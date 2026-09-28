"""Структурированные факты боя -> готовый текст ответа (backend_plan.md §7).

core/combat_mechanics.py считает факты и не знает о тексте вообще. Это —
единственное место, где решается, как бой выглядит для игрока; при
появлении второго фронтенда меняется только этот файл.

Форматирование бросков — по правилу gameplay_loop_mvp.md §9: любой бросок
кубика показывает выпавшее число, а не только словесный итог
(`<число> → <результат>`).

Пара мест, где мокапы в gameplay_loop_mvp.md §9 сами между собой
расходятся в мелких деталях (например, провал уворота подписан то
"не вышло!", то "не смог!"; пример обстоятельства на грани 2 подписан как
buff, хотя по таблице §8 грани 1-3 — debuff) — здесь выбрана одна
последовательная формулировка на каждый случай, не обе сразу.

Двуязычность (docs/notes.md, блок 2) — сами строки живут в i18n/ru.py и
i18n/en.py (core.i18n.t()), этот модуль решает только КАКОЙ ключ и с
какими грамматическими формами противника вызвать в каждой ветке (выбор
падежа/рода — часть структуры боя, не текста, поэтому остаётся здесь).
i18n.enemy_names(enemy_type) отдаёт словарь форм для текущей локали — в
ru.py формы разные (падежи/род), в en.py все формы совпадают с одним
именем (английский не склоняется), поэтому вызывающий код ниже не
ветвится по локали вообще, только по структуре боя.
"""

from typing import Optional

from core import i18n
from core.combat_mechanics import POWER_ATTACK_DAMAGE_MULTIPLIER


def _name_kwargs(names: dict) -> dict:
    """Именованные плейсхолдеры под все грамматические формы противника
    сразу — конкретный t()-шаблон использует только нужные ему форматы,
    остальные str.format() молча игнорирует. Не включает dodge_verb/
    alive_adj — их берут напрямую там, где нужно (они не всегда
    относятся к противнику: например, dodge_verb для собственного
    уворота игрока — фиксированное слово, не форма из ENEMY_NAMES)."""
    return {
        "name_nom_cap": names["nom_cap"],
        "name_nom_low": names["nom_low"],
        "name_acc_cap": names["acc_cap"],
        "name_acc_low": names["acc_low"],
        "name_gen_low": names["gen_low"],
        "name_ins_cap": names["ins_cap"],
        "fled_verb": names["fled_verb"],
    }


def render_encounter(enemy_type: str, roll: int) -> str:
    names = i18n.enemy_names(enemy_type)
    return i18n.t("encounter.found", roll=roll, **_name_kwargs(names))


def render_boss_encounter() -> str:
    """Вход в бой с финальным боссом (docs/notes.md, п.36) — не через
    случайный ростер поиска (§6), поэтому без формата "🎲 Бросок: N → ..." у
    render_encounter: игрок выбирает эту встречу целенаправленно кнопкой, не
    кубиком."""
    names = i18n.enemy_names("boss")
    return i18n.t("encounter.boss", **_name_kwargs(names))


def render_initiative(enemy_type: str, player_roll: int, enemy_roll: int, first_role: str) -> str:
    names = i18n.enemy_names(enemy_type)
    nk = _name_kwargs(names)
    if first_role == "player":
        return i18n.t("combat.initiative.player_first", player_roll=player_roll, enemy_roll=enemy_roll, **nk)
    return i18n.t("combat.initiative.enemy_first", player_roll=player_roll, enemy_roll=enemy_roll, **nk)


def render_circumstance(enemy_type: str, roll: int, outcome, roller_role: str) -> str:
    if outcome is None:
        return i18n.t("combat.circumstance.none", roll=roll)

    names = i18n.enemy_names(enemy_type)
    key = f"combat.circumstance.{outcome}_{roller_role}"
    return i18n.t(key, roll=roll, name_gen_low=names["gen_low"], name_nom_low=names["nom_low"])


