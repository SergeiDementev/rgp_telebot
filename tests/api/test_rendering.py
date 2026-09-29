"""Тесты api/rendering.py — факты боя -> текст.

Локаль по умолчанию (core/i18n.py::DEFAULT_LOCALE) — "ru", поэтому все
тесты ниже без явного переключения локали проверяют русский текст, как и
раньше (i18n/ru.py заполнен дословно тем же текстом, что был в коде до
блока 2 — эти тесты не менялись). Блок английского покрытия внизу файла
проверяет, что переключение локали действительно меняет вывод — по
одному репрезентативному тесту на каждую функцию render_*, не полное
дублирование русских тестов (грамматические тонкости вроде женского рода
"мыши" — специфика русского, в английском не воспроизводятся)."""

import pytest

from api import rendering as r
from core import i18n


def test_render_encounter():
    assert r.render_encounter("wolf", 4) == "🎲 Бросок: 4 → Волк!\n\nТы наткнулся на волка."


def test_render_initiative_player_first():
    text = r.render_initiative("wolf", player_roll=7, enemy_roll=4, first_role="player")
    assert text == "🎲 Инициатива: ты — 7, волк — 4. Ты ходишь первым!"


def test_render_initiative_enemy_first():
    text = r.render_initiative("wolf", player_roll=2, enemy_roll=9, first_role="enemy")
    assert text == "🎲 Инициатива: волк — 9, ты — 2. Волк атакует первым!"


def test_render_circumstance_none():
    assert r.render_circumstance("wolf", roll=5, outcome=None, roller_role="player") == (
        "🎲 Обстоятельство: 5 → без происшествий."
    )


def test_render_circumstance_buff_player():
    text = r.render_circumstance("wolf", roll=9, outcome="buff", roller_role="player")
    assert text == "🎲 Обстоятельство: 9 → ⚡ Прилив адреналина!\nТвоя Сила увеличена на этот бой (×1.2)"


def test_render_circumstance_debuff_enemy():
    # §8: грани 1-3 — debuff кидающему. Кидает противник -> его Сила падает
    # (что выгодно игроку), а не растёт — явно проверяем направление модификатора.
    text = r.render_circumstance("wolf", roll=2, outcome="debuff", roller_role="enemy")
    assert text == "🎲 Обстоятельство: 2 → ⚡ Скользкая земля\nСила волка уменьшена на этот бой (×0.8)"


def test_render_circumstance_uses_genitive_for_mouse():
    # "мыши" (родительный падеж), не "мышь" — регрессия на грамматику.
    text = r.render_circumstance("mouse", roll=1, outcome="debuff", roller_role="enemy")
    assert "Сила мыши" in text


def test_render_potion_used_small():
    assert r.render_potion_used("small", 12.0) == "🧪 Малое зелье: +12 HP."


def test_render_potion_used_large():
    assert r.render_potion_used("large", 25) == "🧪 Большое зелье: +25 HP."


def test_render_hp_status():
    # Урон и регенерация теперь всегда целые (core/combat_mechanics.py,
    # core/progression.py — docs/notes.md) — HP, доходящий до рендера, дробным
    # не бывает, отдельного округления в самом рендере больше не нужно.
    text = r.render_hp_status("wolf", player_hp=34.0, player_hp_max=50.0, enemy_hp=12.0, enemy_hp_max=50.0)
    assert text == "❤️ Ты: 34/50   👹 Волк: 12/50"


@pytest.mark.parametrize(
    "side_role,triggered,expected",
    [
        ("player", False, "🎲 Твоя проверка удачи: 3 → двойного удара нет."),
        ("player", True, "🎲 Твоя проверка удачи: 9 → ✨ УДАЧА! Двойной удар!"),
        ("enemy", False, "🎲 Волк проверяет удачу: 5 → двойного удара нет."),
    ],
)
def test_render_double_strike_check(side_role, triggered, expected):
    roll = 3 if not triggered and side_role == "player" else (9 if triggered else 5)
    assert r.render_double_strike_check("wolf", side_role, roll, triggered) == expected


