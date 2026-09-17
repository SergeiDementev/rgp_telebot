# План бэкенда — Telegram RPG

Документ описывает архитектуру и порядок реализации бэкенда поверх уже согласованных `combat_mechanics.md` (боевое ядро) и `gameplay_loop_mvp.md` (игровой цикл). Здесь — только техническая структура: стек, слои, модели, эндпоинты, порядок работ.

---

## 1. Стек

- **Backend:** Python + FastAPI — автоматическая валидация запросов (Pydantic), автогенерация OpenAPI/Swagger-документации, асинхронность из коробки.
- **БД:** SQLite для старта (ноль конфигурации), SQLAlchemy как ORM — переход на PostgreSQL при росте нагрузки потребует смены только строки подключения.
- **Бот:** aiogram (Python) — общий язык с бэкендом, можно переиспользовать Pydantic-модели между ботом и API при необходимости.
- **HTTP-клиент бота → API:** httpx (асинхронный).

---

## 2. Принципы архитектуры (напоминание, уже согласовано ранее)

- **`core/` не знает про HTTP, БД, Telegram.** Только чистые функции. Тестируется и симулируется независимо от всего остального.
- **Все вычисления — на сервере.** Бот не хранит и не вычисляет игровую логику, только инициирует запросы и отображает готовый результат.
- **Пошаговая обработка боя.** Один HTTP-запр: один ход. Состояние боя живёт в БД между запросами.
- **Единая механика PvE/PvP.** `core/combat_mechanics.py` не различает, кто управляет стороной — разница только в том, кто инициирует запрос на ход.

---

## 3. Структура проекта

```
project/
├── core/                    # чистая игровая логика, без внешних зависимостей
│   ├── combat_mechanics.py  # см. combat_mechanics.md (circumstance — часть этого файла, не отдельный модуль) — готово
│   ├── progression.py       # формулы уровней, регенерации HP, наград, очков прокачки — готово
│   └── economy.py           # готово (docs/notes.md п.30): LOOT_TABLE, цены/капы зелий — единый источник
│                            # для api/ и scripts/simulate_combat_economy.py, не дублируются
│
├── api/                     # FastAPI-приложение — готово (этап 3)
│   ├── main.py               # сборка приложения, create_all(), /health
│   ├── routers/
│   │   ├── character.py     # создание/просмотр персонажа, прокачка
│   │   ├── encounter.py     # поиск противника + инициатива/обстоятельство (/start)
│   │   └── combat.py        # confirm/turn/flee_decision/use_potion/get — цикл ходов боя
│   ├── schemas/              # Pydantic-модели запросов/ответов (character.py, combat.py)
│   ├── rendering.py           # структурированные факты боя → готовый текст для клиента
│   ├── dependencies.py       # сессия БД, авторизация бота, получение текущего персонажа
│   └── enemy_content.py      # загрузка content/enemies.json
│
├── db/                       # готово
│   ├── models.py             # SQLAlchemy-модели: Character, CombatSession
│   └── session.py            # подключение, фабрика сессий
│
├── alembic.ini, migrations/  # alembic-миграции (заведены 2026-09-16) — схему БД
│                              # создаёт и обновляет только `alembic upgrade head`,
│                              # само приложение при старте её больше не трогает
│
├── content/                  # статичные игровые данные — готово (этап 2)
│   └── enemies.json          # статы мышь/волк/кабан
│
├── scripts/                  # готово
│   ├── simulate_combat.py         # консольный симулятор боёв для калибровки (см. §8, этап 2)
│   ├── simulate_combat_economy.py # + слой экономики (лут/золото/зелья) поверх того же движка
│   └── simulate_boss.py           # калибровка статов финального босса (docs/notes.md пп.26-29)
│
├── tests/                     # готово — pytest, зеркалит структуру выше
│   ├── core/
│   ├── api/                  # conftest.py — изолированная SQLite на тест, dependency_overrides
│   ├── scripts/
│   └── bot/                   # моки Message/CallbackQuery и ApiClient — без реального Telegram/сети
│
├── requirements.txt            # рантайм: fastapi/sqlalchemy/pydantic/uvicorn/aiogram/httpx/python-dotenv
├── requirements-dev.txt        # + pytest/pytest-asyncio
│
├── .env.example                 # шаблон: TELEGRAM_BOT_TOKEN, API_BASE_URL, INTERNAL_API_KEY
│
└── bot/                       # Telegram-клиент (aiogram) — готово (этап 4)
    ├── client.py              # асинхронная обёртка над httpx для вызовов api/
    ├── handlers/
    │   ├── start.py           # /start, /rules, создание персонажа
    │   ├── character.py       # экран статов, "Меню игрока" (статы/прокачка + золото/лут/зелья,
    │   │                      # docs/notes.md п.30; общий экран для создания и левел-апа)
    │   └── combat.py          # весь боевой цикл — поиск, инициатива, ходы, завершение
    └── main.py                 # сборка Dispatcher, регистрация роутеров, polling
```

