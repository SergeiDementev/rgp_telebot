"""Английские переводы (docs/notes.md) — наполняются по мере блоков 2-5.

См. i18n/ru.py про соглашение по ключам (плоские, точечный неймспейс).

ENEMY_NAMES — тот же набор ключей (nom_cap/nom_low/acc_cap/acc_low/
gen_low/ins_cap/dodge_verb/alive_adj/fled_verb), что и в ru.py, но
английский не склоняется по падежам/родам — все "формы" одного
противника совпадают с одним именем (капитализация — единственное
различие). api/rendering.py читает оба словаря одинаково, без ветвления
по локали (docs/notes.md, блок 2)."""

ENEMY_NAMES = {
    "mouse": {
        "nom_cap": "Mouse", "nom_low": "mouse",
        "acc_cap": "Mouse", "acc_low": "mouse",
        "gen_low": "mouse",
        "ins_cap": "Mouse",
        "dodge_verb": "dodged",
        "alive_adj": "alive",
        "fled_verb": "fled",
    },
    "wolf": {
        "nom_cap": "Wolf", "nom_low": "wolf",
        "acc_cap": "Wolf", "acc_low": "wolf",
        "gen_low": "wolf",
        "ins_cap": "Wolf",
        "dodge_verb": "dodged",
        "alive_adj": "alive",
        "fled_verb": "fled",
    },
    "boar": {
        "nom_cap": "Boar", "nom_low": "boar",
        "acc_cap": "Boar", "acc_low": "boar",
        "gen_low": "boar",
        "ins_cap": "Boar",
        "dodge_verb": "dodged",
        "alive_adj": "alive",
        "fled_verb": "fled",
    },
    "boss": {
        "nom_cap": "Forest King", "nom_low": "forest king",
        "acc_cap": "Forest King", "acc_low": "forest king",
        "gen_low": "forest king",
        "ins_cap": "Forest King",
        "dodge_verb": "dodged",
        "alive_adj": "alive",
        "fled_verb": "fled",
    },
}

LOOT_ITEM_NAMES = {
    "mouse_pelt": "Mouse pelt",
    "mouse_tail": "Mouse tail",
    "wolf_fang": "Wolf fang",
    "wolf_pelt": "Wolf pelt",
    "boar_tusk": "Boar tusk",
    "boar_hide": "Boar hide",
}

