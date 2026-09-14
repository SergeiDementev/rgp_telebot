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
- **Единая механика PvE/PvP.** `core/combat.py` не различает, кто управляет стороной — разница только в том, кто инициирует запрос на ход.

---

## 3. Структура проекта

```
project/
├── core/                    # чистая игровая логика, без внешних зависимостей
│   ├── combat.py            # готово — combat_core.py, см. combat_mechanics.md
│   ├── progression.py       # формулы уровней, регенерации HP, наград
│   └── circumstance.py      # (может быть частью combat.py — на усмотрение реализации)
│
├── api/                     # FastAPI-приложение
│   ├── main.py
│   ├── routers/
│   │   ├── character.py     # создание/просмотр персонажа, прокачка
│   │   ├── encounter.py     # поиск противника
│   │   └── combat.py        # ход боя, подтверждение, побег
│   ├── schemas/              # Pydantic-модели запросов/ответов
│   ├── rendering.py           # структурированные факты боя → готовый текст для клиента
│   └── dependencies.py       # получение текущего персонажа, авторизация бота
│
├── db/
│   ├── models.py             # SQLAlchemy-модели
│   ├── session.py            # подключение, фабрика сессий
│   └── migrations/           # alembic (по мере надобности)
│
├── content/                  # статичные игровые данные
│   └── enemies.json          # статы мышь/волк/кабан
│
├── scripts/
│   └── simulate_combat.py    # консольный симулятор боёв для калибровки (см. §8, этап 2)
│
└── bot/                       # Telegram-клиент (aiogram)
    ├── handlers/
    │   ├── start.py
    │   ├── character.py
    │   └── combat.py
    └── client.py              # обёртка над httpx для вызовов api/
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
POST /character                      — создать персонажа (nickname из Telegram, стартовые статы)
GET  /character/{telegram_user_id}   — текущее состояние (HP пересчитывается на лету при чтении)
POST /character/{id}/allocate_point  — потратить одно очко прокачки: {"stat": "strength"}

POST /encounter/search               — бросок d10 (60/30/10), создание CombatSession
                                        (status="awaiting_initiative")
POST /combat/{id}/start              — бросок инициативы + обстоятельства одним вызовом
                                        (status -> "awaiting_confirmation")

POST /combat/{id}/confirm            — { "decision": "fight" | "flee" } — после обстоятельства
POST /combat/{id}/turn               — выполнить один ход игрока (+ автоматически ход бота,
                                        если следующая очередь его)
POST /combat/{id}/flee_decision      — { "decision": "flee" | "continue" } — по HP-порогу
GET  /combat/{id}                    — текущее состояние сессии (восстановление после сбоя бота)
```

`/encounter/search` и `/combat/{id}/start` — два отдельных запроса, а не один: в `gameplay_loop_mvp.md` §9 это два отдельных нажатия кнопки ("Искать противника", затем отдельно "Определить инициативу"), а принцип "один HTTP-запрос = один шаг" (§1) требует по запросу на каждое нажатие.

Ни один эндпоинт не принимает от клиента сырых результатов бросков или урона — только идентификаторы и явные решения игрока (fight/flee/continue, какой стат прокачать).

---

## 6. Пример потока одного обработчика (оркестрация, без игровой логики внутри)

```python
@router.post("/combat/{session_id}/turn")
async def make_turn(session_id: int, db: Session):
    session = get_combat_session(db, session_id)
    attacker, defender = get_turn_sides(session)

    luck_roll = roll_d(10)
    attack_rolls = [roll_d(10), roll_d(10)]
    dodge_rolls = [roll_d(10), roll_d(10)]

    turn_results = resolve_turn(
        attacker_strength=attacker.strength,
        defender_agility=defender.agility,
        luck_roll=luck_roll,
        attack_rolls=attack_rolls,
        dodge_rolls=dodge_rolls,
        attacker_luck=attacker.luck,
    )

    apply_results_to_session(session, turn_results)

    if session.status == "finished":
        apply_rewards(db, session)
    elif is_bot_turn(session):
        bot_results = resolve_turn(...)   # тот же вызов ядра, для стороны бота
        apply_results_to_session(session, bot_results)

    db.commit()
    return build_turn_response(session, turn_results)
```