---

## 4. Модели БД

```python
class Character:
    id: int
    telegram_user_id: int        # уникальный ключ для идентификации при запросах от бота
    nickname: str                # берётся из Telegram при создании
    level: int
    victory_points: int          # накопительно, не расходуется — только двигает уровень
    unspent_stat_points: int     # очки прокачки, начисленные при левел-апе, ждут распределения
    strength: int
    agility: int
    luck: int
    vitality: int                 # "Здоровье" — влияет на hp_max, не на скорость регенерации
    hp_current: float
    last_hp_update_at: datetime   # для ленивого пересчёта регенерации
    created_at: datetime

    # docs/notes.md п.30 — "Меню игрока": экономика поверх боя
    gold: int = 0                 # копится продажей лута, тратится на зелья
    loot: JSON                     # {"<item_name>": <count>, ...} — стакается; цены/веса — в core/economy.py,
                                    # не в БД, здесь только количество у персонажа
    potions_small: int = 0
    potions_large: int = 0        # оба капа (SMALL_POTION_CAP=5 / LARGE_POTION_CAP=3) — тоже в core/economy.py,
                                    # перенесены из допущения симулятора в постоянное правило игры

class CombatSession:
    id: int
    character_id: int
    enemy_type: str                # "mouse" | "wolf" | "boar"
    enemy_hp_current: float        # enemy_hp_max НЕ хранится — статичен, читается из content/enemies.json
    character_hp_snapshot: float   # живой HP персонажа во время боя (обновляется на каждом ударе)
    current_turn: str | None       # "player" | "enemy"; None до /combat/{id}/start (инициатива ещё не брошена)
    status: str                    # "awaiting_initiative" | "awaiting_confirmation" | "active" | "finished"
    result: str | None             # "victory" | "defeat" | "player_fled" | "enemy_fled"
    circumstance_outcome: str | None   # "buff" | "debuff" | None
    circumstance_roller: str | None    # "player" | "enemy" — кто кинул обстоятельство
    strength_modifier_player: float = 1.0
    strength_modifier_enemy: float = 1.0
    player_flee_right_used: bool = False
    enemy_flee_right_used: bool = False
    turn_log: JSON                  # накопительный лог событий (для отображения в боте)
    created_at, updated_at: datetime
```

Право на побег (§6 combat_mechanics.md) разведено на `player_flee_right_used`/`enemy_flee_right_used`, не общий флаг — право принадлежит стороне, а не сессии целиком, иначе побег одной стороны мог бы случайно сжечь право другой. Оба поля живут в `CombatSession`, не в `Character` — сгорают только в рамках одного боя, не переносятся между боями.

---

## 5. Эндпоинты

