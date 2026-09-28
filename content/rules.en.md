# Game Rules

## 1. Introduction

This is a text-based turn-based RPG. You search for enemies, fight them turn by turn — roll by roll — and earn victory points for winning, which unlock new levels and stat points to spend. Every action you take in battle is a real dice roll whose number you see right away, not a pre-packaged summary of the outcome.

## 2. Stats

| Stat | What it does |
|---|---|
| ❤️ HP | Hit points. Decrease when you take damage. 0 — defeat. Regenerate on their own over time — no need to wait deliberately. |
| 💛 Vitality | Determines max HP: `HP_max = 20 + Vitality × 10`. Doesn't affect regen speed. Current HP isn't recalculated on level-up — only the max grows, so the HP bar's fill percentage can temporarily drop. |
| 💪 Strength | Determines your strike power. The only fully predictable stat — you get out exactly what you put in. |
| 🤸 Agility | Chance to fully dodge a hit. |
| 🍀 Luck | Chance for a double strike per turn, and the chance to flee when HP is critically low. |

### Strength — what an attack roll means

An attack is a d10 roll (a die from 1 to 10). The result determines what percentage of your Strength turns into damage:

| Roll | Result |
|---|---|
| 1–2 | Miss. 0 damage. The defender doesn't even roll to dodge — there was nothing to dodge. |
| 3–5 | Fixed 50% of Strength. |
| 6–10 | Grows linearly from 60% to 100% of Strength (face 6 → 60%, face 10 → 100%). |

`Damage = Strength × percent ÷ 100`, rounded to a whole number — there's never fractional HP or fractional damage in this game.

### Power attack — risk for damage

On any of your attack turns, instead of a normal attack, you can choose 💥 Power attack — the same d10, but different faces and a different outcome:

| Roll | Result |
|---|---|
| 1–4 | Miss. 0 damage (a wider miss range than a normal attack — 4 faces instead of 2). The defender doesn't even roll to dodge. |
| 5 | Fixed 50% of Strength. |
| 6–10 | Grows linearly from 60% to 100% of Strength — the same scale as a normal attack. |

If the strike doesn't miss, the resulting damage is multiplied by **×1.5**. The choice is unrestricted — available on any turn of manual combat, in any fight, as many times in a row as you like; the only cost is a higher miss chance (40% versus 20% for a normal attack). If a double strike also triggers this turn (see below), the "normal/power" choice applies to both strikes — it isn't asked separately for the second one. Enemies never use this — they always attack normally. In "⚡ Auto-battle" (see §5) there's no choice at all — every turn there is a normal attack, no power attack and no potions.

## 3. Agility and Luck — how the odds work

### Agility — what a dodge roll means

If the attack wasn't a miss, the defender rolls their own d10 to dodge. The outcome is always binary: either you dodge completely and take zero damage, or you take the hit in full — there's no partial damage reduction.

Mechanic: every roll has some number of "successful" faces out of ten (for example, "1 through 4 — dodge") — the higher your Agility, the more such faces. Growth isn't linear: the first few Agility points raise the chance noticeably, and each further point adds progressively less — the curve approaches an almost-guaranteed dodge but never reaches 100%, no matter how much you invest. There's a floor too: even with zero points in Agility, at least one successful face always remains — a small but non-zero "miracle dodge" chance.

### Luck — what a double strike roll means

At the start of your turn (before the attack itself), a separate d10 is rolled for luck. If it lands in the "successful" zone, you (or the enemy, on their turn) strike **twice in a row** this turn — each strike is a full, separate attack-and-defense roll. If not, you strike once as usual. If the first of the two strikes already finishes off the opponent, the second one isn't dealt — the battle ends immediately.

Same successful-faces logic as dodge above: the higher your Luck, the more faces count, with the same slowing growth and the same "almost, but not 100%" ceiling. The difference from dodge — here there is **no** guaranteed minimum: at very low Luck (especially at the start, with nothing invested), a double strike may almost never trigger.