def test_render_strike_miss():
    text = r.render_strike("wolf", "player", attack_roll=1, attack_percent=None, dodge_roll=None, dodged=None, damage=0)
    assert text == "🗡️ Твоя атака: 1 → промах!"


def test_render_strike_hit_player_attacking():
    text = r.render_strike(
        "wolf", "player", attack_roll=8, attack_percent=80, dodge_roll=4, dodged=False, damage=68
    )
    assert text == (
        "🗡️ Твоя атака: 8 → 80% силы.\n"
        "🛡️ Волк уворачивается: 4 → не вышло!\n"
        "💥 Ты наносишь 68 урона."
    )


def test_render_strike_dodged_enemy_attacking():
    text = r.render_strike(
        "wolf", "enemy", attack_roll=6, attack_percent=60, dodge_roll=8, dodged=True, damage=0
    )
    assert text == (
        "🗡️ Атака волка: 6 → 60% силы.\n"
        "🛡️ Твой уворот: 8 → увернулся!\n"
        "✅ Урон полностью пропущен."
    )


def test_render_compact_strike_hit():
    text = r.render_compact_strike(
        "wolf", "player", 1, attack_roll=9, attack_percent=90, dodge_roll=3, dodged=False, damage=72
    )
    assert text == "🗡️ Удар 1: 9 → 90% силы. 🛡️ Волк уворачивается: 3 → не вышло! 💥 72 урона."


def test_render_compact_strike_dodged():
    text = r.render_compact_strike(
        "wolf", "player", 2, attack_roll=5, attack_percent=50, dodge_roll=7, dodged=True, damage=0
    )
    assert text == "🗡️ Удар 2: 5 → 50% силы. 🛡️ Волк уворачивается: 7 → увернулся!"


def test_render_strike_dodged_uses_feminine_verb_for_mouse():
    # Мышь — женский род: "увернулась", не "увернулся" (docs/notes.md).
    text = r.render_strike(
        "mouse", "player", attack_roll=6, attack_percent=60, dodge_roll=8, dodged=True, damage=0
    )
    assert "Мышь уворачивается: 8 → увернулась!" in text


def test_render_compact_strike_miss():
    text = r.render_compact_strike(
        "wolf", "player", 1, attack_roll=2, attack_percent=None, dodge_roll=None, dodged=None, damage=0
    )
    assert text == "🗡️ Удар 1: 2 → промах."


def test_render_compact_strike_dodged_uses_feminine_verb_for_mouse():
    text = r.render_compact_strike(
        "mouse", "player", 1, attack_roll=9, attack_percent=90, dodge_roll=3, dodged=True, damage=0
    )
    assert "Мышь уворачивается: 3 → увернулась!" in text


def test_render_strike_power_attack_hit_uses_own_label_and_multiplier_note():
    # docs/combat_mechanics.md §3a — своя подпись/эмодзи и пометка "урон ×1.5!".
    text = r.render_strike(
        "wolf", "player", attack_roll=7, attack_percent=70, dodge_roll=5, dodged=False, damage=105,
        power_attack=True,
    )
    assert text == (
        "💥 Мощный удар: 7 → 70% силы, урон ×1.5!\n"
        "🛡️ Волк уворачивается: 5 → не вышло!\n"
        "💥 Ты наносишь 105 урона."
    )


def test_render_strike_power_attack_miss():
    text = r.render_strike(
        "wolf", "player", attack_roll=4, attack_percent=None, dodge_roll=None, dodged=None, damage=0,
        power_attack=True,
    )
    assert text == "💥 Мощный удар: 4 → промах!"


def test_render_strike_power_attack_only_affects_player_side():
    # Мобы мощным ударом не пользуются (docs/combat_mechanics.md §3a) —
    # флаг на стороне enemy не должен ничего менять в отображении.
    text = r.render_strike(
        "wolf", "enemy", attack_roll=6, attack_percent=60, dodge_roll=8, dodged=True, damage=0,
        power_attack=True,
    )
    assert text.startswith("🗡️ Атака волка: 6 → 60% силы.")


