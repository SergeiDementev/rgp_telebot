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

    # --- Character screen (bot/handlers/character.py, docs/notes.md, block 3) ---
    "character.menu_title": "👤 Player Menu",
    "character.creation_title": "🧙 Hero Creation",
    "character.button.refresh": "🔄 Refresh",
    "character.button.search_encounter": "🔍 Search for an enemy",
    "character.button.rules": "📜 Rules",
    "character.button.boss": "⚔️ Final Boss",
    "character.button.back": "⬅️ Back",
    "character.button.reset": "🗑 Reset character",
    "character.button.sell_loot": "💰 Sell all loot",
    "character.button.start_adventure": "✅ Start the adventure",
    "character.allocate_button": "+1 {name}",

    "character.stat.strength": "Strength",
    "character.stat.agility": "Agility",
    "character.stat.luck": "Luck",
    "character.stat.vitality": "Vitality",
    "character.stat_line": "{emoji} {name}: {value}",
    "character.vitality_line": "❤️ {name}: {value}  (HP max: {hp_max})",

    "character.level_line": "🏅 Level: {level}",
    "character.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "character.victory_points_line": "🏆 Victory points: {victory_points} (to next level: {points_to_next_level})",
    "character.unspent_points_line": "Points left: {unspent_stat_points}",
    "character.unspent_points_available_line": "Stat points available: {unspent_stat_points}",
    "character.gold_line": "💰 Gold: {gold}",

    "character.loot_line": "📦 Loot: {items}",
    "character.loot_empty": "📦 Loot: none yet",
    "character.potions_line": "🧪 Potions: {items}",
    "character.potions_empty": "🧪 Potions: none yet",
    "character.loot_item_single": "{name} ({price} gold)",
    "character.loot_item_multiple": "{name} ×{count} ({total_price} gold)",
    "character.potion_count": "{name} ×{count}",

    "character.potion_cap_reached": "already at max",
    "character.potion_price": "{price} gold",
    "character.buy_potion_button": "🧪 Buy {name} ({status})",

    "character.buy_error.not_enough_gold": "Not enough gold.",
    "character.buy_error.cap_reached": "Already at the maximum for this potion size.",
    "character.buy_error.generic": "Couldn't buy the potion.",
    "character.allocate_error.no_points": "No stat points left",

    # --- Bot combat UI (bot/handlers/combat.py, docs/notes.md, block 4) ---
    "combat.ui.button.attack": "🎲 Attack",
    "combat.ui.button.defend": "🛡️ Defend",
    "combat.ui.button.flee": "🏃 Flee",
    "combat.ui.button.continue_fight": "⚔️ Keep fighting",
    "combat.ui.button.restart": "🔄 Start over",
    "combat.ui.button.determine_initiative": "⚔️ Roll initiative",
    "combat.ui.button.boss_challenge": "⚔️ Challenge (from level {level})",
    "combat.ui.button.boss_challenge_confirm": "⚔️ Yes, enter the fight",
    "combat.ui.button.enter_battle": "⚔️ Enter the fight",
    "combat.ui.button.retreat": "🏃 Retreat",
    "combat.ui.button.autobattle": "⚡ Auto-battle",
    "combat.ui.potion_stock": "🧪 Your stock:\n  {small_label}: {potions_small}/{small_cap}\n  {large_label}: {potions_large}/{large_cap}",

    "combat.ui.error.already_in_battle": "You already have an unfinished battle — finish it first.",
    "combat.ui.error.cant_cancel_started": "The battle has already started — it can't be cancelled.",
    "combat.ui.error.boss_unavailable": "The final boss isn't available at this level yet.",
    "combat.ui.warning.boss_no_retreat": "⚠️ After this, there's no retreating.",
    "combat.ui.error.cant_flee": "You can't retreat from this battle.",
    "combat.ui.error.potion_already_used": "A potion has already been used this battle.",
    "combat.ui.error.potion_not_owned": "You don't have that potion.",
    "combat.ui.error.potion_generic": "You can't use a potion right now.",

    # --- /language (bot/handlers/language.py, block 4) ---
    "language.confirmation": "✅ Language switched to English.",

    # --- /start, /reset (bot/handlers/start.py + bot/utils.py, block 4) ---
    "start.welcome": (
        "🧙 Welcome to the text RPG!\n\n"
        "Search for enemies, fight with dice rolls, level up your character. "
        "The ultimate goal — grow strong enough to defeat the final boss.\n\n"
        "🌐 /language — сменить язык / switch language"
    ),
    "start.button.start_game": "✅ Start the game",
    "start.resume_prefix": "↩️ Resuming your battle:\n\n",
    "start.reset_confirm": (
        "⚠️ Reset your character for real?\n\n"
        "Stats, level and all progress will be permanently deleted — this can't be undone."
    ),
    "start.button.reset_yes": "🗑 Yes, delete",
    "start.button.cancel": "Cancel",
    "start.reset_done": "Character reset",

    # --- /rules (bot/handlers/character.py + bot/rules_content.py, block 5) ---
    "rules.menu_header": "📖 <b>{title}</b>\n\nChoose a section:",
    "rules.button.back_to_sections": "⬅️ Back to sections",
}