### Luck — what a flee-at-low-HP roll means

If your HP (or the enemy's HP) drops to 25% of max or below, at the start of that side's turn one more, separate d10 is rolled for luck — specifically for the chance to flee (see §6 for the flee mechanic itself). It works similarly to dodge (the same slowing growth, the same guaranteed minimum chance even with zero Luck invested), but with its own, noticeably lower ceiling — even with very high Luck, this check triggers considerably less often than a double strike. Fleeing is a rare shot at survival, not an equally-weighted third ability.

## 4. Enemies

| Enemy | HP | Strength | Agility | Luck | Reward |
|---|---|---|---|---|---|
| 🐭 Mouse | 20 | 5 | 2 | 1 | 1 victory point |
| 🐺 Wolf | 50 | 12 | 6 | 2 | 5 victory points |
| 🐗 Boar | 70 | 11 | 6 | 2 | 15 victory points |

The reward is granted **only on victory**. Defeat and fleeing don't roll back progress — victory points you already have stay right where they are.

## 5. Starting a battle

### Searching for an enemy

A d10 roll determines who you run into. The game automatically adjusts the encounter balance as your character grows — early on you'll more often run into the easy mouse, and later, as you level up, it increasingly shifts toward the more dangerous boar. There's nothing to configure or track yourself — the difficulty rises naturally, along with you.

### Initiative

Both sides roll a d10. Whoever rolls higher goes first for the whole battle. On a tie, both dice are rerolled.

### Circumstance

The side that won initiative immediately rolls one more d10 — for a favorable or unfavorable circumstance for itself:

| Roll | What it means |
|---|---|
| 1–3 | Debuff: the roller's Strength ×0.8 for the whole battle. |
| 4–7 | Nothing happens, nothing changes. |
| 8–10 | Buff: the roller's Strength ×1.2 for the whole battle. |

Important: the effect applies **to whoever rolled the die**, not always to the player. If the enemy won initiative and got unlucky, the debuff goes to them, not to you.

### Decision: fight or retreat

No matter how the circumstance roll turned out (even if it favors you or nothing happened at all), you always have a choice — enter the fight or retreat right away, before the first turn. The reason is simple: who you happened to run into (a mouse or a boar) is already reason enough to decide for yourself.

If you choose to retreat, the flee mechanic kicks in (see §6): one unanswered hit from the enemy, with no defense on your part at all. There's no reward either way — not for retreating, and not for what you'd have gotten by staying.

There's another option too — "⚡ Auto-battle": the fight plays out entirely on its own, with no clicks from you, and you see the finished result. It's chosen fresh for each fight — you could, say, take auto-battle against an easy mouse and fight a boar manually. Auto-battle has a cost: you can't use a potion during it (see §7 on potions) — the whole fight runs blind, on whatever you'd already stocked up by the time it starts.

## 6. Turn cycle and fleeing

### Turn cycle

From here, turns alternate, starting with whoever won initiative. On each attacking side's turn:

1. **Flee-check** (only if the attacking side's HP is ≤ 25% of max and this check hasn't already happened this battle — see "Fleeing at low HP" below).
2. **Double-strike check** (Luck) — see §3. If it triggers, what follows isn't one strike but two in a row.
3. **Strike(s) — only on your own attack turn, you choose:** a normal attack, 💥 a power attack (see §2), or, instead of any strike, a 🧪 potion (see §7 "Economy") — a potion replaces the strike entirely and immediately passes the turn on. If you strike — attack roll (Strength) → if not a miss, the defender's dodge roll (Agility) → damage, if the dodge fails.
4. If the defender's HP drops to 0, the battle is over.
5. Otherwise the turn passes to the other side, and everything repeats from step 1 for them.

### Fleeing at low HP

When the attacking side's HP drops to 25% of max or below, that side gets **exactly one attempt for the whole battle** to check its chance to flee — no more, regardless of whether the roll succeeds or not:

- **Failed** — the attempt is used up. There won't be another such check for this side in this battle, even if HP stays low until the very end — the fight just continues as normal.
- **Succeeded** — a choice opens up: flee now or keep fighting. If you decline to keep fighting (i.e. choose to stay), that's it — the attempt is also burned for good, there won't be a second chance in this battle.
- Against the bot, this check works the same way, except the game makes the choice for it: if the enemy gets the chance to flee, it **always** chooses to flee.

### The flee mechanic — shared between retreating at the start and fleeing on low HP

Both declining the fight right at the start of an encounter (see §5) and fleeing on low HP are resolved the same way — it isn't a free exit, it's a gamble:

> An escape attempt = one unanswered hit from the pursuing side, with **no defense at all** from the one fleeing — no dodge roll happens.
> - If this hit finishes off the fleeing side — it counts as a regular defeat (or a victory, if it was the enemy fleeing).
> - If the fleeing side survives — the battle ends, no winner is determined, and there's **no reward either way**.

In other words, you might get away clean, or you might catch a lethal blow to the back — that's the price of retreating.

## 7. Economy: gold, loot and potions

### Loot — what drops after a victory

After every victory (not after fleeing and not after a defeat), a trophy is determined right away, automatically, with no roll on your part — either one specific item or nothing:

- 🐭 **Mouse:** 45% — mouse pelt (2 gold), 15% — mouse tail (5 gold), 40% — nothing.
- 🐺 **Wolf:** 45% — wolf fang (8 gold), 15% — wolf pelt (20 gold), 40% — nothing.
- 🐗 **Boar:** 45% — boar tusk (20 gold), 15% — boar hide (50 gold), 40% — nothing.

All trophies pile up in your inventory (in "👤 Player Menu") — you can keep hunting and sell them all at once later, not necessarily right after every fight.

### Selling loot

In "👤 Player Menu", the "💰 Sell all loot" button sells **your entire** accumulated trophy inventory in one click, at the prices above — there's no partial sale (item by item). Gold is credited immediately, and the trophy inventory is cleared. The sale can't be undone.

### Potions — buying

In the same place, "👤 Player Menu", you can spend gold on healing potions:

| Potion | Restores | Price | Max in stock |
|---|---|---|---|
| 🧪 Small | 25% of max HP | 8 gold | 5 |
| 🧪 Large | 50% of max HP | 50 gold | 3 |

Buying is one potion per click. If you don't have enough gold, or you're already at the max stock, the buy button stays put but won't let you buy — its label will tell you why.

### Potions — using them in battle

A potion is drunk **only on your own attack turn**, instead of a normal strike — it's not a free bonus alongside your attack, it replaces it: you can't drink a potion and land a hit in the same turn. After using it, the turn passes to the enemy right away, just like after a normal strike.

The limit is **one potion per battle**, shared across both sizes (not "one small + one large") — use any potion once, and for the rest of that battle the potion buttons disappear, no matter how much is still left in stock. The button only appears for a size you actually have — if you have no small potions but two large ones, only the large button will show.

## 8. Leveling up

Victory points accumulate forever — your level is determined by their total count, and the points themselves are never spent. Each new level grants 2 stat points, which you distribute yourself among your stats (Strength / Agility / Luck / Vitality), one point per click.

| Level | Total points | Stat points |
|---|---|---|
| 1 | 0 | — (starting set) |
| 2 | 8 | 2 |
| 3 | 20 | 2 |
| 4 | 36 | 2 |
| 5 | 56 | 2 |
| 6 | 80 | 2 |
| 7 | 108 | 2 |
| 8 | 140 | 2 |
| 9 | 176 | 2 |
| 10 | 216 | 2 |

The further you go, the more points you need for the next level — growth is uneven, each subsequent level requires more than the last.
