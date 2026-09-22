"""Роутер /character — создание, чтение, распределение очков прокачки.

Тонкая оркестрация поверх core/: прочитать состояние -> вызвать функцию
core/ -> сохранить -> вернуть JSON (backend_plan.md §6). Никакой игровой
логики внутри роутера самой по себе.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_api_key
from api.schemas.character import (
    AllocatePointRequest,
    AllocatePointResponse,
    BuyPotionRequest,
    BuyPotionResponse,
    CharacterCreate,
    CharacterOut,
    SellLootResponse,
)
from core import economy as ec
from core import progression as pr
from db.models import Character, CombatSession, StatAllocationLog

router = APIRouter(prefix="/character", tags=["character"], dependencies=[Depends(require_api_key)])

# §2 gameplay_loop_mvp.md — черновые стартовые значения.
BASE_STATS = {"strength": 3, "agility": 3, "luck": 1, "vitality": 3}
STARTING_STAT_POOL = 5


def _now() -> datetime:
    # Naive UTC — см. db/models.py:_utcnow(): колонки без timezone=True,
    # aware здесь привело бы к TypeError при сравнении.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_character_out(character: Character, active_combat_session_id: int | None = None) -> CharacterOut:
    """§8 gameplay_loop_mvp.md: HP пересчитывается на лету при каждом чтении,
    без записи в БД — сама запись меняется только на реальных игровых событиях
    (бой, левел-ап), не на простом чтении состояния.

    `active_combat_session_id` — только для GET /{telegram_user_id} (docs/
    notes.md, п.48): бот проверяет его при /start, чтобы восстановить
    потерянный экран боя вместо показа обычного меню персонажа. Остальные
    вызовы этой функции не ищут активную сессию — не нужно для их ответа."""
    hp_max = pr.calculate_hp_max(character.vitality)
    hp_current = pr.get_current_hp(character.hp_current, hp_max, character.last_hp_update_at, _now())
    return CharacterOut(
        id=character.id,
        telegram_user_id=character.telegram_user_id,
        nickname=character.nickname,
        level=character.level,
        victory_points=character.victory_points,
        points_to_next_level=pr.points_to_next_level(character.victory_points),
        unspent_stat_points=character.unspent_stat_points,
        strength=character.strength,
        agility=character.agility,
        luck=character.luck,
        vitality=character.vitality,
        hp_current=hp_current,
        hp_max=hp_max,
        hp_seconds_to_full=pr.time_to_full_hp(hp_current, hp_max),
        gold=character.gold,
        loot=character.loot,
        potions_small=character.potions_small,
        potions_large=character.potions_large,
        active_combat_session_id=active_combat_session_id,
    )


@router.post("", response_model=CharacterOut, status_code=status.HTTP_201_CREATED)
def create_character(payload: CharacterCreate, db: Session = Depends(get_db)) -> CharacterOut:
    existing = (
        db.query(Character)
        .filter(Character.telegram_user_id == payload.telegram_user_id, Character.is_active.is_(True))
        .first()
    )
    if existing is not None:
        # §1 gameplay_loop_mvp.md: повторный /start не пересоздаёт персонажа.
        return _to_character_out(existing)

    hp_max = pr.calculate_hp_max(BASE_STATS["vitality"])
    character = Character(
        telegram_user_id=payload.telegram_user_id,
        nickname=payload.nickname,
        level=1,
        victory_points=0,
        unspent_stat_points=STARTING_STAT_POOL,
        strength=BASE_STATS["strength"],
        agility=BASE_STATS["agility"],
        luck=BASE_STATS["luck"],
        vitality=BASE_STATS["vitality"],
        hp_current=hp_max,
        last_hp_update_at=_now(),
        is_active=True,
        gold=0,
        loot={},
        potions_small=0,
        potions_large=0,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return _to_character_out(character)


@router.get("/{telegram_user_id}", response_model=CharacterOut)
def get_character(telegram_user_id: int, db: Session = Depends(get_db)) -> CharacterOut:
    character = (
        db.query(Character)
        .filter(Character.telegram_user_id == telegram_user_id, Character.is_active.is_(True))
        .first()
    )
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    # docs/notes.md, п.48 — бот проверяет это поле при /start, чтобы
    # восстановить потерянный экран боя вместо обычного меню персонажа.
    active_session = (
        db.query(CombatSession)
        .filter(CombatSession.character_id == character.id, CombatSession.status != "finished")
        .first()
    )
    return _to_character_out(character, active_combat_session_id=active_session.id if active_session else None)


@router.delete("/{telegram_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def reset_character(
    telegram_user_id: int,
    reason: Literal["manual_reset", "boss_victory"] = Query(...),
    db: Session = Depends(get_db),
) -> None:
    """"Обнулить персонажа" — раньше действительно удаляло строку и каскадом
    CombatSession/StatAllocationLog (docs/notes.md); теперь архивирует
    (docs/notes.md, п.41) — вся история прохождения нужна для аналитики
    (scripts/export_playtest_stats.py) и должна пережить сброс/победу над
    боссом. Название эндпоинта/HTTP-метод не меняли (DELETE
    /character/{telegram_user_id}) — с точки зрения бота ничего не
    изменилось, семантика "сбросить и начать заново" та же самая.

    `reason` — почему архивирован, для аналитики (не влияет на сам сброс):
    "manual_reset" — /reset или "🗑 Обнулить персонажа"; "boss_victory" —
    "🔄 Начать заново" после победы над финальным боссом."""
    character = (
        db.query(Character)
        .filter(Character.telegram_user_id == telegram_user_id, Character.is_active.is_(True))
        .first()
    )
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    character.is_active = False
    character.archived_at = _now()
    character.archived_reason = reason
    db.commit()


@router.post("/{character_id}/allocate_point", response_model=AllocatePointResponse)
def allocate_point(
    character_id: int, payload: AllocatePointRequest, db: Session = Depends(get_db)
) -> AllocatePointResponse:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    # Валидировать имя стата ДО getattr/setattr — иначе payload.stat мог бы
    # указать на произвольный атрибут модели, не только на игровой стат.
    if payload.stat not in pr.STAT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"unknown stat: {payload.stat!r}"
        )

    try:
        new_unspent, new_value = pr.allocate_stat_point(
            character.unspent_stat_points, getattr(character, payload.stat), payload.stat
        )
    except pr.NoStatPointsAvailableError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no unspent stat points available")

    character.unspent_stat_points = new_unspent
    setattr(character, payload.stat, new_value)
    db.add(StatAllocationLog(character_id=character.id, stat=payload.stat, level_at_time=character.level))
    db.commit()
    db.refresh(character)
    return AllocatePointResponse(character=_to_character_out(character))


@router.post("/{character_id}/sell_loot", response_model=SellLootResponse)
def sell_loot(character_id: int, db: Session = Depends(get_db)) -> SellLootResponse:
    """Продаёт весь инвентарь лута разом (docs/gameplay_loop_mvp.md §5) —
    нет отдельного шага "выбрать, что продать": упрощение, как и в
    симуляторе (docs/notes.md, п.26)."""
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    character.gold += ec.sell_loot_value(character.loot)
    character.loot = {}
    db.commit()
    db.refresh(character)
    return SellLootResponse(character=_to_character_out(character))


@router.post("/{character_id}/buy_potion", response_model=BuyPotionResponse)
def buy_potion(character_id: int, payload: BuyPotionRequest, db: Session = Depends(get_db)) -> BuyPotionResponse:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    if payload.size not in ec.POTION_SIZES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"unknown potion size: {payload.size!r}"
        )

    # Проверяем ЗАРАНЕЕ, а не ловим ValueError из ec.buy_potion() — причина
    # отказа ("cap_reached" | "not_enough_gold") идёт в detail явно, бот
    # должен показать игроку правильное сообщение, не общий "нельзя"
    # (docs/gameplay_loop_mvp.md — паттерн видимости кнопок покупки).
    reason = ec.check_can_buy_potion(character.gold, character.potions_small, character.potions_large, payload.size)
    if reason is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    character.gold, character.potions_small, character.potions_large = ec.buy_potion(
        character.gold, character.potions_small, character.potions_large, payload.size
    )
    db.commit()
    db.refresh(character)
    return BuyPotionResponse(character=_to_character_out(character))