```
POST   /character                      — создать персонажа (nickname из Telegram, стартовые статы)
GET    /character/{telegram_user_id}   — текущее состояние (HP пересчитывается на лету при чтении)
POST   /character/{id}/allocate_point  — потратить одно очко прокачки: {"stat": "strength"}
DELETE /character/{telegram_user_id}   — обнулить персонажа целиком (удаляет и его CombatSession);
                                          в основном для тестирования (docs/notes.md, п.12), через
                                          подтверждение на стороне бота, не по одному нажатию

POST   /character/{id}/sell_loot       — docs/notes.md п.30: продать весь лут разом, начислить
                                          gold по ценам из core/economy.py; инвентарь лута обнуляется
POST   /character/{id}/buy_potion      — {"size": "small" | "large"} — проверяет gold >= цена
                                          И потолок капа (core/economy.py) не достигнут; при нарушении
                                          любого условия — понятная ошибка (4xx с причиной detail =
                                          "not_enough_gold" | "cap_reached"), не молчаливый no-op —
                                          бот показывает игроку разный alert по этим двум причинам

POST /encounter/search               — бросок d10 (50/30/20), создание CombatSession
                                        (status="awaiting_initiative")
POST /combat/{id}/start              — бросок инициативы + обстоятельства одним вызовом
                                        (status -> "awaiting_confirmation")

POST /combat/{id}/confirm            — { "decision": "fight" | "flee" } — после обстоятельства
POST /combat/{id}/turn               — выполнить один ход игрока (+ автоматически ход бота,
                                        если следующая очередь его)
POST /combat/{id}/flee_decision      — { "decision": "flee" | "continue" } — по HP-порогу
POST /combat/{id}/use_potion         — docs/notes.md п.33: { "size": "small" | "large" } — явное
                                        действие игрока кнопкой на его ходу атаки, заменяет удар
                                        в этот ход (передаёт ход противнику). Лимит — раз за бой,
                                        общий на оба размера. 409, если не бой не активен/не ход
                                        игрока; 400 с detail="already_used"|"not_owned" — бот
                                        показывает разное сообщение по причине
GET  /combat/{id}                    — текущее состояние сессии (восстановление после сбоя бота)
```

`CombatTurnResponse` (ответы `/confirm`, `/turn`, `/flee_decision`, `/use_potion`) несёт снимок инвентаря зелий игрока (`potions_small`, `potions_large`, `potion_used_this_battle`) — бот решает по нему, показывать ли кнопки "🧪 Малое"/"🧪 Большое" на следующем ходу, без отдельного `GET /character` на каждом шаге.

`/encounter/search` и `/combat/{id}/start` — два отдельных запроса, а не один: в `gameplay_loop_mvp.md` §9 это два отдельных нажатия кнопки ("Искать противника", затем отдельно "Определить инициативу"), а принцип "один HTTP-запрос = один шаг" (§1) требует по запросу на каждое нажатие.

Ни один эндпоинт не принимает от клиента сырых результатов бросков или урона — только идентификаторы и явные решения игрока (fight/flee/continue, какой стат прокачать).

---

## 6. Пример потока одного обработчика (оркестрация, без игровой логики внутри)

Черновик этого раздела предполагал единую функцию ядра `core.resolve_turn(...)`,
возвращающую готовый результат всего хода. По факту такой функции в `core/`
нет и не появилось: композиция "проверка двойного удара → 1-2 удара → проверка
конца боя" требует состояния сессии (`current_turn`, флаги права на побег),
которое `core/` намеренно не знает — доменные формулы (`resolve_strike`,
`is_double_strike_triggered` и т.д. из `core/combat_mechanics.py`) вызываются
по отдельности прямо в роутере, а не через одну "мега-функцию хода". Реальная
реализация — `api/routers/combat.py` (`_resolve_attacker_turn`), сокращённо:

```python
@router.post("/combat/{combat_session_id}/turn")
def take_turn(combat_session_id: int, character=Depends(get_current_character), db=Depends(get_db)):
    session = _load_owned_session(db, combat_session_id, character)
    # ... проверки статуса, ворота побега (§6 combat_mechanics.md) ...

    attacker_role = session.current_turn
    ds_faces = cm.calculate_double_strike_success_faces(attacker_luck, DOUBLE_STRIKE_K)
    triggered = cm.is_double_strike_triggered(random.randint(1, 10), ds_faces)

    for _ in range(2 if triggered else 1):
        strike = cm.resolve_strike(attacker_strength, defender_agility, ...)
        # применить урон к session.enemy_hp_current / session.character_hp_snapshot
        # если защищающийся пал — session.status = "finished", начислить награду

    db.commit()
    return CombatTurnResponse(...)
```

