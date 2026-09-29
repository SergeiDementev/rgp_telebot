"""Общие мелкие утилиты для хендлеров бота."""

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.client import ApiClient, ApiError
from core import i18n

# welcome_text()/start_game_keyboard живут здесь, а не в bot/handlers/
# start.py (откуда их естественно было бы ожидать), потому что
# get_character_or_prompt_start() ниже нужен и character.py, и combat.py, а
# те, в свою очередь, уже импортируются из start.py — переезд сюда
# единственный способ не завести цикл импортов (bot/utils.py ничего не
# импортирует из bot/handlers/*). bot/handlers/start.py по-прежнему
# реэкспортирует welcome_text для совместимости импортов из тестов.


def welcome_text() -> str:
    """Функция, не константа (docs/notes.md, блок 4) — значение зависит от
    текущей локали. Строка-подсказка про /language убрана (docs/notes.md)
    — основной способ переключения теперь кнопка на главном экране
    персонажа (bot/handlers/character.py::toggle_language), а до него
    ещё нужно дойти, /start сам её не показывает."""
    return i18n.t("start.welcome")


def start_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=i18n.t("start.button.start_game"), callback_data="start_game")]]
    )


def detect_language(language_code: Optional[str]) -> str:
    """Язык персонажа по умолчанию при первом создании (docs/notes.md) —
    из message.from_user.language_code Telegram (двух-трёхбуквенный код,
    иногда с региональным суффиксом вроде "ru-RU"/"en-US", иногда
    отсутствует вовсе — Telegram его не гарантирует). "ru"/"ru-RU"/... →
    "ru", всё остальное, включая None, → "en"."""
    return "ru" if language_code is not None and language_code.startswith("ru") else "en"


async def set_locale_from_telegram_profile(
    handler: Callable[[Union[Message, CallbackQuery], dict], Awaitable[Any]],
    event: Union[Message, CallbackQuery],
    data: dict,
) -> Any:
    """Диспетчерская мидлварь (docs/notes.md, блок 4; подключена в
    bot/main.py::build_dispatcher для Message и CallbackQuery — раньше
    аналогичная логика была только в bot/handlers/combat.py, локальной для
    одного роутера; вынесена сюда и обобщена, чтобы покрыть все хендлеры
    разом, включая /start и /reset до того, как персонаж вообще известен).

    Ставит best-effort локаль по профилю Telegram (detect_language) ДО
    того, как выполнится любой хендлер любого роутера — без этого контекст
    оставался бы на DEFAULT_LOCALE ("ru") везде, где хендлер не запрашивает
    персонажа явно (у aiogram свежий contextvars.Context на каждый апдейт,
    docs/notes.md, блок 3 — не наследуется от предыдущего). Хендлеры,
    которые знают точный character.language (через get_character_or_
    prompt_start или свой прямой api.get_character()), переопределяют это
    значение точнее чуть позже в себе самих — обе точки set_locale()
    безопасны в любом порядке."""
    i18n.set_locale(detect_language(event.from_user.language_code))
    return await handler(event, data)


async def try_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    """Пытается удалить сообщение по id (docs/notes.md) — используется, когда
    объекта Message под рукой нет (например, /start удаляет СТАРЫЕ постоянные
    сообщения по сохранённым welcome_message_id/main_message_id перед тем,
    как прислать новые, bot/handlers/start.py::cmd_start). Любая ошибка
    Telegram (сообщение уже недоступно, устарело, чат другой) — не
    пробрасывается дальше, просто пропускаем этот шаг для конкретного
    сообщения, как и просили: не должно мешать создать новые."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def try_edit_message_text(
    bot: Bot, chat_id: int, message_id: int, text: str, *, reply_markup: Optional[InlineKeyboardMarkup] = None
) -> bool:
    """Пытается отредактировать сообщение по id, не имея объекта Message под
    рукой (docs/notes.md) — например, переключатель языка на главном экране
    физически нажат на ОДНОМ постоянном сообщении, но должен дотянуться и до
    ВТОРОГО (bot/handlers/character.py::toggle_language). Любая ошибка
    Telegram — не бросается дальше, просто False, чтобы вызывающий код мог
    graceful продолжить с тем, что получилось."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
        return True
    except TelegramBadRequest:
        return False


