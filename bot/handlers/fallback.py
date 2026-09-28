"""Заглушка на любое текстовое сообщение, не подошедшее ни одному хендлеру
выше по цепочке (docs/notes.md).

Роутер регистрируется последним (bot/main.py::build_dispatcher) — aiogram
проверяет роутеры по порядку регистрации, поэтому сюда доходят только
сообщения, не совпавшие ни с одной командой (/start, /reset) в предыдущих
роутерах. Кнопки (CallbackQuery) — отдельный тип апдейта, этого хендлера
не касаются вообще, конфликтовать с ними нечему.

Текст входящего сообщения намеренно нигде не читается и никуда не
передаётся (ни в api, ни куда-либо ещё) — управление в игре только
кнопками под сообщениями, свободный ввод игрока игре не нужен.

Двуязычность (docs/notes.md, блок 6) — хендлер не запрашивает персонажа
(нет api-параметра, ответ ни от чего не зависит), поэтому точного
character.language здесь не узнать; локаль на момент выполнения уже
best-effort выставлена диспетчерской мидлварью bot/utils.py::
set_locale_from_telegram_profile (блок 4, подключена в bot/main.py для
всех Message-хендлеров, этот не исключение)."""

from aiogram import F, Router
from aiogram.types import Message

from core import i18n

router = Router()


@router.message(F.text)
async def unknown_text(message: Message) -> None:
    await message.answer(i18n.t("fallback.unknown_text"))
