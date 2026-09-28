"""Русские переводы (docs/notes.md) — наполняются по мере блоков 2-5.

Ключи — плоские строки с точечным "неймспейсом" внутри самого ключа
(например, "combat.miss"), не вложенные словари: core/i18n.py::t() делает
один lookup по ключу целиком, не спускается по составным частям — так
проще и сам поиск, и грепать конкретный ключ по всему репозиторию.

Блок 2 — боевые тексты (api/rendering.py), дословно перенесённые из кода
без изменения формулировок. Следующие блоки: кнопки/экраны персонажа,
content/rules.md."""

# ENEMY_NAMES — грамматические формы имени противника для боевых текстов.
# Мышь — существительное женского рода: формы глаголов/прилагательных,
# относящихся к противнику, согласуются с ним (docs/notes.md).
ENEMY_NAMES = {
    "mouse": {
        "nom_cap": "Мышь", "nom_low": "мышь",
        "acc_cap": "Мышь", "acc_low": "мышь",
        "gen_low": "мыши",
        "ins_cap": "Мышью",
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
    "boss": {
        "nom_cap": "Лесной Король", "nom_low": "лесной король",
        "acc_cap": "Лесного Короля", "acc_low": "лесного короля",
        "gen_low": "лесного короля",
        "ins_cap": "Лесным Королём",
        "dodge_verb": "увернулся",
        "alive_adj": "живым",
        # Никогда не рендерится по-настоящему — can_flee=false в
        # content/enemies.json (docs/notes.md, п.36) гарантирует, что бросок
        # на побег для боевой стороны "enemy" не происходит вообще, но поле
        # держим ради целостности словаря (та же форма, что и у остальных).
        "fled_verb": "сбежал",
    },
}

# Дублирует bot/handlers/character.py::LOOT_ITEM_NAMES_RU (docs/notes.md,
# п.30/31) — бот и api не делят импорты (разные процессы, общаются только
# по HTTP), а показ добычи в конце боя рендерится здесь же, где и весь
# остальной текст боя, поэтому своя копия. Синхронизировать вручную при
# добавлении новых предметов в core/economy.py::LOOT_TABLE.
LOOT_ITEM_NAMES = {
    "mouse_pelt": "Мышиная шкурка",
    "mouse_tail": "Мышиный хвост",
    "wolf_fang": "Клык волка",
    "wolf_pelt": "Шкура волка",
    "boar_tusk": "Клык кабана",
    "boar_hide": "Шкура кабана",
}

TRANSLATIONS: dict[str, str] = {
    "encounter.found": "🎲 Бросок: {roll} → {name_nom_cap}!\n\nТы наткнулся на {name_acc_low}.",
    "encounter.boss": "👑 Ты входишь в чертог {name_acc_cap}. Отступать некуда — он уже смотрит на тебя.",

    "combat.initiative.player_first": "🎲 Инициатива: ты — {player_roll}, {name_nom_low} — {enemy_roll}. Ты ходишь первым!",
    "combat.initiative.enemy_first": "🎲 Инициатива: {name_nom_low} — {enemy_roll}, ты — {player_roll}. {name_nom_cap} атакует первым!",

    "combat.circumstance.none": "🎲 Обстоятельство: {roll} → без происшествий.",
    "combat.circumstance.buff_player": "🎲 Обстоятельство: {roll} → ⚡ Прилив адреналина!\nТвоя Сила увеличена на этот бой (×1.2)",
    "combat.circumstance.buff_enemy": "🎲 Обстоятельство: {roll} → ⚡ Прилив адреналина!\nСила {name_gen_low} увеличена на этот бой (×1.2)",
    "combat.circumstance.debuff_player": "🎲 Обстоятельство: {roll} → ⚡ Скользкая земля\nТвоя Сила уменьшена на этот бой (×0.8)",
    "combat.circumstance.debuff_enemy": "🎲 Обстоятельство: {roll} → ⚡ Скользкая земля\nСила {name_gen_low} уменьшена на этот бой (×0.8)",

    "combat.double_strike.player_triggered": "🎲 Твоя проверка удачи: {luck_roll} → ✨ УДАЧА! Двойной удар!",
    "combat.double_strike.player_missed": "🎲 Твоя проверка удачи: {luck_roll} → двойного удара нет.",
    "combat.double_strike.enemy_triggered": "🎲 {name_nom_cap} проверяет удачу: {luck_roll} → ✨ УДАЧА! Двойной удар!",
    "combat.double_strike.enemy_missed": "🎲 {name_nom_cap} проверяет удачу: {luck_roll} → двойного удара нет.",

    "combat.strike.power_label": "💥 Мощный удар",
    "combat.strike.damage_percent_power": "{percent}% силы, урон ×{multiplier}!",
    "combat.strike.damage_percent": "{percent}% силы.",
    "combat.strike.player_attack_label": "🗡️ Твоя атака",
    "combat.strike.enemy_attack_label": "🗡️ Атака {name_gen_low}",
    "combat.strike.enemy_dodge_label": "{name_nom_cap} уворачивается",
    "combat.strike.player_dodge_label": "Твой уворот",
    "combat.strike.player_damage_verb": "Ты наносишь",
    "combat.strike.enemy_damage_verb": "{name_nom_cap} наносит",
    "combat.strike.player_dodge_verb": "увернулся",
    "combat.strike.miss": "{attack_label}: {attack_roll} → промах!",
    "combat.strike.header": "{attack_label}: {attack_roll} → {percent_part}",
    "combat.strike.dodge_success": "🛡️ {dodge_label}: {dodge_roll} → {dodge_verb}!",
    "combat.strike.damage_avoided": "✅ Урон полностью пропущен.",
    "combat.strike.dodge_fail": "🛡️ {dodge_label}: {dodge_roll} → не вышло!",
    "combat.strike.damage_dealt": "💥 {damage_verb} {damage} урона.",

    "combat.compact_strike.attack_label": "🗡️ Удар",
    "combat.compact_strike.player_dodge_label": "Ты уворачиваешься",
    "combat.compact_strike.miss": "{strike_label} {strike_number}: {attack_roll} → промах.",
    "combat.compact_strike.header": "{strike_label} {strike_number}: {attack_roll} → {percent_part}",
    "combat.compact_strike.damage": "💥 {damage} урона.",

    "combat.potion.large_label": "Большое",
    "combat.potion.small_label": "Малое",
    "combat.potion.used": "🧪 {label} зелье: +{heal} HP.",

    "combat.hp_status": "❤️ Ты: {player_hp}/{player_hp_max}   👹 {name_nom_cap}: {enemy_hp}/{enemy_hp_max}",

    "combat.flee_check.player_hp_label": "Твоё HP критически низкое",
    "combat.flee_check.player_prefix": "Твоя проверка удачи на побег",
    "combat.flee_check.player_alive_adj": "живым",
    "combat.flee_check.enemy_hp_label": "HP {name_gen_low} критически низкое",
    "combat.flee_check.enemy_prefix": "{name_nom_cap} проверяет удачу на побег",
    "combat.flee_check.triggered": "⚠️ {hp_label}! ({current_hp}/{max_hp})\n🍀 {prefix}: {luck_roll} → есть шанс уйти {alive_adj}!",
    "combat.flee_check.not_triggered": "🍀 {prefix}: {luck_roll} → шанса уйти нет в этот раз.",

    "combat.flee_attempt.player_miss": (
        "🏃 Ты пытаешься сбежать — {name_nom_low} бьёт без ответа!\n"
        "🎲 Атака {name_gen_low}: {attack_roll} → промах!\n"
        "✅ Тебе удаётся уйти чисто."
    ),
    "combat.flee_attempt.player_caught": (
        "🏃 Ты пытаешься сбежать — {name_nom_low} бьёт без ответа!\n"
        "🎲 Атака {name_gen_low}: {attack_roll} → {attack_percent}% силы.\n"
        "💀 Удар настигает тебя ({damage} урона)."
    ),
    "combat.flee_attempt.player_survives": (
        "🏃 Ты пытаешься сбежать — {name_nom_low} бьёт без ответа!\n"
        "🎲 Атака {name_gen_low}: {attack_roll} → {attack_percent}% силы.\n"
        "💥 {damage} урона вдогонку, но ты вырываешься."
    ),
    "combat.flee_attempt.enemy_miss": (
        "🏃 {name_nom_cap} пытается сбежать — твой удар без ответа!\n"
        "🎲 Твоя атака: {attack_roll} → промах!\n"
        "{name_nom_cap} убегает."
    ),
    "combat.flee_attempt.enemy_caught": (
        "🏃 {name_nom_cap} пытается сбежать — твой удар без ответа!\n"
        "🎲 Твоя атака: {attack_roll} → {attack_percent}% силы.\n"
        "💀 Добиваешь {name_acc_low} на бегу ({damage} урона)."
    ),
    "combat.flee_attempt.enemy_survives": (
        "🏃 {name_nom_cap} пытается сбежать — твой удар без ответа!\n"
        "🎲 Твоя атака: {attack_roll} → {attack_percent}% силы.\n"
        "💥 {damage} урона, но {name_nom_low} вырывается."
    ),

    "combat.battle_end.victory_header": "⚔️ Бой окончен! Ты победил {name_acc_cap}.",
    "combat.battle_end.reward_line": "🏆 +{reward} победных очков (всего: {victory_points_total})",
    "combat.battle_end.defeat_header": "💀 Ты пал в бою с {name_ins_cap}...",
    "combat.battle_end.player_fled_header": "🏃 Тебе удалось уйти от боя с {name_ins_cap}.",
    "combat.battle_end.enemy_fled_header": "🏃 {name_nom_cap} {fled_verb}, добить не удалось.",
    "combat.battle_end.loot_line": "🎁 Добыча: {loot_name}",
    "combat.battle_end.no_loot_line": "😕 Упс, не повезло с добычей...",
    "combat.battle_end.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "combat.battle_end.regen_line": "⏳ Полное восстановление через: ~{hp_seconds_to_full} сек.",

    "combat.boss_victory": "🎉 Ты повергнул {name_acc_cap}!\n\nПриключение окончено. Спасибо, что играл(а)!",

    # --- Экран персонажа (bot/handlers/character.py, docs/notes.md, блок 3) ---
    "character.menu_title": "👤 Меню игрока",
    "character.creation_title": "🧙 Создание героя",
    "character.button.refresh": "🔄 Обновить",
    "character.button.search_encounter": "🔍 Искать противника",
    "character.button.rules": "📜 Правила",
    "character.button.boss": "⚔️ Финальный босс",
    "character.button.back": "⬅️ Назад",
    "character.button.reset": "🗑 Обнулить персонажа",
    "character.button.sell_loot": "💰 Продать весь лут",
    "character.button.start_adventure": "✅ Начать приключение",
    "character.allocate_button": "+1 {name}",

    "character.stat.strength": "Сила",
    "character.stat.agility": "Ловкость",
    "character.stat.luck": "Удача",
    "character.stat.vitality": "Здоровье",
    "character.stat_line": "{emoji} {name}: {value}",
    "character.vitality_line": "❤️ {name}: {value}  (HP max: {hp_max})",

    "character.level_line": "🏅 Уровень: {level}",
    "character.hp_line": "❤️ HP: {hp_current}/{hp_max}",
    "character.victory_points_line": "🏆 Победные очки: {victory_points} (до след. уровня: {points_to_next_level})",
    "character.unspent_points_line": "Осталось очков: {unspent_stat_points}",
    "character.unspent_points_available_line": "Доступно очков прокачки: {unspent_stat_points}",
    "character.gold_line": "💰 Золото: {gold}",

    "character.loot_line": "📦 Лут: {items}",
    "character.loot_empty": "📦 Лут: пока нет",
    "character.potions_line": "🧪 Зелья: {items}",
    "character.potions_empty": "🧪 Зелья: пока нет",
    "character.loot_item_single": "{name} ({price} зол.)",
    "character.loot_item_multiple": "{name} ×{count} ({total_price} зол.)",
    "character.potion_count": "{name} ×{count}",

    "character.potion_cap_reached": "уже максимум",
    "character.potion_price": "{price} зол.",
    "character.buy_potion_button": "🧪 Купить {name} ({status})",

    "character.buy_error.not_enough_gold": "Не хватает золота.",
    "character.buy_error.cap_reached": "Уже максимум зелий этого размера.",
    "character.buy_error.generic": "Не удалось купить зелье.",
    "character.allocate_error.no_points": "Не осталось свободных очков",

    # --- Боевой UI бота (bot/handlers/combat.py, docs/notes.md, блок 4) ---
    # Кнопки/алерты вокруг боя — в отличие от combat.* из блока 2 (боевой
    # лог, рендерится на api/, боевой ход), это клиентская обвязка бота:
    # выбор действия, флоу босса, эдж-кейсы. "💥 Мощный удар"/"Малое"/
    # "Большое" здесь переиспользуют combat.strike.power_label/combat.
    # potion.*_label из блока 2 — не дублируются отдельным переводом.
    "combat.ui.button.attack": "🎲 Атаковать",
    "combat.ui.button.defend": "🛡️ Защищаться",
    "combat.ui.button.flee": "🏃 Сбежать",
    "combat.ui.button.continue_fight": "⚔️ Биться дальше",
    "combat.ui.button.restart": "🔄 Начать заново",
    "combat.ui.button.determine_initiative": "⚔️ Определить инициативу",
    "combat.ui.button.boss_challenge": "⚔️ Бросить вызов (с {level} уровня)",
    "combat.ui.button.boss_challenge_confirm": "⚔️ Да, вступить в бой",
    "combat.ui.button.enter_battle": "⚔️ Вступить в бой",
    "combat.ui.button.retreat": "🏃 Отступить",
    "combat.ui.button.autobattle": "⚡ Автобой",
    "combat.ui.potion_stock": "🧪 Твой запас:\n  {small_label}: {potions_small}/{small_cap}\n  {large_label}: {potions_large}/{large_cap}",

    "combat.ui.error.already_in_battle": "У тебя уже есть незавершённый бой — сначала заверши его.",
    "combat.ui.error.cant_cancel_started": "Бой уже начался — отменить нельзя.",
    "combat.ui.error.boss_unavailable": "Финальный босс пока недоступен на этом уровне.",
    "combat.ui.warning.boss_no_retreat": "⚠️ После этого отступить будет нельзя.",
    "combat.ui.error.cant_flee": "Из боя с этим противником нельзя отступить.",
    "combat.ui.error.potion_already_used": "Зелье в этом бою уже использовано.",
    "combat.ui.error.potion_not_owned": "У тебя нет такого зелья.",
    "combat.ui.error.potion_generic": "Сейчас нельзя использовать зелье.",

    # --- /language (bot/handlers/language.py, блок 4) ---
    # LANGUAGE_PROMPT_TEXT и подписи "Русский"/"English" сознательно не
    # переведены через t() — показываются до выбора языка, см. докстринг
    # модуля.
    "language.confirmation": "✅ Язык переключён на русский.",

    # --- /start, /reset (bot/handlers/start.py + bot/utils.py, блок 4) ---
    "start.welcome": (
        "🧙 Добро пожаловать в текстовую RPG!\n\n"
        "Ищи противников, сражайся на кубиках, качай персонажа. "
        "Финальная цель — набраться сил и одолеть финального босса.\n\n"
        "🌐 /language — сменить язык / switch language"
    ),
    "start.button.start_game": "✅ Начать игру",
    "start.resume_prefix": "↩️ Продолжаем начатый бой:\n\n",
    "start.reset_confirm": (
        "⚠️ Точно обнулить персонажа?\n\n"
        "Статы, уровень и весь прогресс будут удалены безвозвратно — отменить это будет нельзя."
    ),
    "start.button.reset_yes": "🗑 Да, удалить",
    "start.button.cancel": "Отмена",
    "start.reset_done": "Персонаж обнулён",

    # --- /rules (bot/handlers/character.py + bot/rules_content.py, блок 5) ---
    # Сам текст правил — content/rules.md/rules.en.md, отдельные файлы, не
    # TRANSLATIONS (см. докстринг bot/rules_content.py) — здесь только
    # обвязка меню разделов.
    "rules.menu_header": "📖 <b>{title}</b>\n\nВыбери раздел:",
    "rules.button.back_to_sections": "⬅️ К списку разделов",
}