def render_double_strike_check(enemy_type: str, side_role: str, luck_roll: int, triggered: bool) -> str:
    suffix = "triggered" if triggered else "missed"
    if side_role == "player":
        return i18n.t(f"combat.double_strike.player_{suffix}", luck_roll=luck_roll)
    names = i18n.enemy_names(enemy_type)
    return i18n.t(f"combat.double_strike.enemy_{suffix}", luck_roll=luck_roll, name_nom_cap=names["nom_cap"])


def _attack_label(power_attack: bool, normal_label: str) -> str:
    """§3a: подпись атакующего действия — "💥 Мощный удар", если выбран
    мощный удар, иначе обычная подпись вызывающей функции (у полной и
    компактной формы разный текст для обычной атаки — "🗡️ Твоя атака" /
    "🗡️ Удар" — но один и тот же для мощного удара)."""
    return i18n.t("combat.strike.power_label") if power_attack else normal_label


def _damage_suffix(percent: int, power_attack: bool) -> str:
    """§3a: хвост строки атаки после "→" — процент силы, при мощном ударе с
    пометкой множителя урона (POWER_ATTACK_DAMAGE_MULTIPLIER, не хардкод)."""
    if power_attack:
        return i18n.t("combat.strike.damage_percent_power", percent=percent, multiplier=f"{POWER_ATTACK_DAMAGE_MULTIPLIER:g}")
    return i18n.t("combat.strike.damage_percent", percent=percent)


def render_strike(
    enemy_type: str,
    side_role: str,
    attack_roll: int,
    attack_percent,
    dodge_roll,
    dodged,
    damage: float,
    power_attack: bool = False,
) -> str:
    """Полная (многострочная) форма одного удара — вне двойного удара.

    power_attack (docs/combat_mechanics.md §3a) — только у игрока (мобы им
    не пользуются, см. api/routers/combat.py::_resolve_attacker_turn), меняет
    только строку атаки (эмодзи/подпись/пометка множителя урона, значение —
    core.combat_mechanics.POWER_ATTACK_DAMAGE_MULTIPLIER, не хардкод) —
    уворот и урон уже посчитаны вызывающим кодом с учётом множителя, здесь
    только отображение."""
    names = i18n.enemy_names(enemy_type)
    power_attack = power_attack and side_role == "player"  # мобы мощным ударом не пользуются, вне зависимости от переданного флага
    if side_role == "player":
        dodge_label = i18n.t("combat.strike.enemy_dodge_label", name_nom_cap=names["nom_cap"])
        damage_verb = i18n.t("combat.strike.player_damage_verb")
        dodge_verb = names["dodge_verb"]
        attack_label = _attack_label(power_attack, i18n.t("combat.strike.player_attack_label"))
    else:
        attack_label = i18n.t(
            "combat.strike.enemy_attack_label", name_gen_low=names["gen_low"], name_nom_cap=names["nom_cap"]
        )
        dodge_label = i18n.t("combat.strike.player_dodge_label")
        damage_verb = i18n.t("combat.strike.enemy_damage_verb", name_nom_cap=names["nom_cap"])
        dodge_verb = i18n.t("combat.strike.player_dodge_verb")

    if attack_percent is None:
        return i18n.t("combat.strike.miss", attack_label=attack_label, attack_roll=attack_roll)

    percent_part = _damage_suffix(attack_percent, power_attack)
    lines = [i18n.t("combat.strike.header", attack_label=attack_label, attack_roll=attack_roll, percent_part=percent_part)]
    if dodged:
        lines.append(i18n.t("combat.strike.dodge_success", dodge_label=dodge_label, dodge_roll=dodge_roll, dodge_verb=dodge_verb))
        lines.append(i18n.t("combat.strike.damage_avoided"))
    else:
        lines.append(i18n.t("combat.strike.dodge_fail", dodge_label=dodge_label, dodge_roll=dodge_roll))
        lines.append(i18n.t("combat.strike.damage_dealt", damage_verb=damage_verb, damage=f"{damage:.0f}"))
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
    power_attack: bool = False,
) -> str:
    """Компактная (однострочная) форма удара — используется внутри двойного
    удара. power_attack — см. render_strike, тот же принцип (только игрок,
    только подпись/эмодзи/пометка множителя)."""
    names = i18n.enemy_names(enemy_type)
    power_attack = power_attack and side_role == "player"  # мобы мощным ударом не пользуются, вне зависимости от переданного флага
    if side_role == "player":
        dodge_label = i18n.t("combat.strike.enemy_dodge_label", name_nom_cap=names["nom_cap"])
        dodge_verb = names["dodge_verb"]
        strike_label = _attack_label(power_attack, i18n.t("combat.compact_strike.attack_label"))
    else:
        dodge_label = i18n.t("combat.compact_strike.player_dodge_label")
        dodge_verb = i18n.t("combat.strike.player_dodge_verb")
        strike_label = i18n.t("combat.compact_strike.attack_label")

    if attack_percent is None:
        return i18n.t("combat.compact_strike.miss", strike_label=strike_label, strike_number=strike_number, attack_roll=attack_roll)

    percent_part = _damage_suffix(attack_percent, power_attack)
    parts = [i18n.t(
        "combat.compact_strike.header",
        strike_label=strike_label, strike_number=strike_number, attack_roll=attack_roll, percent_part=percent_part,
    )]
    if dodged:
        parts.append(i18n.t("combat.strike.dodge_success", dodge_label=dodge_label, dodge_roll=dodge_roll, dodge_verb=dodge_verb))
    else:
        parts.append(i18n.t("combat.strike.dodge_fail", dodge_label=dodge_label, dodge_roll=dodge_roll))
        parts.append(i18n.t("combat.compact_strike.damage", damage=f"{damage:.0f}"))
    return " ".join(parts)