def test_render_compact_strike_power_attack_hit():
    text = r.render_compact_strike(
        "wolf", "player", 1, attack_roll=9, attack_percent=90, dodge_roll=3, dodged=False, damage=135,
        power_attack=True,
    )
    assert text == "💥 Мощный удар 1: 9 → 90% силы, урон ×1.5! 🛡️ Волк уворачивается: 3 → не вышло! 💥 135 урона."


def test_render_flee_opportunity_triggered_player():
    text = r.render_flee_opportunity_check("wolf", "player", current_hp=18, max_hp=85, luck_roll=7, triggered=True)
    assert text == "⚠️ Твоё HP критически низкое! (18/85)\n🍀 Твоя проверка удачи на побег: 7 → есть шанс уйти живым!"


def test_render_flee_opportunity_triggered_enemy():
    text = r.render_flee_opportunity_check("wolf", "enemy", current_hp=18, max_hp=85, luck_roll=7, triggered=True)
    assert text == "⚠️ HP волка критически низкое! (18/85)\n🍀 Волк проверяет удачу на побег: 7 → есть шанс уйти живым!"


def test_render_flee_opportunity_triggered_enemy_uses_feminine_adjective_for_mouse():
    # "уйти живой", не "уйти живым" — мышь женского рода (docs/notes.md).
    text = r.render_flee_opportunity_check("mouse", "enemy", current_hp=4, max_hp=20, luck_roll=7, triggered=True)
    assert "есть шанс уйти живой!" in text


def test_render_flee_opportunity_not_triggered_player():
    text = r.render_flee_opportunity_check("wolf", "player", current_hp=18, max_hp=85, luck_roll=2, triggered=False)
    assert text == "🍀 Твоя проверка удачи на побег: 2 → шанса уйти нет в этот раз."


def test_render_flee_opportunity_not_triggered_enemy():
    text = r.render_flee_opportunity_check("wolf", "enemy", current_hp=18, max_hp=85, luck_roll=2, triggered=False)
    assert text == "🍀 Волк проверяет удачу на побег: 2 → шанса уйти нет в этот раз."


def test_render_flee_attempt_player_survives():
    text = r.render_flee_attempt("wolf", "player", attack_roll=6, attack_percent=60, damage=18, defeated=False)
    assert "вырываешься" in text


def test_render_flee_attempt_player_caught():
    text = r.render_flee_attempt("wolf", "player", attack_roll=10, attack_percent=100, damage=100, defeated=True)
    assert "настигает тебя" in text


def test_render_flee_attempt_player_misses_pursuer():
    text = r.render_flee_attempt("wolf", "player", attack_roll=1, attack_percent=None, damage=0, defeated=False)
    assert text == (
        "🏃 Ты пытаешься сбежать — волк бьёт без ответа!\n"
        "🎲 Атака волка: 1 → промах!\n"
        "✅ Тебе удаётся уйти чисто."
    )


def test_render_flee_attempt_enemy_caught_and_killed():
    text = r.render_flee_attempt("wolf", "enemy", attack_roll=10, attack_percent=100, damage=100, defeated=True)
    assert "Добиваешь" in text


def test_render_battle_end_victory_without_loot_shows_no_luck_line():
    # Лут не гарантирован (core.economy.resolve_loot_drop может выкатить
    # "nothing") — явная строка вместо молчания (docs/notes.md).
    text = r.render_battle_end(
        "wolf", "victory", reward=5, victory_points_total=23, hp_current=40, hp_max=60, hp_seconds_to_full=20
    )
    assert text == (
        "⚔️ Бой окончен! Ты победил Волка.\n"
        "🏆 +5 победных очков (всего: 23)\n"
        "😕 Упс, не повезло с добычей...\n"
        "\n"
        "❤️ HP: 40/60\n"
        "⏳ Полное восстановление через: ~20 сек."
    )


def test_render_battle_end_victory_with_loot_shows_loot_line():
    text = r.render_battle_end(
        "wolf", "victory", reward=5, victory_points_total=23, hp_current=40, hp_max=60, hp_seconds_to_full=20,
        loot_dropped="wolf_fang",
    )
    assert text == (
        "⚔️ Бой окончен! Ты победил Волка.\n"
        "🏆 +5 победных очков (всего: 23)\n"
        "🎁 Добыча: Клык волка\n"
        "\n"
        "❤️ HP: 40/60\n"
        "⏳ Полное восстановление через: ~20 сек."
    )