async def safe_edit_text(message: Message, text: str, *, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """edit_text, но не падает, если контент не изменился.

    Нужно для кнопки "Обновить": если состояние с прошлого раза не
    поменялось (например, HP уже полностью восстановилось), Telegram
    отвечает ошибкой "message is not modified" на identical text+markup.
    Без обработки исключение прилетает раньше callback.answer() — спиннер
    на кнопке не гаснет, выглядит как зависание (docs/notes.md)."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message:
            raise


# docs/notes.md — ревизия двуязычности нашла три гонки с одной причиной:
# несколько хендлеров делают цикл "прочитать состояние персонажа (в т.ч.
# welcome_message_id/main_message_id) -> изменить -> записать" без всякой
# защиты от того, что тот же игрок нажмёт кнопку/пошлёт команду второй раз
# до завершения первого вызова (двойной тап). In-process asyncio.Lock на
# telegram_user_id технически достаточен: docker-compose.yml запускает
# сервис `bot` ЕДИНСТВЕННЫМ инстансом (одна команда `python -m bot.main`,
# без deploy.replicas и без второго bot-сервиса) — все апдейты одного
# пользователя обрабатываются в одном и том же процессе/event loop, внешний
# межпроцессный лок (Redis и т.п.) не нужен. Если это когда-нибудь
# изменится (несколько инстансов бота), этот механизм придётся заменить —
# тогда же стоит пересмотреть и само допущение.
#
# defaultdict, не явная очистка по TTL/по завершении использования — лок на
# каждого нового telegram_user_id создаётся один раз и живёт до перезапуска
# процесса; на масштабе этого бота (не миллионы пользователей) это не
# больше нескольких КБ памяти за всё время жизни процесса, специально не
# усложняем ради этого.
_user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def user_lock(telegram_user_id: int) -> asyncio.Lock:
    """Лок на пользователя (docs/notes.md) — оборачивает весь путь "прочитать
    состояние -> изменить -> записать" в хендлерах, где повторный/
    конкурентный вызов того же игрока мог бы иначе прочитать УСТАРЕВШЕЕ
    состояние (welcome_message_id/main_message_id, character.language) и
    записать поверх него результат, потеряв изменения первого вызова.
    Второй конкурентный вызов ждёт первого и продолжает уже с актуальным
    состоянием (свежий api.get_character() внутри `async with` этого лока),
    а не отклоняется — так по каждому из трёх мест это и разумнее (не
    дублировать сообщения при двойном /start, применить оба переключения
    языка последовательно и т.п., см. docs/notes.md)."""
    return _user_locks[telegram_user_id]


async def get_character_or_prompt_start(callback: CallbackQuery, api: ApiClient) -> Optional[dict]:
    """Общая обёртка над api.get_character() для колбэков экранов вне боя.

    Персонажа может не быть — например, свежая БД после переезда на новую
    СУБД, или устаревшая клавиатура на старом сообщении в чате (docs/
    notes.md). Раньше каждый такой хендлер падал необработанным 404 —
    нажатие выглядело как зависание, без единого сообщения игроку. Теперь —
    то же приглашение "Начать игру", что и при самом первом /start
    (bot/handlers/start.py::cmd_start). Возвращает None, если персонажа нет
    (экран уже отредактирован здесь, вызывающий хендлер должен сразу
    return), иначе — сам персонаж.

    Заодно выставляет текущую локаль (core.i18n.set_locale) по
    character["language"] (docs/notes.md, блок 3) — единственная общая
    точка входа для character.py/combat.py, поэтому самое естественное
    место сделать это один раз, без лишнего запроса к API.
    bot/handlers/start.py не проходит через эту функцию (свой прямой
    api.get_character()) и выставляет локаль сама, тем же способом.
    `.get(..., DEFAULT_LOCALE)`, не прямой доступ по ключу — реальный API
    всегда отдаёт language (обязательное поле, api/schemas/character.py),
    но часть моков в тестах его не имитирует и это не повод падать здесь с
    KeyError. 404-ветка ничего не переопределяет сама (docs/notes.md,
    блок 4) — welcome_text() уже рендерится на локали, выставленной
    set_locale_from_telegram_profile до входа сюда."""
    try:
        character = await api.get_character(callback.from_user.id)
    except ApiError as error:
        if error.status_code != 404:
            raise
        await safe_edit_text(callback.message, welcome_text(), reply_markup=start_game_keyboard())
        await callback.answer()
        return None
    i18n.set_locale(character.get("language", i18n.DEFAULT_LOCALE))
    return character
