"""Хендлеры /start, создание персонажа (gameplay_loop_mvp.md §1-2).

Правила игры — не здесь: живут в bot/handlers/character.py как кнопка на
экране статов (docs/notes.md, п.1), не как отдельная команда, чтобы не
плодить отдельные сообщения не в очереди с редактируемым боевым.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from bot.handlers.character import allocation_keyboard, render_allocation_screen, render_stats_screen, stats_screen_keyboard
from bot.handlers.combat import build_resume_keyboard, build_resume_text
from bot.utils import WELCOME_TEXT, detect_language, start_game_keyboard  # noqa: F401 — WELCOME_TEXT реэкспортируется для тестов

router = Router()

RESUME_BATTLE_PREFIX = "↩️ Продолжаем начатый бой:\n\n"

RESET_CONFIRM_TEXT = (
    "⚠️ Точно обнулить персонажа?\n\n"
    "Статы, уровень и весь прогресс будут удалены безвозвратно — отменить это будет нельзя."
)


def _reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data="reset_confirm:manual_reset"),
                # "Отмена" ведёт на уже существующий "back_to_stats" (bot/
                # handlers/character.py), не на отдельный текст без кнопок
                # (docs/notes.md) — иначе отмена была тупиком: "Отменено." без
                # единой кнопки, продолжить играть можно было только вручную
                # набрав /start.
                InlineKeyboardButton(text="Отмена", callback_data="back_to_stats"),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, api: ApiClient) -> None:
    try:
        character = await api.get_character(message.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        # §1: персонажа ещё нет — предложить создать.
        await message.answer(WELCOME_TEXT, reply_markup=start_game_keyboard())
        return

    # §1: персонаж уже есть — повторный /start не пересоздаёт его. Баннер
    # шлём в любом случае, даже при восстановлении боя ниже — то же самое
    # первое сообщение, что игрок всегда видит на /start.
    await message.answer(WELCOME_TEXT)

    # docs/notes.md, п.48 — незавершённый бой не теряется, если сообщение с
    # его клавиатурой пропало (например, игрок удалил чат в Telegram):
    # CombatSession в БД остаётся активной, /start восстанавливает экран
    # вместо обычного меню персонажа.
    active_session_id = character.get("active_combat_session_id")
    if active_session_id is not None:
        resume = await api.resume_combat_session(message.from_user.id, active_session_id)
        await message.answer(
            f"{RESUME_BATTLE_PREFIX}{build_resume_text(resume)}",
            reply_markup=build_resume_keyboard(active_session_id, resume),
        )
        return

    await message.answer(render_stats_screen(character), reply_markup=stats_screen_keyboard(character))


@router.callback_query(F.data == "start_game")
async def start_game(callback: CallbackQuery, api: ApiClient) -> None:
    try:
        character = await api.get_character(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        # docs/notes.md — язык по умолчанию только для по-настоящему нового
        # персонажа; при повторном /start (get_character успевает) язык уже
        # выбран раньше и его не переопределяем.
        language = detect_language(callback.from_user.language_code)
        character = await api.create_character(callback.from_user.id, callback.from_user.full_name, language)

    await callback.message.edit_text(
        render_allocation_screen(character, title="🧙 Создание героя", mode="creation"),
        reply_markup=allocation_keyboard(character, mode="creation"),
    )
    await callback.answer()


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Обнулить персонажа — в основном для тестирования, но без ограничения
    на окружение (docs/notes.md). Необратимо, поэтому только через
    подтверждение, а не с одного нажатия."""
    await message.answer(RESET_CONFIRM_TEXT, reply_markup=_reset_confirm_keyboard())


@router.callback_query(F.data == "reset_request")
async def reset_request(callback: CallbackQuery) -> None:
    """То же подтверждение, что и /reset, но с кнопки на экране прокачки
    (bot/handlers/character.py) — редактируем то же сообщение, а не шлём
    новое, как остальные экраны вне боя."""
    await callback.message.edit_text(RESET_CONFIRM_TEXT, reply_markup=_reset_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("reset_confirm:"))
async def reset_confirm(callback: CallbackQuery, api: ApiClient) -> None:
    """Сразу после архивации (docs/notes.md, п.41 — раньше было "удаление")
    создаём нового персонажа и показываем экран создания — без
    приветственного текста (он уже был показан при первом /start, повторно
    не нужен, docs/notes.md) и без лишнего клика "Начать игру": намерение
    начать заново уже подтверждено кнопкой "Да, удалить"/"Начать заново".

    Причина в самом callback_data ("manual_reset" — эта кнопка, "boss_
    victory" — экран поздравления после босса, bot/handlers/combat.py::
    _boss_victory_keyboard) — только для аналитики на сервере, поведение
    бота от неё не зависит."""
    reason = callback.data.split(":", 1)[1]
    # docs/notes.md — язык переносится со старого персонажа на нового, не
    # переопределяется заново по language_code: если игрок явно выбрал язык
    # через /language, обнуление персонажа не должно тихо сбрасывать этот
    # выбор обратно к автоопределению.
    old_character = await api.get_character(callback.from_user.id)
    await api.delete_character(callback.from_user.id, reason=reason)
    character = await api.create_character(
        callback.from_user.id, callback.from_user.full_name, old_character["language"]
    )
    await callback.message.edit_text(
        render_allocation_screen(character, title="🧙 Создание героя", mode="creation"),
        reply_markup=allocation_keyboard(character, mode="creation"),
    )
    await callback.answer("Персонаж обнулён")
