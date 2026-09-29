# Game Rules

## 1. Introduction

This is a turn-based, text-based RPG. You search for enemies in an area and fight them turn by turn, roll by roll. Defeating enemies earns Victory Points, which unlock new levels and stat upgrade points. Every action you take in combat involves an actual dice roll whose result you see immediately — not a pre-written summary of what happened.

## 2. Stats

| Stat | What it does |
|---|---|
| ❤️ HP | Hit Points. Decrease when you take damage. At 0, you are defeated. HP regenerates automatically over time; there's no need to wait or rest manually. |
| 💛 Vitality | Determines your maximum HP: `HP_max = 20 + Vitality × 10`. It does not affect HP regeneration speed. Your current HP is not recalculated when you upgrade Vitality — only your maximum increases, so your HP bar may temporarily appear less full. |
| 💪 Strength | Determines how hard you hit. The only fully predictable stat: every point you invest gives you exactly that much Strength. |
| 🤸 Agility | Your chance to dodge an attack completely. |
| 🍀 Luck | Your chance to land a double strike in a turn and to escape when your HP is critically low. |

### Strength — What an Attack Roll Means

An attack is a d10 roll (a die with faces numbered 1 to 10). The result determines what percentage of your Strength is dealt as damage:

| Roll | Result |
|---|---|
| 1–2 | Miss. 0 damage. The enemy does not roll to dodge — there is nothing to dodge. |
| 3–5 | A fixed 50% of Strength. |
| 6–10 | Scales linearly from 60% to 100% of Strength (6 → 60%, 10 → 100%). |

`Damage = Strength × percentage ÷ 100`. The result is rounded to the nearest whole number — HP and damage are never fractional.

### Powerful Strike — Risk for More Damage

On each of your attack turns, you can choose 💥 Powerful Strike instead of a normal attack. It uses the same d10, but with different outcomes:

| Roll | Result |
|---|---|
| 1–4 | Miss. 0 damage (a wider miss range than a normal attack: 4 faces instead of 2). The enemy does not roll to dodge. |
| 5 | A fixed 50% of Strength. |
| 6–10 | Scales linearly from 60% to 100% of Strength — the same scale as a normal attack. |

If the strike hits, final damage is multiplied by **×1.5**. There are no restrictions: you can use it on any turn in manual combat, in any battle, as many turns in a row as you like. Its only cost is the increased chance to miss (40% versus 20% for a normal attack). If a double strike triggers on the same turn (see below), your choice of normal or powerful attack applies to both strikes; you are not asked again for the second strike. Enemies never use Powerful Strike — they always make normal attacks. In ⚡ Auto-Battle (see §5), there is no choice: every turn uses a normal attack, with no Powerful Strike or potions.

## 3. Agility and Luck — How Chances Are Calculated

### Agility — What a Dodge Roll Means

If an attack is not a miss, the defender rolls a d10 to dodge. The outcome is always binary: either you dodge completely and take no damage, or the attack hits in full. There is no partial damage reduction.

Mechanics: each roll has a certain number of successful faces out of ten (for example, “a roll of 1–4 means a dodge”). The more Agility you have, the more successful faces there are. Growth is nonlinear: the first points of Agility noticeably increase your chance, while each additional point adds less. The curve approaches an almost guaranteed dodge but never reaches 100%, no matter how much you invest. The reverse guarantee also applies: even with zero Agility, at least one face is always successful — a small but nonzero chance for a “miracle dodge.”

### Luck — What a Double-Strike Roll Means

At the start of your turn, before the attack itself, you make a separate d10 Luck roll. If it lands in the successful range, you (or the enemy, on its turn) strike **twice in a row** during that turn. Each strike has its own full attack and defense rolls. Otherwise, you strike once as normal. If the first of the two strikes defeats the enemy, the second strike is skipped and the battle ends immediately.