def render_potion_used(size: str, heal: float) -> str:
    """Автоматическое исцеление зельем в начале хода игрока (docs/notes.md,
    п.31) — не бросок, поэтому без "🎲"; показывает сам факт и сколько
    вылечило, тем же принципом прозрачности, что и остальной бой."""
    label = i18n.t("combat.potion.large_label") if size == "large" else i18n.t("combat.potion.small_label")
    return i18n.t("combat.potion.used", label=label, heal=f"{heal:.0f}")


def render_hp_status(
    enemy_type: str,
    player_hp: float,
    player_hp_max: float,
    enemy_hp: float,
    enemy_hp_max: float,
) -> str:
    """Шапка статуса HP — печатается первой строкой в каждом сообщении боя."""
    names = i18n.enemy_names(enemy_type)
    return i18n.t(
        "combat.hp_status",
        player_hp=f"{player_hp:.0f}", player_hp_max=f"{player_hp_max:.0f}",
        name_nom_cap=names["nom_cap"],
        enemy_hp=f"{enemy_hp:.0f}", enemy_hp_max=f"{enemy_hp_max:.0f}",
    )


def render_flee_opportunity_check(
    enemy_type: str, side_role: str, current_hp: float, max_hp: float, luck_roll: int, triggered: bool
) -> str:
    """Чья это проверка, должно быть видно сразу — иначе не отличить свою
    проверку на побег от проверки моба (см. docs/notes.md, п.6)."""
    if side_role == "player":
        hp_label = i18n.t("combat.flee_check.player_hp_label")
        prefix = i18n.t("combat.flee_check.player_prefix")
        alive_adj = i18n.t("combat.flee_check.player_alive_adj")
    else:
        names = i18n.enemy_names(enemy_type)
        hp_label = i18n.t(
            "combat.flee_check.enemy_hp_label", name_gen_low=names["gen_low"], name_nom_low=names["nom_low"]
        )
        prefix = i18n.t("combat.flee_check.enemy_prefix", name_nom_cap=names["nom_cap"])
        alive_adj = names["alive_adj"]

    if triggered:
        return i18n.t(
            "combat.flee_check.triggered",
            hp_label=hp_label, current_hp=f"{current_hp:.0f}", max_hp=f"{max_hp:.0f}",
            prefix=prefix, luck_roll=luck_roll, alive_adj=alive_adj,
        )
    return i18n.t("combat.flee_check.not_triggered", prefix=prefix, luck_roll=luck_roll)


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
    names = i18n.enemy_names(enemy_type)
    nk = _name_kwargs(names)
    damage_str = f"{damage:.0f}"
    if fleeing_role == "player":
        if attack_percent is None:
            return i18n.t("combat.flee_attempt.player_miss", attack_roll=attack_roll, **nk)
        if defeated:
            return i18n.t(
                "combat.flee_attempt.player_caught",
                attack_roll=attack_roll, attack_percent=attack_percent, damage=damage_str, **nk,
            )
        return i18n.t(
            "combat.flee_attempt.player_survives",
            attack_roll=attack_roll, attack_percent=attack_percent, damage=damage_str, **nk,
        )

    if attack_percent is None:
        return i18n.t("combat.flee_attempt.enemy_miss", attack_roll=attack_roll, **nk)
    if defeated:
        return i18n.t(
            "combat.flee_attempt.enemy_caught",
            attack_roll=attack_roll, attack_percent=attack_percent, damage=damage_str, **nk,
        )
    return i18n.t(
        "combat.flee_attempt.enemy_survives",
        attack_roll=attack_roll, attack_percent=attack_percent, damage=damage_str, **nk,
    )


