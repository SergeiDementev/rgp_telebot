"""Роутер /character — создание, чтение, распределение очков прокачки.

Тонкая оркестрация поверх core/: прочитать состояние -> вызвать функцию
core/ -> сохранить -> вернуть JSON (backend_plan.md §6). Никакой игровой
логики внутри роутера самой по себе.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
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
    # Naive UTC — см. db/models.py:_utcnow(): SQLite всегда возвращает
    # naive-datetime, aware здесь привело бы к TypeError при сравнении.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_character_out(character: Character) -> CharacterOut:
    """§8 gameplay_loop_mvp.md: HP пересчитывается на лету при каждом чтении,
    без записи в БД — сама запись меняется только на реальных игровых событиях
    (бой, левел-ап), не на простом чтении состояния."""
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
    )


@router.post("", response_model=CharacterOut, status_code=status.HTTP_201_CREATED)
def create_character(payload: CharacterCreate, db: Session = Depends(get_db)) -> CharacterOut:
    existing = db.query(Character).filter(Character.telegram_user_id == payload.telegram_user_id).first()
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
    character = db.query(Character).filter(Character.telegram_user_id == telegram_user_id).first()
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")
    return _to_character_out(character)


@router.delete("/{telegram_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(telegram_user_id: int, db: Session = Depends(get_db)) -> None:
    """Обнулить персонажа — в основном для тестирования (docs/notes.md), но
    без ограничения на окружение. Удаляет и все его CombatSession/
    StatAllocationLog — прямого каскада на уровне БД нет (db/models.py),
    делаем явно в правильном порядке (дочерние таблицы, потом сам
    персонаж), иначе осиротевшие строки останутся в БД."""
    character = db.query(Character).filter(Character.telegram_user_id == telegram_user_id).first()
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="character not found")

    db.query(CombatSession).filter(CombatSession.character_id == character.id).delete()
    db.query(StatAllocationLog).filter(StatAllocationLog.character_id == character.id).delete()
    db.delete(character)
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