Правило: обработчик = прочитать состояние → вызвать функцию `core/` → сохранить → вернуть JSON. Никакой логики броска/урона/условий внутри роутера.

---

## 7. Рендеринг событий боя (turn_log и текст)

**Принцип:** вся логика боя и весь текст, который её описывает, — на бэкенде. Бот (и любой другой будущий фронтенд) не формирует и не интерпретирует события боя — он получает от API уже готовый текст и просто показывает его. Это разделено на два слоя внутри бэкенда, чтобы не терять переносимость на другой фронтенд/язык/формат позже:

1. **`core/combat.py`** — считает структурированные факты (какие грани выпали, какой урон, сработал ли уворот). Не знает о тексте вообще.
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

Готовый текст **не хранится заранее** — генерируется на лету функциями `api/rendering.py` в момент формирования HTTP-ответа на конкретный запрос:

```python
# api/rendering.py

def render_strike_event(event: dict) -> str:
    if event["result"] == "miss":
        return "🎲 Ты промахнулся!"
    if event["dodged"]:
        return f"🎲 Бросок атаки: {event['attack_roll']} → {event['attack_percent']}%. Противник уворачивается!"
    return f"🎲 Бросок атаки: {event['attack_roll']} → {event['attack_percent']}%. 💥 Ты наносишь {event['damage']} урона."
```

**Что это даёт:** при появлении второго фронтенда (веб, мобильное приложение) или необходимости локализации — меняется/добавляется только `rendering.py` (или его аналог под нужды нового клиента), а `core/` и структура данных в БД не трогаются вообще.

```
core/combat.py       → считает структурированные факты боя
db (turn_log)         → хранит структурированные факты (источник истины)
api/rendering.py      → превращает факты в готовый текст ответа
api/routers/combat.py → отдаёт HTTP-ответ с готовым текстом (вызывает rendering.py)
bot/                   → получает готовый текст, только показывает — ничего не решает
```

---

## 8. Порядок реализации по модулям

**Этап 1 — `core/`**
- Перенести/уточнить `combat_core.py`.
- Добавить `progression.py`: формулы уровней (`threshold(N)`), регенерации HP (`get_current_hp`, `time_to_full_hp`), начисления наград.
- Юнит-тесты на граничные случаи каждой формулы (минимумы/максимумы граней, промах, крайние значения статов).

**Этап 2 — калибровка без БД и HTTP**
- `scripts/simulate_combat.py` — консольный прогон N боёв игрок vs мышь/волк/кабан на случайных или заданных статах.
- Подбор конкретных статов мобов и констант (`K`, пороги, награды) по статистике побед/поражений.
- Результат этапа — заполненный `content/enemies.json` с финальными (не черновыми) статами.

**Этап 3 — `db/` и `api/`**
- Модели и миграции.
- Роутеры `character`, `encounter`, `combat` — тонкая оркестрация поверх уже проверенного `core/`.
- Проверка через Swagger/curl, без бота.

**Этап 4 — `bot/`**
- Хендлеры `/start`, создание персонажа, экран статов, поиск противника, ход боя.
- Только вызовы `api/` через `client.py` и рендер ответов — никакой логики.

Логика этого порядка: к моменту, когда пишется HTTP-слой, все формулы уже проверены на реальных числах (этап 2), поэтому API-контракты не потребуют частых правок задним числом. Бот пишется последним и быстрее всего, потому что весь сложный слой к этому моменту уже готов и протестирован напрямую.

---

## 9. Авторизация бот ↔ API

Для MVP — простой статический API-ключ в заголовке (`X-Internal-Api-Key`), известный только боту. Полноценная схема авторизации избыточна, пока бэкенд не выставлен публично отдельно от бота.

---

## 10. Открытые вопросы, не закрытые этим документом

- Обработка одновременных/дублирующихся запросов на один и тот же ход (идемпотентность) — актуально уже в PvP, для PvE-MVP можно отложить.
- Миграции БД (alembic) — не настроены, добавить при первом реальном изменении схемы после начального деплоя.
