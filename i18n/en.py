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
        "gen_low": "Forest King",
        "ins_cap": "Forest King",
        "dodge_verb": "dodged",
        "alive_adj": "alive",
        "fled_verb": "fled",
    },
}

LOOT_ITEM_NAMES = {
    "mouse_pelt": "Mouse Pelt",
    "mouse_tail": "Mouse Tail",
    "wolf_fang": "Wolf Fang",
    "wolf_pelt": "Wolf Pelt",
    "boar_tusk": "Boar Tusk",
    "boar_hide": "Boar Hide",
}

TRANSLATIONS: dict[str, str] = {
    "encounter.found": "🎲 Roll: {roll} → {name_nom_cap}!\n\nYou encounter {name_acc_low}.",
    "encounter.boss": "👑 You enter {name_acc_cap}'s lair. There's nowhere to run — it already has its eyes on you.",

    "combat.initiative.player_first": "🎲 Initiative: you — {player_roll}, {name_nom_low} — {enemy_roll}. You go first!",
    "combat.initiative.enemy_first": "🎲 Initiative: {name_nom_low} — {enemy_roll}, you — {player_roll}. {name_nom_cap} goes first!",

    "combat.circumstance.none": "🎲 Event: {roll} → Nothing happens.",
    "combat.circumstance.buff_player": "🎲 Event: {roll} → ⚡ Adrenaline Rush!\nYour Strength is increased for this battle (×1.2)",
    "combat.circumstance.buff_enemy": "🎲 Event: {roll} → ⚡ Adrenaline Rush!\n{name_gen_low}'s Strength is increased for this battle (×1.2)",
    "combat.circumstance.debuff_player": "🎲 Event: {roll} → ⚡ Slippery Ground\nYour Strength is reduced for this battle (×0.8)",
    "combat.circumstance.debuff_enemy": "🎲 Event: {roll} → ⚡ Slippery Ground\n{name_gen_low}'s Strength is reduced for this battle (×0.8)",

    "combat.double_strike.player_triggered": "🎲 Your Luck roll: {luck_roll} → ✨ LUCKY! Double strike!",
    "combat.double_strike.player_missed": "🎲 Your Luck roll: {luck_roll} → no double strike.",
    "combat.double_strike.enemy_triggered": "🎲 {name_nom_cap} rolls for Luck: {luck_roll} → ✨ LUCKY! Double strike!",
    "combat.double_strike.enemy_missed": "🎲 {name_nom_cap} rolls for Luck: {luck_roll} → no double strike.",

    "combat.strike.power_label": "💥 Powerful Strike",
    "combat.strike.damage_percent_power": "{percent}% power, damage ×{multiplier}!",
    "combat.strike.damage_percent": "{percent}% power.",
    "combat.strike.player_attack_label": "🗡️ Your attack",
    "combat.strike.enemy_attack_label": "🗡️ {name_gen_low}'s attack",
    "combat.strike.enemy_dodge_label": "{name_nom_cap} dodges",
    "combat.strike.player_dodge_label": "Your dodge",
    "combat.strike.player_damage_verb": "You deal",
    "combat.strike.enemy_damage_verb": "{name_nom_cap} deals",
    "combat.strike.player_dodge_verb": "dodged",
    "combat.strike.miss": "{attack_label}: {attack_roll} → Miss!",
    "combat.strike.header": "{attack_label}: {attack_roll} → {percent_part}",
    "combat.strike.dodge_success": "🛡️ {dodge_label}: {dodge_roll} → {dodge_verb}!",
    "combat.strike.damage_avoided": "✅ All damage avoided.",
    "combat.strike.dodge_fail": "🛡️ {dodge_label}: {dodge_roll} → Failed!",
    "combat.strike.damage_dealt": "💥 {damage_verb} {damage} damage.",

    "combat.compact_strike.attack_label": "🗡️ Strike",
    "combat.compact_strike.player_dodge_label": "You dodge",
    "combat.compact_strike.miss": "{strike_label} {strike_number}: {attack_roll} → Miss.",
    "combat.compact_strike.header": "{strike_label} {strike_number}: {attack_roll} → {percent_part}",
    "combat.compact_strike.damage": "💥 {damage} damage.",

    "combat.potion.large_label": "Large",
    "combat.potion.small_label": "Small",
    "combat.potion.used": "🧪 {label} Potion: +{heal} HP.",

    "combat.hp_status": "❤️ You: {player_hp}/{player_hp_max}   👹 {name_nom_cap}: {enemy_hp}/{enemy_hp_max}",

    "combat.flee_check.player_hp_label": "Your HP is critically low",
    "combat.flee_check.player_prefix": "Your escape chance roll",
    "combat.flee_check.player_alive_adj": "alive",
    "combat.flee_check.enemy_hp_label": "{name_gen_low}'s HP is critically low",
    "combat.flee_check.enemy_prefix": "{name_nom_cap} rolls for a chance to flee",
    "combat.flee_check.triggered": "⚠️ {hp_label}! ({current_hp}/{max_hp})\n🍀 {prefix}: {luck_roll} → a chance to escape while {alive_adj}!",
    "combat.flee_check.not_triggered": "🍀 {prefix}: {luck_roll} → no chance to escape this time.",

    "combat.flee_attempt.player_miss": (
        "🏃 You try to flee — {name_nom_low} gets a free hit!\n🎲 {name_gen_low}'s attack: {attack_roll} → Miss!\n✅ You make a clean escape."
    ),
    "combat.flee_attempt.player_caught": (
        "🏃 You try to flee — {name_nom_low} gets a free hit!\n🎲 {name_gen_low}'s attack: {attack_roll} → {attack_percent}% power.\n💀 The hit catches you ({damage} damage)."
    ),
    "combat.flee_attempt.player_survives": (
        "🏃 You try to flee — {name_nom_low} gets a free hit!\n🎲 {name_gen_low}'s attack: {attack_roll} → {attack_percent}% power.\n💥 You take {damage} damage, but get away."
    ),
    "combat.flee_attempt.enemy_miss": (
        "🏃 {name_nom_cap} tries to flee — you get a free hit!\n🎲 Your attack: {attack_roll} → Miss!\n{name_nom_cap} escapes."
    ),
    "combat.flee_attempt.enemy_caught": (
        "🏃 {name_nom_cap} tries to flee — you get a free hit!\n🎲 Your attack: {attack_roll} → {attack_percent}% power.\n💀 You finish off {name_acc_low} while it flees ({damage} damage)."
    ),
    "combat.flee_attempt.enemy_survives": (
        "🏃 {name_nom_cap} tries to flee — you get a free hit!\n🎲 Your attack: {attack_roll} → {attack_percent}% power.\n💥 {damage} damage, but {name_nom_low} gets away."
    ),

    "combat.battle_end.victory_header": "⚔️ Battle over! You defeated {name_acc_cap}.",
    "combat.battle_end.reward_line": "🏆 +{reward} Victory Points (total: {victory_points_total})",
    "combat.battle_end.defeat_header": "💀 You were defeated by {name_ins_cap}...",
    "combat.battle_end.player_fled_header": "🏃 You escaped from {name_ins_cap}.",
    "combat.battle_end.enemy_fled_header": "🏃 {name_nom_cap} {fled_verb}, and you couldn't finish it off.",
    "combat.battle_end.loot_line": "🎁 Loot: {loot_name}",
    "combat.battle_end.no_loot_line": "😕 No luck with the loot...",
    "combat.battle_end.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "combat.battle_end.regen_line": "⏳ Fully restored in: ~{hp_seconds_to_full} sec.",

    "combat.boss_victory": "🎉 You have defeated {name_acc_cap}!\n\nYour adventure is complete. Thanks for playing!",

    # docs/notes.md, block 6 — api/routers/combat.py::confirm_combat, the
    # decision="fight" branch.
    "combat.fight_confirmed": "⚔️ You engage in combat!",

    # --- Character screen (bot/handlers/character.py, docs/notes.md, block 3) ---
    "character.menu_title": "👤 Player Menu",
    "character.creation_title": "🧙 Create Your Hero",
    "character.button.refresh": "🔄 Refresh",
    "character.button.search_encounter": "🔍 Find an Enemy",
    "character.button.rules": "📜 Rules",
    "character.button.boss": "⚔️ Final Boss",
    "character.button.back": "⬅️ Back",
    "character.button.reset": "🗑 Reset Character",
    "character.button.sell_loot": "💰 Sell All Loot",
    "character.button.start_adventure": "✅ Start Adventure",
    "character.allocate_button": "+1 {name}",

    "character.stat.strength": "Strength",
    "character.stat.agility": "Agility",
    "character.stat.luck": "Luck",
    "character.stat.vitality": "Vitality",
    "character.stat_line": "{emoji} {name}: {value}",
    "character.vitality_line": "❤️ {name}: {value} (Max HP: {hp_max})",

    "character.level_line": "🏅 Level: {level}",
    "character.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "character.victory_points_line": "🏆 Victory Points: {victory_points} (to next level: {points_to_next_level})",
    "character.unspent_points_line": "Points remaining: {unspent_stat_points}",
    "character.unspent_points_available_line": "Available upgrade points: {unspent_stat_points}",
    "character.gold_line": "💰 Gold: {gold}",

    "character.loot_line": "📦 Loot: {items}",
    "character.loot_empty": "📦 Loot: None yet",
    "character.potions_line": "🧪 Potions: {items}",
    "character.potions_empty": "🧪 Potions: None yet",
    "character.loot_item_single": "{name} ({price} gold)",
    "character.loot_item_multiple": "{name} ×{count} ({total_price} gold)",
    "character.potion_count": "{name} ×{count}",

    "character.potion_cap_reached": "Maximum stock reached",
    "character.potion_price": "{price} gold",
    "character.buy_potion_button": "🧪 Buy {name} ({status})",

    "character.buy_error.not_enough_gold": "Not enough gold.",
    "character.buy_error.cap_reached": "You already have the maximum number of potions of this size.",
    "character.buy_error.generic": "Could not purchase the potion.",
    "character.allocate_error.no_points": "No unspent points remaining.",

    # --- Bot combat UI (bot/handlers/combat.py, docs/notes.md, block 4) ---
    "combat.ui.button.attack": "🎲 Attack",
    "combat.ui.button.defend": "🛡️ Defend",
    "combat.ui.button.flee": "🏃 Flee",
    "combat.ui.button.continue_fight": "⚔️ Keep Fighting",
    "combat.ui.button.restart": "🔄 Start Over",
    "combat.ui.button.determine_initiative": "⚔️ Roll for Initiative",
    "combat.ui.button.boss_challenge": "⚔️ Challenge (Level {level}+)",
    "combat.ui.button.boss_challenge_confirm": "⚔️ Yes, fight!",
    "combat.ui.button.enter_battle": "⚔️ Enter Battle",
    "combat.ui.button.retreat": "🏃 Retreat",
    "combat.ui.button.autobattle": "⚡ Auto-Battle",
    "combat.ui.potion_stock": "🧪 Your stock:\n  {small_label}: {potions_small}/{small_cap}\n  {large_label}: {potions_large}/{large_cap}",

    "combat.ui.error.already_in_battle": "You already have an unfinished battle. Finish it first.",
    "combat.ui.error.cant_cancel_started": "The battle has started and can't be cancelled.",
    "combat.ui.error.boss_unavailable": "The Final Boss is not available at your current level.",
    "combat.ui.warning.boss_no_retreat": "⚠️ You won't be able to retreat after this.",
    "combat.ui.error.cant_flee": "You can't retreat from a fight against this enemy.",
    "combat.ui.error.potion_already_used": "You've already used a potion in this battle.",
    "combat.ui.error.potion_not_owned": "You don't have that potion.",
    "combat.ui.error.potion_generic": "You can't use a potion right now.",
    "combat.ui.error.battle_in_progress": "⚠️ Battle is already in progress — here's the current state:",
    "combat.ui.error.battle_already_resolved": "This battle has already ended.",

    # --- /start, /reset (bot/handlers/start.py + bot/utils.py, block 4) ---
    "start.welcome": (
        "🧙 Welcome to this text-based RPG!\n\nFind enemies, fight them with dice, and level up your character. Your ultimate goal is to grow stronger and defeat the Final Boss.\n\nIf the bot stops responding, send /start."
    ),
    "start.button.start_game": "✅ Start Game",
    "start.resume_prefix": "↩️ Resuming your current battle:\n\n",
    "start.reset_confirm": (
        "⚠️ Are you sure you want to reset your character?\n\nYour stats, level, and all progress will be permanently deleted. This cannot be undone."
    ),
    "start.button.reset_yes": "🗑 Yes, Reset",
    "start.button.cancel": "Cancel",
    "start.reset_done": "Character reset.",
    "start.error.send_failed": "⚠️ Couldn't send the message — there may be a temporary connection issue. Try /start again in a minute.",

    # --- /rules (bot/handlers/character.py + bot/rules_content.py, block 5) ---
    "rules.menu_header": "📖 <b>{title}</b>\n\nChoose a section:",
    "rules.button.back_to_sections": "⬅️ Back to Sections",

    # --- bot/handlers/fallback.py (block 6) ---
    "fallback.unknown_text": "Use the buttons below the messages to control the game.",
}
