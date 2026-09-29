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
    get_character_or_prompt_start,
    start_game_keyboard,
    try_delete_message,
    user_lock,
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
    # docs/notes.md — ревизия двуязычности: весь цикл "прочитать
    # welcome_message_id/main_message_id -> отправить новые -> сохранить"
    # под локом на пользователя (bot/utils.py::user_lock). Без этого
    # двойной быстрый /start (обе гонки читают одни и те же старые id) шлёт
    # 4 новых сообщения вместо 2 и теряет id первой пары навсегда — вторая
    # гонка теперь просто ждёт первую и стартует уже с её результатом
    # (свежим api.get_character() ниже), а не с устаревшим.
    async with user_lock(message.from_user.id):
        try:
            character = await api.get_character(message.from_user.id)
        except ApiError as error:
            if error.status_code != 404:
                raise
            # §1: персонажа ещё нет — предложить создать. Локаль на этот
            # момент уже best-effort выставлена bot/utils.py::
            # set_locale_from_telegram_profile (bot/main.py, docs/notes.md,
            # блок 4) — welcome_text() рендерится на ней без дополнительных
            # действий здесь.
            await message.answer(welcome_text(), reply_markup=start_game_keyboard())
            return

        # docs/notes.md, блок 3 — экраны ниже (render_stats_screen и т.п.)
        # идут через core.i18n.t(), поэтому локаль нужно выставить точнее
        # (по character.language) до их вызова — переопределяет
        # best-effort значение от set_locale_from_telegram_profile.
        i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))

        # docs/notes.md — повторный /start удаляет оба старых постоянных
        # сообщения (приветствие + главный экран) и создаёт новые вместо
        # накопления истории чата. У персонажа, ещё ни разу не
        # проходившего /start после раскатки этого поля, их не будет
        # (None).
        old_welcome_id = character.get("welcome_message_id")
        old_main_id = character.get("main_message_id")

        # docs/notes.md, ревизия двуязычности — старые сообщения удаляются
        # ПОСЛЕ того, как новые отправлены и их id сохранены в БД, не до
        # (раньше было наоборот). Если отправка нового сообщения сорвётся
        # (сетевой сбой на самом Telegram-запросе, не бизнес-ошибка вида
        # TelegramBadRequest — тот ожидаемый случай уже покрыт
        # try_delete_message ниже), БД должна по-прежнему указывать на ещё
        # РЕАЛЬНО существующие старые сообщения, а не на уже удалённые. Со
        # старым порядком (сначала удалить, потом слать) ровно в этом
        # сценарии на мгновение возникало состояние "id в БД есть, а
        # сообщения уже нет" — текущий порядок исключает это состояние
        # целиком, без необходимости ничего откатывать в БД на None при
        # сбое: если отправка не удалась, БД просто не переписывается
        # вообще, а старые сообщения остаются на месте.
        active_session_id = character.get("active_combat_session_id")
        if active_session_id is not None:
            # docs/notes.md, п.48 — незавершённый бой не теряется, если
            # сообщение с его клавиатурой пропало (например, игрок удалил
            # чат в Telegram): CombatSession в БД остаётся активной,
            # /start восстанавливает экран вместо обычного меню персонажа.
            resume = await api.resume_combat_session(message.from_user.id, active_session_id)
            main_content = f"{resume_battle_prefix()}{build_resume_text(resume)}"
            main_markup = build_resume_keyboard(active_session_id, resume)
        else:
            main_content = render_stats_screen(character)
            main_markup = stats_screen_keyboard(character)

        try:
            # §1: персонаж уже есть — повторный /start не пересоздаёт его.
            # Баннер шлём в любом случае, даже при восстановлении боя
            # выше — то же самое первое сообщение, что игрок всегда видит
            # на /start.
            welcome_message = await message.answer(welcome_text())
            main_message = await message.answer(main_content, reply_markup=main_markup)
        except Exception:
            # Best-effort: та же связь, что подвела отправку выше, может
            # всё же оказаться жива для короткого сообщения без
            # клавиатуры — но если и эта попытка сорвётся, второй сбой не
            # маскируем повторным try.
            try:
                await message.answer(i18n.t("start.error.send_failed"))
            except Exception:
                pass
            raise

        await api.set_message_ids(
            character["id"], welcome_message_id=welcome_message.message_id, main_message_id=main_message.message_id
        )

        if old_welcome_id is not None:
            await try_delete_message(message.bot, message.chat.id, old_welcome_id)
        if old_main_id is not None:
            await try_delete_message(message.bot, message.chat.id, old_main_id)


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
async def cmd_reset(message: Message, api: ApiClient) -> None:
    """Обнулить персонажа — в основном для тестирования, но без ограничения
    на окружение (docs/notes.md). Необратимо, поэтому только через
    подтверждение, а не с одного нажатия.

    docs/notes.md, ревизия двуязычности — подтягивает точную локаль
    персонажа (character.language), не best-effort язык клиента Telegram:
    без этого подтверждение могло "залипать" на старом языке после
    переключения кнопкой. Не через get_character_or_prompt_start — та на
    404 показывает приглашение "Начать игру" и не отправляет ничего
    дальше, а здесь нужно показать подтверждение сброса в любом случае
    (несуществующего персонажа реально обнулить нечем, но это не новая
    проблема этого фикса — reset_confirm и раньше падал на своём
    api.get_character() при подтверждении)."""
    try:
        character = await api.get_character(message.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
    else:
        i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))
    await message.answer(reset_confirm_text(), reply_markup=_reset_confirm_keyboard())


