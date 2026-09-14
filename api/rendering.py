"""Структурированные факты боя -> готовый текст ответа (backend_plan.md §7).

core/combat_mechanics.py считает факты и не знает о тексте вообще. Это —
единственное место, где решается, как бой выглядит для игрока; при
появлении второго фронтенда/локализации меняется только этот файл.

Форматирование бросков — по правилу gameplay_loop_mvp.md §9: любой бросок
кубика показывает выпавшее число, а не только словесный итог
(`<число> → <результат>`).

Пара мест, где мокапы в gameplay_loop_mvp.md §9 сами между собой
расходятся в мелких деталях (например, провал уворота подписан то
"не вышло!", то "не смог!"; пример обстоятельства на грани 2 подписан как
buff, хотя по таблице §8 грани 1-2 — debuff) — здесь выбрана одна
последовательная формулировка на каждый случай, не обе сразу.
"""

ENEMY_NAMES = {
    "mouse": {
        "nom_cap": "Мышь", "nom_low": "мышь",
        "acc_cap": "Мышь", "acc_low": "мышь",
        "gen_low": "мыши",
        "ins_cap": "Мышью",
    },
    "wolf": {
        "nom_cap": "Волк", "nom_low": "волк",
        "acc_cap": "Волка", "acc_low": "волка",
        "gen_low": "волка",
        "ins_cap": "Волком",
    },
    "boar": {
        "nom_cap": "Кабан", "nom_low": "кабан",
        "acc_cap": "Кабана", "acc_low": "кабана",
        "gen_low": "кабана",
        "ins_cap": "Кабаном",
    },
}


def render_encounter(enemy_type: str, roll: int) -> str:
    names = ENEMY_NAMES[enemy_type]
    return f"🎲 Бросок: {roll} → {names['nom_cap']}!\n\nТы наткнулся на {names['acc_low']}."


def render_initiative(enemy_type: str, player_roll: int, enemy_roll: int, first_role: str) -> str:
    names = ENEMY_NAMES[enemy_type]
    if first_role == "player":
        return f"🎲 Инициатива: ты — {player_roll}, {names['nom_low']} — {enemy_roll}. Ты ходишь первым!"
    return f"🎲 Инициатива: {names['nom_low']} — {enemy_roll}, ты — {player_roll}. {names['nom_cap']} атакует первым!"


def render_circumstance(enemy_type: str, roll: int, outcome, roller_role: str) -> str:
    if outcome is None:
        return f"🎲 Обстоятельство: {roll} → без происшествий."

    names = ENEMY_NAMES[enemy_type]
    if outcome == "buff":
        flavor, direction, multiplier = "⚡ Прилив адреналина!", "увеличена", "×1.2"
    else:
        flavor, direction, multiplier = "⚡ Скользкая земля", "уменьшена", "×0.8"

    subject = "Твоя Сила" if roller_role == "player" else f"Сила {names['gen_low']}"
    return f"🎲 Обстоятельство: {roll} → {flavor}\n{subject} {direction} на этот бой ({multiplier})"


def render_double_strike_check(enemy_type: str, side_role: str, luck_roll: int, triggered: bool) -> str:
    prefix = "Проверка удачи" if side_role == "player" else f"{ENEMY_NAMES[enemy_type]['nom_cap']} проверяет удачу"
    if triggered:
        return f"🎲 {prefix}: {luck_roll} → ✨ УДАЧА! Двойной удар!"
    return f"🎲 {prefix}: {luck_roll} → двойного удара нет."


def render_strike(
    enemy_type: str,
    side_role: str,
    attack_roll: int,
    attack_percent,
    dodge_roll,
    dodged,
    damage: float,
) -> str:
    """Полная (многострочная) форма одного удара — вне двойного удара."""
    names = ENEMY_NAMES[enemy_type]
    if side_role == "player":
        attack_label, dodge_label, damage_verb = "Твоя атака", f"{names['nom_cap']} уворачивается", "Ты наносишь"
    else:
        attack_label, dodge_label, damage_verb = f"Атака {names['gen_low']}", "Твой уворот", f"{names['nom_cap']} наносит"

    if attack_percent is None:
        return f"🗡️ {attack_label}: {attack_roll} → промах!"

    lines = [f"🗡️ {attack_label}: {attack_roll} → {attack_percent}% силы."]
    if dodged:
        lines.append(f"🛡️ {dodge_label}: {dodge_roll} → увернулся!")
        lines.append("✅ Урон полностью пропущен.")
    else:
        lines.append(f"🛡️ {dodge_label}: {dodge_roll} → не вышло!")
        lines.append(f"💥 {damage_verb} {damage:.0f} урона.")
    return "\n".join(lines)