Правило то же, что и в черновике: обработчик = прочитать состояние → вызвать функции `core/` → сохранить → вернуть JSON. Никакой логики броска/урона/условий внутри роутера — только их композиция.

---

## 7. Рендеринг событий боя (turn_log и текст)

**Принцип:** вся логика боя и весь текст, который её описывает, — на бэкенде. Бот (и любой другой будущий фронтенд) не формирует и не интерпретирует события боя — он получает от API уже готовый текст и просто показывает его. Это разделено на два слоя внутри бэкенда, чтобы не терять переносимость на другой фронтенд/язык/формат позже:

1. **`core/combat_mechanics.py`** — считает структурированные факты (какие грани выпали, какой урон, сработал ли уворот). Не знает о тексте вообще.
2. **`api/rendering.py`** — отдельный модуль, превращающий структурированные факты в готовый текст ответа. Единственное место, где "решается", как это выглядит для человека.

**`turn_log` в БД хранит структурированные факты, а не готовый текст** — это исторический источник истины про бой (для отладки, статистики, восстановления состояния), и структурированные данные компактнее и не привязаны к конкретному языку/стилю отображения.

Пример записи в `turn_log`:

```json
{
  "type": "strike",
  "side": "player",
  "attack_roll": 8,
  "attack_percent": 80,
  "dodge_roll": 6,
  "dodged": false,
  "damage": 64,
  "target_hp_after": 36
}
```

Другие типы событий по той же логике — только факты, без текста: `"type": "initiative"`, `"type": "circumstance"`, `"type": "double_strike_check"`, `"type": "flee_attempt"` и т.д., с соответствующими полями бросков и результатов.

Готовый текст **не хранится заранее** — генерируется на лету функциями `api/rendering.py` в момент формирования HTTP-ответа на конкретный запрос. Черновой пример ниже был единой функцией `render_strike_event(event: dict)`; по факту `api/rendering.py` разбит на функцию на каждый тип события с явными параметрами (не один общий `dict`), плюс отдельная компактная форма для ударов внутри двойного удара — например:

```python
# api/rendering.py (сокращённо, реальные сигнатуры)

def render_strike(enemy_type, side_role, attack_roll, attack_percent, dodge_roll, dodged, damage) -> str:
    if attack_percent is None:
        return f"🗡️ {attack_label}: {attack_roll} → промах!"
    ...

def render_compact_strike(enemy_type, side_role, strike_number, attack_roll, attack_percent, dodge_roll, dodged, damage) -> str:
    ...  # однострочная форма — используется внутри двойного удара
```

**Что это даёт:** при появлении второго фронтенда (веб, мобильное приложение) или необходимости локализации — меняется/добавляется только `rendering.py` (или его аналог под нужды нового клиента), а `core/` и структура данных в БД не трогаются вообще.

```
core/combat_mechanics.py → считает структурированные факты боя
db (turn_log)             → хранит структурированные факты (источник истины)
api/rendering.py          → превращает факты в готовый текст ответа
api/routers/combat.py     → отдаёт HTTP-ответ с готовым текстом (вызывает rendering.py)
bot/                       → получает готовый текст, только показывает — ничего не решает
```

---

## 8. Порядок реализации по модулям

**Этап 1 — `core/` (готово)**
- Реализовать `core/combat_mechanics.py` с нуля по `combat_mechanics.md`.
- Добавить `progression.py`: формулы уровней (`threshold(N)`), регенерации HP (`get_current_hp`, `time_to_full_hp`), начисления наград.
- Юнит-тесты на граничные случаи каждой формулы (минимумы/максимумы граней, промах, крайние значения статов).

**Этап 2 — калибровка без БД и HTTP (готово)**
- `scripts/simulate_combat.py` — консольный прогон N боёв игрок vs мышь/волк/кабан на случайных или заданных статах.
- Подбор конкретных статов мобов и констант (`K`, пороги, награды) по статистике побед/поражений.
- Результат этапа — заполненный `content/enemies.json` с финальными (не черновыми) статами.