@router.callback_query(F.data == "reset_request")
async def reset_request(callback: CallbackQuery, api: ApiClient) -> None:
    """То же подтверждение, что и /reset, но с кнопки на экране прокачки
    (bot/handlers/character.py) — редактируем то же сообщение, а не шлём
    новое, как остальные экраны вне боя.

    docs/notes.md, ревизия двуязычности — запрашивает персонажа ради
    точной локали (тот же фикс, что и у show_rules в bot/handlers/
    character.py): без этого подтверждение залипало на языке клиента
    Telegram вместо только что выбранного языка персонажа."""
    character = await get_character_or_prompt_start(callback, api)
    if character is None:
        return
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
    бота от неё не зависит.

    docs/notes.md, ревизия двуязычности, №86 закрыт — под тем же локом на
    пользователя (bot/utils.py::user_lock), что и cmd_start/toggle_language:
    двойной тап на "Да, удалить" иначе мог бы архивировать/создавать
    персонажа дважды подряд на устаревших данных. Заодно закрывает сироту
    прежнего main-сообщения (см. комментарий у try_delete_message ниже)."""
    async with user_lock(callback.from_user.id):
        reason = callback.data.split(":", 1)[1]
        # docs/notes.md — язык переносится со старого персонажа на нового,
        # не переопределяется заново по language_code: если игрок явно
        # выбрал язык через /language, обнуление персонажа не должно тихо
        # сбрасывать этот выбор обратно к автоопределению.
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
        # docs/notes.md — это НОВАЯ строка персонажа (старая архивирована
        # выше), welcome_message_id/main_message_id у неё ещё None. Само
        # сообщение — edit, не новый Telegram-message_id, но это первое
        # закрепление main_message_id за этим персонажем: то самое
        # "создание нового персонажа после /reset" из списка мест,
        # требующих синхронизации.
        #
        # welcome_message_id — ПЕРЕНОСИТСЯ со старого персонажа, той же
        # логикой, что и language чуть выше: это тот же физический
        # Telegram-message, никуда не делся, просто у новой строки
        # персонажа поле стартует с None. Раньше его "не трогали" — верно
        # для НОВОГО приветственного сообщения (в этом флоу оно
        # действительно не отправляется), но неверно для СТАРОГО: без
        # переноса бот переставал его знать — не обновлял при следующем
        # toggle_language (id уже None) и не удалял следующим /start (та же
        # причина, old_welcome_id тоже читался бы как None) — оно оставалось
        # висеть в чате бессрочно, замороженное на языке персонажа ДО
        # сброса (баг-репорт: "приветственное сообщение как будто теряет
        # связь с приложением").
        await api.set_message_ids(
            character["id"],
            main_message_id=callback.message.message_id,
            welcome_message_id=old_character.get("welcome_message_id"),
        )

        # docs/notes.md, №86 — подтверждение могло прийти НЕ с того же
        # сообщения, что было main_message (/reset-команда шлёт отдельное
        # подтверждение НОВЫМ сообщением через cmd_reset, в отличие от
        # кнопки "🗑 Обнулить персонажа" на экране прокачки, которая
        # редактирует то же main-сообщение). В этом случае прежнее
        # main-сообщение только что потеряло свой id из БД (перезаписан
        # выше на id ЭТОГО сообщения) и без явного удаления остаётся
        # сиротой в чате навсегда. old_character уже прочитан под локом
        # выше — это его настоящий, ещё актуальный на момент чтения id.
        old_main_id = old_character.get("main_message_id")
        if old_main_id is not None and old_main_id != callback.message.message_id:
            await try_delete_message(callback.bot, callback.message.chat.id, old_main_id)

        await callback.answer(i18n.t("start.reset_done"))