def test_render_battle_end_defeat_no_reward_line():
    text = r.render_battle_end(
        "boar", "defeat", reward=0, victory_points_total=0, hp_current=0, hp_max=60, hp_seconds_to_full=60
    )
    assert "🏆" not in text
    assert text.startswith("💀 Ты пал в бою с Кабаном...")
    # "Не повезло с добычей" — только про исход "victory", на поражении лут
    # в принципе не кидался (см. api/routers/combat.py::_finish_battle).
    assert "не повезло" not in text


def test_render_battle_end_player_fled():
    text = r.render_battle_end(
        "wolf", "player_fled", reward=0, victory_points_total=0, hp_current=34, hp_max=60, hp_seconds_to_full=26
    )
    assert text.startswith("🏃 Тебе удалось уйти от боя с Волком.")


def test_render_battle_end_enemy_fled():
    text = r.render_battle_end(
        "wolf", "enemy_fled", reward=0, victory_points_total=0, hp_current=50, hp_max=60, hp_seconds_to_full=10
    )
    assert text.startswith("🏃 Волк сбежал")


def test_render_battle_end_enemy_fled_uses_feminine_verb_for_mouse():
    # "Мышь сбежала", не "Мышь сбежал" (docs/notes.md).
    text = r.render_battle_end(
        "mouse", "enemy_fled", reward=0, victory_points_total=0, hp_current=10, hp_max=20, hp_seconds_to_full=10
    )
    assert text.startswith("🏃 Мышь сбежала")


def test_render_battle_end_omits_regen_line_when_already_full():
    text = r.render_battle_end(
        "mouse", "victory", reward=1, victory_points_total=1, hp_current=20, hp_max=20, hp_seconds_to_full=0
    )
    assert "Полное восстановление" not in text


def test_render_battle_end_rejects_unknown_result():
    with pytest.raises(ValueError):
        r.render_battle_end(
            "wolf", "draw", reward=0, victory_points_total=0, hp_current=1, hp_max=1, hp_seconds_to_full=0
        )


def test_render_battle_end_boss_defeat_uses_boss_declension():
    # Победа над боссом рендерится отдельно (render_boss_victory), но
    # поражение/побег всё ещё идут через обычный render_battle_end и должны
    # использовать полную грамматическую запись "boss" из ENEMY_NAMES.
    text = r.render_battle_end(
        "boss", "defeat", reward=0, victory_points_total=0, hp_current=0, hp_max=60, hp_seconds_to_full=60
    )
    assert text.startswith("💀 Ты пал в бою с Лесным Королём...")


def test_render_boss_encounter_mentions_boss():
    text = r.render_boss_encounter()
    assert "Лесно" in text  # "Лесного Короля"/"Лесной Король" в зависимости от формулировки
    assert text


def test_render_boss_victory_has_no_reward_or_hp_line():
    # п.54 — победа над боссом не даёт награды, экран — просто поздравление.
    text = r.render_boss_victory()
    assert "Лесного Короля" in text
    assert "🏆" not in text
    assert "❤️ HP" not in text
    assert "⏳" not in text


def test_render_fight_confirmed():
    # docs/notes.md, блок 6 — раньше сырой литерал в api/routers/combat.py,
    # в обход этого модуля/core.i18n целиком.
    assert r.render_fight_confirmed() == "⚔️ Ты вступаешь в бой!"


# --- Английская локаль (docs/notes.md, блок 2) --------------------------
# По одному тесту на каждую render_*-функцию — доказывает, что
# i18n.set_locale("en") действительно меняет вывод, не полное дублирование
# русских тестов выше (см. докстринг модуля).


@pytest.fixture
def en_locale():
    token = i18n.set_locale("en")
    try:
        yield
    finally:
        i18n.reset_locale(token)


def test_render_encounter_en(en_locale):
    assert r.render_encounter("wolf", 4) == "🎲 Roll: 4 → Wolf!\n\nYou encounter wolf."


