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
buff, хотя по таблице §8 грани 1-3 — debuff) — здесь выбрана одна
последовательная формулировка на каждый случай, не обе сразу.
"""

ENEMY_NAMES = {
    "mouse": {
        "nom_cap": "Мышь", "nom_low": "мышь",
        "acc_cap": "Мышь", "acc_low": "мышь",
        "gen_low": "мыши",
        "ins_cap": "Мышью",
        # Мышь — существительное женского рода: формы глаголов/прилагательных,
        # относящихся к противнику, должны с ним согласовываться (docs/notes.md).
        "dodge_verb": "увернулась",
        "alive_adj": "живой",
        "fled_verb": "сбежала",
    },
    "wolf": {
        "nom_cap": "Волк", "nom_low": "волк",
        "acc_cap": "Волка", "acc_low": "волка",
        "gen_low": "волка",
        "ins_cap": "Волком",
        "dodge_verb": "увернулся",
        "alive_adj": "живым",
        "fled_verb": "сбежал",
    },
    "boar": {
        "nom_cap": "Кабан", "nom_low": "кабан",
        "acc_cap": "Кабана", "acc_low": "кабана",
        "gen_low": "кабана",
        "ins_cap": "Кабаном",
        "dodge_verb": "увернулся",
        "alive_adj": "живым",
        "fled_verb": "сбежал",
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
    prefix = "Твоя проверка удачи" if side_role == "player" else f"{ENEMY_NAMES[enemy_type]['nom_cap']} проверяет удачу"
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
        dodge_verb = names["dodge_verb"]
    else:
        attack_label, dodge_label, damage_verb = f"Атака {names['gen_low']}", "Твой уворот", f"{names['nom_cap']} наносит"
        dodge_verb = "увернулся"

    if attack_percent is None:
        return f"🗡️ {attack_label}: {attack_roll} → промах!"

    lines = [f"🗡️ {attack_label}: {attack_roll} → {attack_percent}% силы."]
    if dodged:
        lines.append(f"🛡️ {dodge_label}: {dodge_roll} → {dodge_verb}!")
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
    names = ENEMY_NAMES[enemy_type]
    if side_role == "player":
        dodge_label, dodge_verb = f"{names['nom_cap']} уворачивается", names["dodge_verb"]
    else:
        dodge_label, dodge_verb = "Ты уворачиваешься", "увернулся"

    if attack_percent is None:
        return f"🗡️ Удар {strike_number}: {attack_roll} → промах."

    parts = [f"🗡️ Удар {strike_number}: {attack_roll} → {attack_percent}% силы."]
    if dodged:
        parts.append(f"🛡️ {dodge_label}: {dodge_roll} → {dodge_verb}!")
    else:
        parts.append(f"🛡️ {dodge_label}: {dodge_roll} → не вышло!")
        parts.append(f"💥 {damage:.0f} урона.")
    return " ".join(parts)


def render_hp_status(
    enemy_type: str,
    player_hp: float,
    player_hp_max: float,
    enemy_hp: float,
    enemy_hp_max: float,
) -> str:
    """Шапка статуса HP — печатается первой строкой в каждом сообщении боя."""
    names = ENEMY_NAMES[enemy_type]
    return f"❤️ Ты: {player_hp:.0f}/{player_hp_max:.0f}   👹 {names['nom_cap']}: {enemy_hp:.0f}/{enemy_hp_max:.0f}"


def render_flee_opportunity_check(
    enemy_type: str, side_role: str, current_hp: float, max_hp: float, luck_roll: int, triggered: bool
) -> str:
    """Чья это проверка, должно быть видно сразу — иначе не отличить свою
    проверку на побег от проверки моба (см. docs/notes.md, п.6)."""
    if side_role == "player":
        hp_label, prefix, alive_adj = "Твоё HP критически низкое", "Твоя проверка удачи на побег", "живым"
    else:
        names = ENEMY_NAMES[enemy_type]
        hp_label = f"HP {names['gen_low']} критически низкое"
        prefix = f"{names['nom_cap']} проверяет удачу на побег"
        alive_adj = names["alive_adj"]

    if triggered:
        return f"⚠️ {hp_label}! ({current_hp:.0f}/{max_hp:.0f})\n🍀 {prefix}: {luck_roll} → есть шанс уйти {alive_adj}!"
    return f"🍀 {prefix}: {luck_roll} → шанса уйти нет в этот раз."


def render_flee_attempt(
    enemy_type: str,
    fleeing_role: str,
    attack_roll: int,
    attack_percent,
    damage: float,
    defeated: bool,
) -> str:
    """§7: безответный удар преследователя — без фазы уворота у убегающего.
    Многострочный формат (как у render_strike), а не одна строка: сообщение
    сразу следом идёт заголовок итога боя (render_battle_end), и в одну
    строку бросок на его фоне терялся (см. docs/notes.md, п.7)."""
    names = ENEMY_NAMES[enemy_type]
    if fleeing_role == "player":
        header = f"🏃 Ты пытаешься сбежать — {names['nom_low']} бьёт без ответа!"
        attack_label = f"Атака {names['gen_low']}"
        if attack_percent is None:
            return f"{header}\n🎲 {attack_label}: {attack_roll} → промах!\n✅ Тебе удаётся уйти чисто."
        if defeated:
            return (
                f"{header}\n🎲 {attack_label}: {attack_roll} → {attack_percent}% силы."
                f"\n💀 Удар настигает тебя ({damage:.0f} урона)."
            )
        return (
            f"{header}\n🎲 {attack_label}: {attack_roll} → {attack_percent}% силы."
            f"\n💥 {damage:.0f} урона вдогонку, но ты вырываешься."
        )

    header = f"🏃 {names['nom_cap']} пытается сбежать — твой удар без ответа!"
    if attack_percent is None:
        return f"{header}\n🎲 Твоя атака: {attack_roll} → промах!\n{names['nom_cap']} убегает."
    if defeated:
        return (
            f"{header}\n🎲 Твоя атака: {attack_roll} → {attack_percent}% силы."
            f"\n💀 Добиваешь {names['acc_low']} на бегу ({damage:.0f} урона)."
        )
    return (
        f"{header}\n🎲 Твоя атака: {attack_roll} → {attack_percent}% силы."
        f"\n💥 {damage:.0f} урона, но {names['nom_low']} вырывается."
    )


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
        header = f"🏃 {names['nom_cap']} {names['fled_verb']}, добить не удалось."
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