**Этап 3 — `db/` и `api/` (готово)**
- Модели, миграции через alembic (`alembic upgrade head` — см. §10, заведены 2026-09-16, до этого был `create_all()` при старте).
- Роутеры `character`, `encounter`, `combat` — тонкая оркестрация поверх уже проверенного `core/`.
- Проверено через Swagger/TestClient, без бота (`tests/api/`).

**Этап 4 — `bot/` (готово, код и юнит-тесты; сквозной прогон живьём в Telegram — ещё нет)**
- Хендлеры `/start`, создание персонажа, экран статов, поиск противника, ход боя.
- Только вызовы `api/` через `client.py` и рендер ответов — никакой логики.
- Потребовалось одно небольшое расширение API задним числом (единственный случай, когда предсказание из абзаца ниже не вполне сбылось): `CombatTurnResponse` не отдавал `current_turn`, а боту он нужен, чтобы подписать кнопку "Атаковать"/"Защищаться" без лишнего запроса — добавили поле в `api/schemas/combat.py` и `api/routers/combat.py`.

Логика этого порядка: к моменту, когда пишется HTTP-слой, все формулы уже проверены на реальных числах (этап 2), поэтому API-контракты не потребуют частых правок задним числом. Бот пишется последним и быстрее всего, потому что весь сложный слой к этому моменту уже готов и протестирован напрямую.

---

## 9. Авторизация бот ↔ API

Для MVP — простой статический API-ключ в заголовке (`X-Internal-Api-Key`), известный только боту. Полноценная схема авторизации избыточна, пока бэкенд не выставлен публично отдельно от бота.

Отдельно от ключа — заголовок `X-Telegram-User-Id`: им бот на каждом запросе сообщает, от чьего лица действует. `api/dependencies.get_current_character` ищет персонажа по этому id (а не по значению, присланному в теле запроса) — так клиент не может подменить чужого персонажа, просто указав другой id в JSON.

Значения (`INTERNAL_API_KEY`, `TELEGRAM_BOT_TOKEN`, `API_BASE_URL`) читаются из переменных окружения (см. `.env.example`) — `api/dependencies.py` на стороне сервера, `bot/client.py`/`bot/main.py` на стороне бота. `INTERNAL_API_KEY` должен совпадать в обеих конфигурациях (сервер проверяет ровно то значение, что шлёт бот).

---

## 10. Миграции БД (alembic)

Заведены 2026-09-16 — решили не откладывать: пока БД без ценных данных (плейтест), проще завести нормально, чем потом разбираться с ручными патчами схемы на "боевой" базе. `alembic` отдельно от `create_all()` не потому, что SQLite чего-то не умеет (простое добавление колонки она поддерживает нативно) — а потому что `Base.metadata.create_all()` в принципе создаёт только отсутствующие таблицы, не дотягивает изменения в уже существующих, независимо от СУБД. При переходе на Postgres (просто смена строки подключения, см. §1) миграции переигрываются на новую БД без изменений — poэтому `alembic` заведён один раз, а не отдельно под каждую целевую БД.

- `migrations/env.py` не хранит свою строку подключения — берёт `DATABASE_URL` из `db/session.py` и метаданные моделей из `db/models.py`, единственный источник и того и другого — сам код приложения, не `alembic.ini`.
- Новая миграция при изменении моделей: `alembic revision --autogenerate -m "описание"`, проверить сгенерированный файл в `migrations/versions/` (автоген не всегда точен — например, не всегда видит смену значения по умолчанию), применить `alembic upgrade head`.
- Приложение (`api/main.py`) больше не создаёт и не трогает схему при старте — это исключительно ответственность `alembic upgrade head`, выполняется отдельным шагом при деплое/локальном запуске (см. `docs/README.md`).
- Тестовая БД (`tests/api/conftest.py`) продолжает использовать `Base.metadata.create_all()` напрямую на одноразовой временной SQLite — это осознанно другой путь: тестам нужна чистая БД с нуля на каждый тест, а не история миграций.

---

## 11. Открытые вопросы, не закрытые этим документом

- Обработка одновременных/дублирующихся запросов на один и тот же ход (идемпотентность) — актуально уже в PvP, для PvE-MVP можно отложить.