def render_battle_end(
    enemy_type: str,
    result: str,
    reward: int,
    victory_points_total: int,
    hp_current: float,
    hp_max: float,
    hp_seconds_to_full: float,
    loot_dropped: Optional[str] = None,
) -> str:
    names = i18n.enemy_names(enemy_type)
    nk = _name_kwargs(names)
    reward_line = None
    if result == "victory":
        header = i18n.t("combat.battle_end.victory_header", **nk)
        reward_line = i18n.t("combat.battle_end.reward_line", reward=reward, victory_points_total=victory_points_total)
    elif result == "defeat":
        header = i18n.t("combat.battle_end.defeat_header", **nk)
    elif result == "player_fled":
        header = i18n.t("combat.battle_end.player_fled_header", **nk)
    elif result == "enemy_fled":
        header = i18n.t("combat.battle_end.enemy_fled_header", **nk)
    else:
        raise ValueError(f"unknown battle result: {result!r}")

    lines = [header]
    if reward_line:
        lines.append(reward_line)
    if result == "victory":
        if loot_dropped:
            loot_name = i18n.loot_item_names().get(loot_dropped, loot_dropped)
            lines.append(i18n.t("combat.battle_end.loot_line", loot_name=loot_name))
        else:
            # Лут — не гарантирован (core.economy.resolve_loot_drop может
            # выкатить "nothing"), явная строка вместо молчания — иначе
            # игрок не может отличить "лута не было в принципе" от того,
            # что о нём просто забыли показать (docs/notes.md).
            lines.append(i18n.t("combat.battle_end.no_loot_line"))
    lines.append("")
    lines.append(i18n.t("combat.battle_end.hp_line", hp_current=f"{hp_current:.0f}", hp_max=f"{hp_max:.0f}"))
    if hp_seconds_to_full > 0:
        lines.append(i18n.t("combat.battle_end.regen_line", hp_seconds_to_full=f"{hp_seconds_to_full:.0f}"))
    return "\n".join(lines)


def render_boss_victory() -> str:
    """Победа над финальным боссом — конец игры (docs/notes.md, п.36/п.54), не
    обычный `render_battle_end`: без строки HP/таймера регена и без награды
    (победные очки за неё не начисляются — персонаж всё равно обнуляется
    следующим нажатием, очки ему больше не нужны), с отдельным
    поздравительным заголовком вместо стандартного "Бой окончен!"."""
    names = i18n.enemy_names("boss")
    return i18n.t("combat.boss_victory", name_acc_cap=names["acc_cap"])


def render_fight_confirmed() -> str:
    """Подтверждение "принял бой" (docs/notes.md, п.81/блок 6) —
    api/routers/combat.py::confirm_combat, ветка decision="fight". Раньше
    это был сырой литерал в самом роутере, в обход этого модуля/core.i18n
    целиком — единственное такое место, все остальные ответы combat-роутера
    уже шли через render_*/i18n.t()."""
    return i18n.t("combat.fight_confirmed")
