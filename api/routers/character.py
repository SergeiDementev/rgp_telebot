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
    CharacterCreate,
    CharacterOut,
)
from core import progression as pr
from db.models import Character

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
    db.commit()
    db.refresh(character)
    return AllocatePointResponse(character=_to_character_out(character))