TRANSLATIONS: dict[str, str] = {
    "encounter.found": "🎲 Roll: {roll} → {name_nom_cap}!\n\nYou ran into a {name_acc_low}.",
    "encounter.boss": "👑 You step into the {name_nom_cap}'s hall. There's no turning back — he's already watching you.",

    "combat.initiative.player_first": "🎲 Initiative: you — {player_roll}, {name_nom_low} — {enemy_roll}. You go first!",
    "combat.initiative.enemy_first": "🎲 Initiative: {name_nom_low} — {enemy_roll}, you — {player_roll}. {name_nom_cap} attacks first!",

    "combat.circumstance.none": "🎲 Circumstance: {roll} → nothing happens.",
    "combat.circumstance.buff_player": "🎲 Circumstance: {roll} → ⚡ Adrenaline rush!\nYour Strength is increased for this fight (×1.2)",
    "combat.circumstance.buff_enemy": "🎲 Circumstance: {roll} → ⚡ Adrenaline rush!\nThe {name_nom_low}'s Strength is increased for this fight (×1.2)",
    "combat.circumstance.debuff_player": "🎲 Circumstance: {roll} → ⚡ Slippery ground\nYour Strength is decreased for this fight (×0.8)",
    "combat.circumstance.debuff_enemy": "🎲 Circumstance: {roll} → ⚡ Slippery ground\nThe {name_nom_low}'s Strength is decreased for this fight (×0.8)",

    "combat.double_strike.player_triggered": "🎲 Your luck check: {luck_roll} → ✨ LUCKY! Double strike!",
    "combat.double_strike.player_missed": "🎲 Your luck check: {luck_roll} → no double strike.",
    "combat.double_strike.enemy_triggered": "🎲 {name_nom_cap} rolls for luck: {luck_roll} → ✨ LUCKY! Double strike!",
    "combat.double_strike.enemy_missed": "🎲 {name_nom_cap} rolls for luck: {luck_roll} → no double strike.",

    "combat.strike.power_label": "💥 Power attack",
    "combat.strike.damage_percent_power": "{percent}% strength, damage ×{multiplier}!",
    "combat.strike.damage_percent": "{percent}% strength.",
    "combat.strike.player_attack_label": "🗡️ Your attack",
    "combat.strike.enemy_attack_label": "🗡️ {name_nom_cap}'s attack",
    "combat.strike.enemy_dodge_label": "{name_nom_cap} dodges",
    "combat.strike.player_dodge_label": "Your dodge",
    "combat.strike.player_damage_verb": "You deal",
    "combat.strike.enemy_damage_verb": "{name_nom_cap} deals",
    "combat.strike.player_dodge_verb": "dodged",
    "combat.strike.miss": "{attack_label}: {attack_roll} → miss!",
    "combat.strike.header": "{attack_label}: {attack_roll} → {percent_part}",
    "combat.strike.dodge_success": "🛡️ {dodge_label}: {dodge_roll} → {dodge_verb}!",
    "combat.strike.damage_avoided": "✅ Damage fully avoided.",
    "combat.strike.dodge_fail": "🛡️ {dodge_label}: {dodge_roll} → failed!",
    "combat.strike.damage_dealt": "💥 {damage_verb} {damage} damage.",

    "combat.compact_strike.attack_label": "🗡️ Strike",
    "combat.compact_strike.player_dodge_label": "You dodge",
    "combat.compact_strike.miss": "{strike_label} {strike_number}: {attack_roll} → miss.",
    "combat.compact_strike.header": "{strike_label} {strike_number}: {attack_roll} → {percent_part}",
    "combat.compact_strike.damage": "💥 {damage} damage.",

    "combat.potion.large_label": "Large",
    "combat.potion.small_label": "Small",
    "combat.potion.used": "🧪 {label} potion: +{heal} HP.",

    "combat.hp_status": "❤️ You: {player_hp}/{player_hp_max}   👹 {name_nom_cap}: {enemy_hp}/{enemy_hp_max}",

    "combat.flee_check.player_hp_label": "Your HP is critically low",
    "combat.flee_check.player_prefix": "Your luck check to flee",
    "combat.flee_check.player_alive_adj": "alive",
    "combat.flee_check.enemy_hp_label": "The {name_nom_low}'s HP is critically low",
    "combat.flee_check.enemy_prefix": "{name_nom_cap} rolls for luck to flee",
    "combat.flee_check.triggered": "⚠️ {hp_label}! ({current_hp}/{max_hp})\n🍀 {prefix}: {luck_roll} → there's a chance to get away {alive_adj}!",
    "combat.flee_check.not_triggered": "🍀 {prefix}: {luck_roll} → no chance to get away this time.",

    "combat.flee_attempt.player_miss": (
        "🏃 You try to flee — the {name_nom_low} strikes unopposed!\n"
        "🎲 {name_nom_cap}'s attack: {attack_roll} → miss!\n"
        "✅ You get away clean."
    ),
    "combat.flee_attempt.player_caught": (
        "🏃 You try to flee — the {name_nom_low} strikes unopposed!\n"
        "🎲 {name_nom_cap}'s attack: {attack_roll} → {attack_percent}% strength.\n"
        "💀 The blow catches you ({damage} damage)."
    ),
    "combat.flee_attempt.player_survives": (
        "🏃 You try to flee — the {name_nom_low} strikes unopposed!\n"
        "🎲 {name_nom_cap}'s attack: {attack_roll} → {attack_percent}% strength.\n"
        "💥 {damage} damage on your way out, but you break free."
    ),
    "combat.flee_attempt.enemy_miss": (
        "🏃 {name_nom_cap} tries to flee — your strike goes unopposed!\n"
        "🎲 Your attack: {attack_roll} → miss!\n"
        "{name_nom_cap} gets away."
    ),
    "combat.flee_attempt.enemy_caught": (
        "🏃 {name_nom_cap} tries to flee — your strike goes unopposed!\n"
        "🎲 Your attack: {attack_roll} → {attack_percent}% strength.\n"
        "💀 You finish off the {name_acc_low} as it flees ({damage} damage)."
    ),
    "combat.flee_attempt.enemy_survives": (
        "🏃 {name_nom_cap} tries to flee — your strike goes unopposed!\n"
        "🎲 Your attack: {attack_roll} → {attack_percent}% strength.\n"
        "💥 {damage} damage, but the {name_nom_low} breaks free."
    ),

    "combat.battle_end.victory_header": "⚔️ Battle over! You defeated the {name_acc_cap}.",
    "combat.battle_end.reward_line": "🏆 +{reward} victory points (total: {victory_points_total})",
    "combat.battle_end.defeat_header": "💀 You died in battle with the {name_ins_cap}...",
    "combat.battle_end.player_fled_header": "🏃 You managed to escape the fight with the {name_ins_cap}.",
    "combat.battle_end.enemy_fled_header": "🏃 {name_nom_cap} {fled_verb}, you couldn't finish it off.",
    "combat.battle_end.loot_line": "🎁 Loot: {loot_name}",
    "combat.battle_end.no_loot_line": "😕 Aww, no luck with loot this time...",
    "combat.battle_end.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "combat.battle_end.regen_line": "⏳ Full recovery in: ~{hp_seconds_to_full} sec.",

    "combat.boss_victory": "🎉 You have defeated the {name_acc_cap}!\n\nThe adventure is over. Thanks for playing!",
}