def test_render_boss_encounter_en(en_locale):
    text = r.render_boss_encounter()
    assert text == "👑 You enter Forest King's lair. There's nowhere to run — it already has its eyes on you."


def test_render_initiative_en(en_locale):
    text = r.render_initiative("wolf", player_roll=7, enemy_roll=4, first_role="player")
    assert text == "🎲 Initiative: you — 7, wolf — 4. You go first!"


def test_render_circumstance_buff_player_en(en_locale):
    text = r.render_circumstance("wolf", roll=9, outcome="buff", roller_role="player")
    assert text == "🎲 Event: 9 → ⚡ Adrenaline Rush!\nYour Strength is increased for this battle (×1.2)"


def test_render_double_strike_check_triggered_en(en_locale):
    text = r.render_double_strike_check("wolf", "player", 9, True)
    assert text == "🎲 Your Luck roll: 9 → ✨ LUCKY! Double strike!"


def test_render_strike_hit_player_attacking_en(en_locale):
    text = r.render_strike("wolf", "player", attack_roll=8, attack_percent=80, dodge_roll=4, dodged=False, damage=68)
    assert text == (
        "🗡️ Your attack: 8 → 80% power.\n"
        "🛡️ Wolf dodges: 4 → Failed!\n"
        "💥 You deal 68 damage."
    )


def test_render_strike_miss_en(en_locale):
    text = r.render_strike("wolf", "player", attack_roll=1, attack_percent=None, dodge_roll=None, dodged=None, damage=0)
    assert text == "🗡️ Your attack: 1 → Miss!"


def test_render_compact_strike_hit_en(en_locale):
    text = r.render_compact_strike(
        "wolf", "player", 1, attack_roll=9, attack_percent=90, dodge_roll=3, dodged=False, damage=72
    )
    assert text == "🗡️ Strike 1: 9 → 90% power. 🛡️ Wolf dodges: 3 → Failed! 💥 72 damage."


def test_render_potion_used_en(en_locale):
    assert r.render_potion_used("large", 25) == "🧪 Large Potion: +25 HP."


def test_render_hp_status_en(en_locale):
    text = r.render_hp_status("wolf", player_hp=34.0, player_hp_max=50.0, enemy_hp=12.0, enemy_hp_max=50.0)
    assert text == "❤️ You: 34/50   👹 Wolf: 12/50"


def test_render_flee_opportunity_triggered_player_en(en_locale):
    text = r.render_flee_opportunity_check("wolf", "player", current_hp=18, max_hp=85, luck_roll=7, triggered=True)
    assert text == (
        "⚠️ Your HP is critically low! (18/85)\n"
        "🍀 Your escape chance roll: 7 → a chance to escape while alive!"
    )


def test_render_flee_attempt_player_misses_pursuer_en(en_locale):
    text = r.render_flee_attempt("wolf", "player", attack_roll=1, attack_percent=None, damage=0, defeated=False)
    assert text == (
        "🏃 You try to flee — wolf gets a free hit!\n"
        "🎲 wolf's attack: 1 → Miss!\n"
        "✅ You make a clean escape."
    )


def test_render_battle_end_victory_with_loot_en(en_locale):
    text = r.render_battle_end(
        "wolf", "victory", reward=5, victory_points_total=23, hp_current=40, hp_max=60, hp_seconds_to_full=20,
        loot_dropped="wolf_fang",
    )
    assert text == (
        "⚔️ Battle over! You defeated Wolf.\n"
        "🏆 +5 Victory Points (total: 23)\n"
        "🎁 Loot: Wolf Fang\n"
        "\n"
        "❤️ HP: 40/60\n"
        "⏳ Fully restored in: ~20 sec."
    )


def test_render_battle_end_defeat_en(en_locale):
    text = r.render_battle_end(
        "boar", "defeat", reward=0, victory_points_total=0, hp_current=0, hp_max=60, hp_seconds_to_full=60
    )
    assert text.startswith("💀 You were defeated by Boar...")
    assert "🏆" not in text


def test_render_boss_victory_en(en_locale):
    text = r.render_boss_victory()
    assert text == "🎉 You have defeated Forest King!\n\nYour adventure is complete. Thanks for playing!"


