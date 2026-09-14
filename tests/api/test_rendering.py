"""Тесты api/rendering.py — факты боя -> текст."""

import pytest

from api import rendering as r


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
    # §8: грани 1-2 — debuff кидающему. Кидает противник -> его Сила падает
    # (что выгодно игроку), а не растёт — явно проверяем направление модификатора.
    text = r.render_circumstance("wolf", roll=2, outcome="debuff", roller_role="enemy")
    assert text == "🎲 Обстоятельство: 2 → ⚡ Скользкая земля\nСила волка уменьшена на этот бой (×0.8)"


def test_render_circumstance_uses_genitive_for_mouse():
    # "мыши" (родительный падеж), не "мышь" — регрессия на грамматику.
    text = r.render_circumstance("mouse", roll=1, outcome="debuff", roller_role="enemy")
    assert "Сила мыши" in text


@pytest.mark.parametrize(
    "side_role,triggered,expected",
    [
        ("player", False, "🎲 Проверка удачи: 3 → двойного удара нет."),
        ("player", True, "🎲 Проверка удачи: 9 → ✨ УДАЧА! Двойной удар!"),
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


def test_render_compact_strike_miss():
    text = r.render_compact_strike(
        "wolf", "player", 1, attack_roll=2, attack_percent=None, dodge_roll=None, dodged=None, damage=0
    )
    assert text == "🗡️ Удар 1: 2 → промах."


def test_render_flee_opportunity_triggered():
    text = r.render_flee_opportunity_check(current_hp=18, max_hp=85, luck_roll=7, triggered=True)
    assert text == "⚠️ Твоё HP критически низкое! (18/85)\n🍀 Проверка удачи на побег: 7 → есть шанс уйти живым!"


def test_render_flee_opportunity_not_triggered():
    text = r.render_flee_opportunity_check(current_hp=18, max_hp=85, luck_roll=2, triggered=False)
    assert text == "🍀 Проверка удачи на побег: 2 → шанса уйти нет в этот раз."


def test_render_flee_attempt_player_survives():
    text = r.render_flee_attempt("wolf", "player", attack_roll=6, attack_percent=60, damage=18, defeated=False)
    assert "вырываешься" in text


def test_render_flee_attempt_player_caught():
    text = r.render_flee_attempt("wolf", "player", attack_roll=10, attack_percent=100, damage=100, defeated=True)
    assert "настигает тебя" in text


def test_render_flee_attempt_player_misses_pursuer():
    text = r.render_flee_attempt("wolf", "player", attack_roll=1, attack_percent=None, damage=0, defeated=False)
    assert text == "🎲 Волк: 1 → промах! Тебе удаётся уйти чисто."


def test_render_flee_attempt_enemy_caught_and_killed():
    text = r.render_flee_attempt("wolf", "enemy", attack_roll=10, attack_percent=100, damage=100, defeated=True)
    assert "Добиваешь" in text


def test_render_battle_end_victory():
    text = r.render_battle_end(
        "wolf", "victory", reward=5, victory_points_total=23, hp_current=40, hp_max=60, hp_seconds_to_full=20
    )
    assert text == (
        "⚔️ Бой окончен! Ты победил Волка.\n"
        "🏆 +5 победных очков (всего: 23)\n"
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