The successful-face system works the same way as dodging: more Luck means more successful faces, with diminishing returns and a ceiling of “almost, but not quite, 100%.” Unlike dodging, **there is no guaranteed minimum** here: with very low Luck (especially at the start, before investing any points), a double strike may almost never trigger.

### Luck — What an Escape Roll at Low HP Means

If your HP (or the enemy's HP) falls to 25% of its maximum or below, that side makes another separate d10 Luck roll at the start of its turn to check whether it can flee (see §6 for the escape mechanics). It works similarly to dodging, with diminishing returns and a guaranteed minimum chance even with no Luck investment, but has a distinctly lower ceiling. Even with very high Luck, this check triggers noticeably less often than a double strike. Escaping is a rare chance to survive, not an equally powerful third ability.

## 4. Enemies

| Enemy | HP | Strength | Agility | Luck | Reward |
|---|---:|---:|---:|---:|---|
| 🐭 Mouse | 20 | 5 | 2 | 1 | 1 Victory Point |
| 🐺 Wolf | 50 | 12 | 6 | 2 | 5 Victory Points |
| 🐗 Boar | 70 | 11 | 6 | 2 | 15 Victory Points |

Rewards are granted **only for victory**. Defeat and escape do not roll back progress — any Victory Points you've already earned are yours to keep.

## 5. Starting a Battle

### Finding an Enemy

A d10 roll determines which enemy you encounter. The game adjusts encounter balance as your character grows: early on, you're more likely to encounter an easy Mouse; as you level up, encounters shift increasingly toward the more dangerous Boar. There's nothing you need to configure or track — difficulty naturally increases as you grow stronger.

### Initiative

Both sides roll a d10. The higher roll goes first for the entire battle. If the rolls are tied, both dice are rolled again.

### Encounter Event

The side that wins initiative immediately rolls another d10 to determine whether a favorable or unfavorable event affects it:

| Roll | Effect |
|---|---|
| 1–3 | Debuff: the roller's Strength is multiplied by ×0.8 for the entire battle. |
| 4–7 | No event; nothing changes. |
| 8–10 | Buff: the roller's Strength is multiplied by ×1.2 for the entire battle. |

Important: the effect applies to **the side that rolled**, not always the player. If the enemy wins initiative and gets an unfavorable result, the enemy receives the debuff, not you.

### Decide: Fight or Retreat

Regardless of the event result (even if it benefits you, or nothing happens), you can always choose to enter the fight or retreat immediately, before the first turn. The reason is simple: the enemy you encounter — Mouse or Boar — may be reason enough to make your own decision.

If you retreat, the escape mechanic applies (see §6): the enemy gets one unopposed attack, and you do not get to roll a dodge. You receive no reward either way — not for retreating, and not for staying and fighting.

There's another option: ⚡ Auto-Battle. The entire fight is resolved immediately without any button presses, and you see the final result. You choose it separately for each battle — for example, you can auto-battle an easy Mouse and fight a Boar manually. Auto-Battle has a cost: you cannot use a potion during it (see §7) — the entire fight plays out automatically using only what you have when it begins.

## 6. Turn Cycle and Escape

### Turn Cycle

Turns alternate, starting with the side that won initiative. On each attacking side's turn:

1. **Check for an escape opportunity** (only if the attacking side's HP is ≤ 25% of its maximum and it has not made this check yet in the current battle — see “Escape at Low HP” below).
2. **Check for a double strike** (Luck) — see §3. If it triggers, the side makes two consecutive strikes instead of one.
3. **Strike(s) — on your attack turn only, you choose:** a normal attack, 💥 Powerful Strike (see §2), or 🧪 a potion instead of any strike (see §7, “Economy”). A potion replaces the entire attack and immediately passes the turn to the other side. If you attack: attack roll (Strength) → if it isn't a miss, the defender rolls to dodge (Agility) → damage is dealt if the dodge fails.
4. If the defender's HP reaches 0, the battle ends.
5. Otherwise, the turn passes to the other side, and the cycle repeats from step 1 for them.

### Escape at Low HP

When an attacking side's HP falls to 25% of its maximum or below, it gets **exactly one chance per battle** to roll for escape — no more, regardless of whether the roll succeeds:

- **If it fails:** the attempt is spent. That side cannot make another escape check in this battle, even if its HP stays low until the end. The battle continues as normal.
- **If it succeeds:** the side can choose to flee or keep fighting. If it declines to flee (chooses to stay), the attempt is permanently spent; there is no second chance in this battle.
- The same check applies to enemies, but the game makes the choice for them: if an enemy gets the chance to flee, it **always** chooses to run.

### Escape Mechanics — Shared by Early Retreat and Low-HP Escape

Both declining a fight at the start of an encounter (see §5) and escaping at low HP use the same mechanic. Escape is not free — it comes with a risk:

> Attempting to escape means taking one unopposed hit from the pursuing side, **with no defense** — the fleeing side does not roll to dodge.
> - If the hit defeats the fleeing side, it counts as a normal defeat (or victory, if the enemy was fleeing).
> - If the fleeing side survives, the battle ends with no winner, and **no reward is granted**.

You might get away cleanly, or take a fatal hit in the back — that's the price of retreat.

## 7. Economy: Gold, Loot, and Potions

### Loot — Drops After Victory

After every victory (not after escape or defeat), loot is determined automatically, without a separate roll from you: either one specific item drops, or nothing:

- 🐭 **Mouse:** 45% — Mouse Pelt (2 gold); 15% — Mouse Tail (5 gold); 40% — nothing.
- 🐺 **Wolf:** 45% — Wolf Fang (8 gold); 15% — Wolf Pelt (20 gold); 40% — nothing.
- 🐗 **Boar:** 45% — Boar Tusk (20 gold); 15% — Boar Hide (50 gold); 40% — nothing.

All loot accumulates in your inventory (in the 👤 Player Menu). You can keep hunting and sell everything at once later; you don't have to sell after every battle.

### Selling Loot

The 👤 Player Menu's 💰 Sell All Loot button sells **all** accumulated loot in one click at the prices listed above. You cannot sell items individually. Gold is added immediately, and the loot inventory is emptied. The sale cannot be undone.

### Potions — Purchasing

You can also spend gold in the 👤 Player Menu on healing potions:

| Potion | Restores | Price | Maximum stock |
|---|---|---:|---:|
| 🧪 Small | 25% of max HP | 8 gold | 5 |
| 🧪 Large | 50% of max HP | 50 gold | 3 |

Potions are purchased one at a time, with one click per potion. If you don't have enough gold or have already reached the stock limit, the purchase button remains visible but won't let you buy one; the message below it explains why.

### Potions — Using Them in Combat

You can use a potion **only on your attack turn**, instead of making a normal attack. It is not a free bonus action: using a potion replaces your attack, and you cannot drink a potion and attack on the same turn. After you use one, your turn passes to the enemy, just as it does after an attack.

The limit is **one potion per battle**, shared between both sizes (not “one Small + one Large”). Once you've used any potion, the potion buttons disappear for the rest of the battle, regardless of what you have left in stock. A button appears only for a potion size you actually have — if you have no Small Potions but have two Large Potions, only the Large Potion button is shown.

## 8. Leveling Up

Victory Points accumulate permanently. Your level is determined by your total Victory Points, which are never spent. Each new level grants 2 stat upgrade points, which you can distribute among Strength, Agility, Luck, and Vitality, one point per click.

| Level | Total Victory Points | Upgrade points |
|---:|---:|---:|
| 1 | 0 | — (starting stats) |
| 2 | 8 | 2 |
| 3 | 20 | 2 |
| 4 | 36 | 2 |
| 5 | 56 | 2 |
| 6 | 80 | 2 |
| 7 | 108 | 2 |
| 8 | 140 | 2 |
| 9 | 176 | 2 |
| 10 | 216 | 2 |

The higher your level, the more Victory Points you need for the next one. The increase is uneven, and each level requires more points than the previous one.