def test_render_fight_confirmed_en(en_locale):
    assert r.render_fight_confirmed() == "⚔️ You engage in combat!"


# --- Регрессия: KeyError на en-локали в редко покрытых ветках --------
# Обнаружено в проде (docs/notes.md) — render_strike(side_role="enemy") на
# "en" падал с KeyError: 'name_nom_cap', потому что api/rendering.py
# передавал в i18n.t() только name_gen_low (форму, нужную i18n/ru.py), а
# i18n/en.py для того же ключа использует {name_nom_cap} — разные локали
# законно используют разные грамматические формы одного и того же имени
# противника (i18n/ru.py — падежи, i18n/en.py — нет склонения), но
# существовавшие EN-тесты выше проверяли только side_role="player" для
# каждой функции, не side_role="enemy" — ровно та ветка, что и упала.
# Тест ниже — не по одному репрезентативному случаю на функцию, а прогон
# ВСЕХ веток (оба enemy_type-зависимых side_role, оба roller_role
# обстоятельства, все исходы) на обеих локалях: ловит именно класс
# ошибки "шаблон одной локали требует форму, которую вызывающий код не
# передал", а не полагается на то, что кто-то не забудет добавить
# конкретный тест на конкретную новую ветку в будущем.
def test_all_render_functions_succeed_across_every_branch_and_locale():
    for locale in ("ru", "en"):
        token = i18n.set_locale(locale)
        try:
            for enemy_type in ("mouse", "wolf", "boar", "boss"):
                assert r.render_encounter(enemy_type, 5)
                for first_role in ("player", "enemy"):
                    assert r.render_initiative(enemy_type, 5, 3, first_role)
                for roller_role in ("player", "enemy"):
                    assert r.render_circumstance(enemy_type, 5, None, roller_role)
                    assert r.render_circumstance(enemy_type, 5, "buff", roller_role)
                    assert r.render_circumstance(enemy_type, 5, "debuff", roller_role)
                for side_role in ("player", "enemy"):
                    assert r.render_double_strike_check(enemy_type, side_role, 5, True)
                    assert r.render_double_strike_check(enemy_type, side_role, 5, False)
                    assert r.render_strike(enemy_type, side_role, 5, None, None, None, 0)
                    assert r.render_strike(enemy_type, side_role, 5, 50, 5, True, 0)
                    assert r.render_strike(enemy_type, side_role, 5, 50, 5, False, 10)
                    assert r.render_strike(enemy_type, side_role, 5, 50, 5, False, 10, power_attack=True)
                    assert r.render_compact_strike(enemy_type, side_role, 1, 5, None, None, None, 0)
                    assert r.render_compact_strike(enemy_type, side_role, 1, 5, 50, 5, True, 0)
                    assert r.render_compact_strike(enemy_type, side_role, 1, 5, 50, 5, False, 10)
                    assert r.render_flee_opportunity_check(enemy_type, side_role, 10, 40, 5, True)
                    assert r.render_flee_opportunity_check(enemy_type, side_role, 10, 40, 5, False)
                    assert r.render_flee_attempt(enemy_type, side_role, 5, None, 0, False)
                    assert r.render_flee_attempt(enemy_type, side_role, 5, 50, 10, True)
                    assert r.render_flee_attempt(enemy_type, side_role, 5, 50, 10, False)
                for result in ("victory", "defeat", "player_fled", "enemy_fled"):
                    assert r.render_battle_end(
                        enemy_type, result, reward=5, victory_points_total=10,
                        hp_current=40, hp_max=60, hp_seconds_to_full=20,
                    )
                assert r.render_battle_end(
                    enemy_type, "victory", reward=5, victory_points_total=10,
                    hp_current=40, hp_max=60, hp_seconds_to_full=20, loot_dropped="wolf_fang",
                )
            assert r.render_boss_encounter()
            assert r.render_boss_victory()
            assert r.render_fight_confirmed()
            assert r.render_hp_status("wolf", 30, 50, 10, 50)
            assert r.render_potion_used("small", 10)
            assert r.render_potion_used("large", 20)
        finally:
            i18n.reset_locale(token)