def render_compact_strike(
    enemy_type: str,
    side_role: str,
    strike_number: int,
    attack_roll: int,
    attack_percent,
    dodge_roll,
    dodged,
    damage: float,
) -> str:
    """Компактная (однострочная) форма удара — используется внутри двойного удара."""
    dodge_label = f"{ENEMY_NAMES[enemy_type]['nom_cap']} уворачивается" if side_role == "player" else "Ты уворачиваешься"

    if attack_percent is None:
        return f"🗡️ Удар {strike_number}: {attack_roll} → промах."

    parts = [f"🗡️ Удар {strike_number}: {attack_roll} → {attack_percent}% силы."]
    if dodged:
        parts.append(f"🛡️ {dodge_label}: {dodge_roll} → увернулся!")
    else:
        parts.append(f"🛡️ {dodge_label}: {dodge_roll} → не вышло!")
        parts.append(f"💥 {damage:.0f} урона.")
    return " ".join(parts)


def render_flee_opportunity_check(current_hp: float, max_hp: float, luck_roll: int, triggered: bool) -> str:
    if triggered:
        return (
            f"⚠️ Твоё HP критически низкое! ({current_hp:.0f}/{max_hp:.0f})\n"
            f"🍀 Проверка удачи на побег: {luck_roll} → есть шанс уйти живым!"
        )
    return f"🍀 Проверка удачи на побег: {luck_roll} → шанса уйти нет в этот раз."


def render_flee_attempt(
    enemy_type: str,
    fleeing_role: str,
    attack_roll: int,
    attack_percent,
    damage: float,
    defeated: bool,
) -> str:
    """§7: безответный удар преследователя. Точного мокапа в доке нет —
    формулировка подобрана в стиле остальных сообщений."""
    names = ENEMY_NAMES[enemy_type]
    if fleeing_role == "player":
        if attack_percent is None:
            return f"🎲 {names['nom_cap']}: {attack_roll} → промах! Тебе удаётся уйти чисто."
        if defeated:
            return f"🎲 {names['nom_cap']}: {attack_roll} → {attack_percent}% силы. 💥 Удар настигает тебя ({damage:.0f} урона)."
        return f"🎲 {names['nom_cap']}: {attack_roll} → {attack_percent}% силы. 💥 {damage:.0f} урона вдогонку, но ты вырываешься."

    if attack_percent is None:
        return f"🎲 Твой удар: {attack_roll} → промах! {names['nom_cap']} убегает."
    if defeated:
        return f"🎲 Твой удар: {attack_roll} → {attack_percent}% силы. 💥 Добиваешь {names['acc_low']} на бегу ({damage:.0f} урона)."
    return f"🎲 Твой удар: {attack_roll} → {attack_percent}% силы. 💥 {damage:.0f} урона, но {names['nom_low']} вырывается."


def render_battle_end(
    enemy_type: str,
    result: str,
    reward: int,
    victory_points_total: int,
    hp_current: float,
    hp_max: float,
    hp_seconds_to_full: float,
) -> str:
    names = ENEMY_NAMES[enemy_type]
    if result == "victory":
        header = f"⚔️ Бой окончен! Ты победил {names['acc_cap']}."
        reward_line = f"🏆 +{reward} победных очков (всего: {victory_points_total})"
    elif result == "defeat":
        header = f"💀 Ты пал в бою с {names['ins_cap']}..."
        reward_line = None
    elif result == "player_fled":
        header = f"🏃 Тебе удалось уйти от боя с {names['ins_cap']}."
        reward_line = None
    elif result == "enemy_fled":
        header = f"🏃 {names['nom_cap']} сбежал, добить не удалось."
        reward_line = None
    else:
        raise ValueError(f"unknown battle result: {result!r}")

    lines = [header]
    if reward_line:
        lines.append(reward_line)
    lines.append("")
    lines.append(f"❤️ HP: {hp_current:.0f}/{hp_max:.0f}")
    if hp_seconds_to_full > 0:
        lines.append(f"⏳ Полное восстановление через: ~{hp_seconds_to_full:.0f} сек.")
    return "\n".join(lines)
