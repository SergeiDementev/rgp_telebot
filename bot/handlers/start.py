"""Хендлеры /start, создание персонажа (gameplay_loop_mvp.md §1-2).

Правила игры — не здесь: живут в bot/handlers/character.py как кнопка на
экране статов (docs/notes.md, п.1), не как отдельная команда, чтобы не
плодить отдельные сообщения не в очереди с редактируемым боевым.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from bot.handlers.character import (
    allocation_keyboard,
    creation_screen_title,
    render_allocation_screen,
    render_stats_screen,
    stats_screen_keyboard,
)
from bot.handlers.combat import build_resume_keyboard, build_resume_text
from bot.utils import (  # noqa: F401 — welcome_text реэкспортируется для тестов
    detect_language,
    start_game_keyboard,
    try_delete_message,
    welcome_text,
)
from core import i18n

router = Router()


def resume_battle_prefix() -> str:
    return i18n.t("start.resume_prefix")


def reset_confirm_text() -> str:
    return i18n.t("start.reset_confirm")


def _reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=i18n.t("start.button.reset_yes"), callback_data="reset_confirm:manual_reset"),
                # "Отмена" ведёт на уже существующий "back_to_stats" (bot/
                # handlers/character.py), не на отдельный текст без кнопок
                # (docs/notes.md) — иначе отмена была тупиком: "Отменено." без
                # единой кнопки, продолжить играть можно было только вручную
                # набрав /start.
                InlineKeyboardButton(text=i18n.t("start.button.cancel"), callback_data="back_to_stats"),
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
        # §1: персонажа ещё нет — предложить создать. Локаль на этот момент
        # уже best-effort выставлена bot/utils.py::set_locale_from_telegram_
        # profile (bot/main.py, docs/notes.md, блок 4) — welcome_text()
        # рендерится на ней без дополнительных действий здесь.
        await message.answer(welcome_text(), reply_markup=start_game_keyboard())
        return

    # docs/notes.md, блок 3 — экраны ниже (render_stats_screen и т.п.) идут
    # через core.i18n.t(), поэтому локаль нужно выставить точнее (по
    # character.language) до их вызова — переопределяет best-effort
    # значение от set_locale_from_telegram_profile.
    i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))

    # docs/notes.md — повторный /start удаляет оба старых постоянных
    # сообщения (приветствие + главный экран) и создаёт новые вместо
    # накопления истории чата. У персонажа, ещё ни разу не проходившего
    # /start после раскатки этого поля, их не будет (None) — try_delete_
    # message тогда просто не вызывается, ничего удалять не пытаемся.
    old_welcome_id = character.get("welcome_message_id")
    old_main_id = character.get("main_message_id")
    if old_welcome_id is not None:
        await try_delete_message(message.bot, message.chat.id, old_welcome_id)
    if old_main_id is not None:
        await try_delete_message(message.bot, message.chat.id, old_main_id)

    # §1: персонаж уже есть — повторный /start не пересоздаёт его. Баннер
    # шлём в любом случае, даже при восстановлении боя ниже — то же самое
    # первое сообщение, что игрок всегда видит на /start.
    welcome_message = await message.answer(welcome_text())

    # docs/notes.md, п.48 — незавершённый бой не теряется, если сообщение с
    # его клавиатурой пропало (например, игрок удалил чат в Telegram):
    # CombatSession в БД остаётся активной, /start восстанавливает экран
    # вместо обычного меню персонажа.
    active_session_id = character.get("active_combat_session_id")
    if active_session_id is not None:
        resume = await api.resume_combat_session(message.from_user.id, active_session_id)
        main_message = await message.answer(
            f"{resume_battle_prefix()}{build_resume_text(resume)}",
            reply_markup=build_resume_keyboard(active_session_id, resume),
        )
    else:
        main_message = await message.answer(render_stats_screen(character), reply_markup=stats_screen_keyboard(character))

    await api.set_message_ids(
        character["id"], welcome_message_id=welcome_message.message_id, main_message_id=main_message.message_id
    )


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

    i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))
    await callback.message.edit_text(
        render_allocation_screen(character, title=creation_screen_title(), mode="creation"),
        reply_markup=allocation_keyboard(character, mode="creation"),
    )
    await callback.answer()


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Обнулить персонажа — в основном для тестирования, но без ограничения
    на окружение (docs/notes.md). Необратимо, поэтому только через
    подтверждение, а не с одного нажатия."""
    await message.answer(reset_confirm_text(), reply_markup=_reset_confirm_keyboard())


@router.callback_query(F.data == "reset_request")
async def reset_request(callback: CallbackQuery) -> None:
    """То же подтверждение, что и /reset, но с кнопки на экране прокачки
    (bot/handlers/character.py) — редактируем то же сообщение, а не шлём
    новое, как остальные экраны вне боя."""
    await callback.message.edit_text(reset_confirm_text(), reply_markup=_reset_confirm_keyboard())
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
    i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))
    await callback.message.edit_text(
        render_allocation_screen(character, title=creation_screen_title(), mode="creation"),
        reply_markup=allocation_keyboard(character, mode="creation"),
    )
    # docs/notes.md — это НОВАЯ строка персонажа (старая архивирована выше),
    # welcome_message_id/main_message_id у неё ещё None. Само сообщение —
    # edit, не новый Telegram-message_id, но это первое закрепление
    # main_message_id за этим персонажем: то самое "создание нового
    # персонажа после /reset" из списка мест, требующих синхронизации.
    # welcome_message_id не трогаем — отдельного приветственного сообщения
    # в этом флоу не было (он приходит только явным следующим /start).
    await api.set_message_ids(character["id"], main_message_id=callback.message.message_id)
    await callback.answer(i18n.t("start.reset_done"))
