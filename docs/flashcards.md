# Flashcards for song-study — experience design

## Context

The app helps you *read* a song: Sudachi tokenization, furigana, JMDict glosses, LRCLIB line
timings, YouTube playback. Nothing helps you *retain* what you read. This document designs the
study experience — what a card looks like, what it asks, how it sounds, and how it is scheduled.

**Schema and migrations are deliberately out of scope here.** The last section lists only what
data the experience needs and whether the app already has it. Nothing is settled until the
experience is.

Two premises the rest of the document rests on:

- **The app assumes perfect hiragana/katakana literacy.** So the deck tests meaning and grammar,
  not pronunciation.
- **Grading is objective on every card.** No card asks you to rate your own recall; every answer
  is checkable and every rating is computed.

---

## 1. Does FSRS know when a card is already well known?

**Yes — that is exactly what stability measures.** FSRS models memory as three numbers:

- **Stability (S)**, in days: how long until predicted recall decays to 90%. This *is* the
  "how well known" metric. Anki's convention calls a card **mature** at S ≥ 21 days; nothing
  stops you picking your own threshold for a "known" badge.
- **Retrievability (R)**, 0–1: predicted recall probability *right now*. `py-fsrs` exposes
  `scheduler.get_card_retrievability(card)`, so you can show "you'd probably recall this: 94%".
- **Difficulty (D)**, 1–10: how intrinsically hard this item is for you.

So the progress UI has real numbers behind it without inventing anything.

### But you still want an "I already know this" button

Stability is *derived from reviews*, so a word you already knew before the app ever showed it
starts at zero regardless. FSRS's in-flow answer is rating **Easy**, which on a brand-new card
sets initial stability to the `w[3]` parameter — about **8 days**. Useful, but not "don't bother
me for a season", which is what you're describing.

Recommend three distinct escapes, in increasing strength:

| Action | Effect | When |
|---|---|---|
| **Easy** (rating 4) | Normal FSRS path, ~8 days on a new card | "That was easy" — in-flow |
| **"I know this — push it out"** | Set due date 1 / 3 / 6 months out **and** rewrite stability to match the new interval | "I knew this word before I ever opened this app" |
| **Remove from my list** | Leave the queue entirely, **keep the row and its history** | "Stop asking me this" |

The middle one is Anki's *Set Due Date* with the `!` suffix, and it's the established pattern —
the `!` is what makes it also rewrite stability, so the card doesn't snap back to a short
interval on the next review. **Decided:** offer it as a 1 / 3 / 6 month preset ladder rather than
a date picker.

### Removal is reversible, and re-adding goes through the song

**Decided:** removal suspends the card, it never deletes it. You get the word back by finding it
in the lyrics again and re-adding it from the gloss popup — which restores the card's existing
stability rather than starting it over.

That matters more than it sounds: hard-deleting would throw away months of review history the
moment you mis-click, and re-adding would then restart the word from zero. Suspend-and-restore
costs nothing and is strictly safer.

It also settles where **manual enrollment** lives: the reading view's gloss popup grows an
"in your list ✓ / add" affordance. That pairs well with the per-song limit of 10 new cards a day
— auto-enroll paces you, and the reading view is the escape hatch for a word you specifically
want *now*. Same surface handles both first-time adds and restores, so there's one concept to
learn rather than two.

Worth noting the popup is already crowded and its positioning logic is delicate (the
`useLayoutEffect` edge-nudge that avoids the floating sidebar), so this is a real UI change, not
a free one.

**Important detail:** a manual push-out must be recorded as a *reschedule*, not as a review.
If it lands in the review log as a real rating, it poisons the data that the FSRS optimizer
would later use to fit your personal parameters.

Since enrollment is automatic, this button is load-bearing — auto-enroll will pull in plenty of
words you already know, and the push-out is how you clear them in one keystroke instead of
grinding them through learning steps. It carries even more weight given the objective-grading
decision in §3, which makes an Easy rating unreachable on the default card set: push-out becomes
the *only* fast path for a word you already know.

---

## 2. Settings

Two knobs, in one settings surface.

### Desired retention (default 0.90)

`desired_retention` is the one FSRS knob worth surfacing. It's the recall probability the
scheduler aims for at the moment a card comes up; everything else follows from it.

A terminology note, because these get conflated and the distinction matters downstream:
**retention is the setting you choose** (a target recall probability), while **stability is a
measured property of one card** (how many days until that card decays to 90% recall). You set
retention; FSRS reports stability back to you.

Proposed UI — a slider with live consequences, not a bare number:

| Setting | What it means | Effect on your day |
|---|---|---|
| **0.75** | You'll blank on about **1 in 4** cards when they appear | Longest intervals, lightest load. Fine for a big backlog you're grazing. |
| **0.85** | About **1 in 7** | Often near the sweet spot for total work per word retained. |
| **0.90** | About **1 in 10** — FSRS's default | Balanced. Start here. |
| **0.95** | About **1 in 20** | Roughly doubles your reviews versus 0.90 for a modest recall gain. |

Above 0.95 the review count climbs steeply for very little return; that ceiling is worth
enforcing in the slider rather than explaining after the fact. The range 0.80–0.90 is where most
people land. Later, `fsrs[optimizer]` can compute a personal answer via
`compute_optimal_retention()` from your own review history.

Changing it doesn't rewrite existing due dates — it takes effect at the next review of each card,
which is worth saying in the UI so the setting doesn't look broken.

### New cards per day (default 10, per song)

How many previously-unseen cards a song may introduce in a day. Sits in the same settings surface
as retention.

### Why one is global and the other is per song

**The new-card limit is per song; desired retention is global.** This isn't arbitrary — it falls
out of cards being global per word:

- The limit governs **enrollment**, which is inherently a per-song act. "Introduce 10 new words
  from this song today" is coherent, and it's the right unit given the music is the point.
- Retention governs **scheduling of a card that may appear in five songs at once**. If 君 is in
  three songs with three different retention targets, there is no answer to "when is it due."

So the settings panel shows a global retention slider plus the current song's new-card limit. A
per-song retention *override* would need cards to stop being shared, which costs you the main
benefit of the design — learning a word once, everywhere.

---

## 3. The card types

Every card is anchored to **a line of a song**, and the line plays. The prompt is the music; the
lyric text is the visual.

### Universal frame

```
┌──────────────────────────────────────────────────────┐
│  ♪  Song title                        ▸ replay (␣)   │
│                                                      │
│      ·· · ·· ·  聞こえてる  ···                        │
│      (dimmed)      ▲       (dimmed)                  │
│                                                      │
│      « the question for this card type »             │
│                                                      │
│      ⏎ reveal                                        │
└──────────────────────────────────────────────────────┘
```

The line auto-plays once on card entry; space replays it. **Decided:** the line is present but
**dimmed except the target**, brightening to full on reveal. That keeps the song context — the
whole reason to study this way — without letting the neighbouring words hand you the answer.
Glosses and furigana stay suppressed until reveal regardless; otherwise the card answers itself.

### Type A — Recognition (the backbone)

> The line plays, dimmed except one word. **Which of these is its meaning?**

```
PROMPT                                REVEAL
  ·· · ·· · 聞こえてる ···               君 の 声 が 聞こえてる んだ
     (dimmed)  ▲  (dimmed)             きこえる · to be audible, can hear
                                       dictionary form: 聞こえる
  1  to be audible, can hear   ←
  2  to call out, to shout
  3  to fall silent
  4  to echo, to resound
```

**Decided: pick the correct gloss from four English-only options.** The app assumes perfect
hiragana/katakana literacy, so what's worth testing is meaning, not pronunciation.

**Readings are omitted from the options.** This is the load-bearing detail. If each option
carried its own reading — `きこえる · to be audible` — you could match the prompt's 聞 to the
きこ and pick by pronunciation without knowing what the word means. English-only options force
the actual question. It also means the option list needs its own renderer rather than reusing
`SenseBlock`/`GlossDetails`, which both show the reading.

Reveal restores everything: the full line, the reading in furigana, the ranked senses, and the
dictionary form when the surface is conjugated (聞こえてる → 聞こえる). Prompting on the surface
as it appears in the song and revealing the dictionary form is the right way round — you meet
words in their sung form, not their citation form.

#### Distractor rules

The quality of this card is entirely the quality of its distractors. Four rules, all cheap with
data the app already has:

1. **Same Sudachi major POS as the target** — `part_of_speech[0]`. Otherwise "to be audible"
   against three nouns is answerable by shape alone.
2. **Drawn from the same song** where possible, falling back to the rest of the deck. Familiar
   words make weaker giveaways than exotic ones.
3. **Reject near-synonyms of the target.** Real risk of two defensible answers. Cheap guard:
   discard any candidate sharing a comma-separated gloss string, or a significant gloss word,
   with the target.
4. **Show the same number of senses on every option**, and prefer distractors whose sense count
   can match the target's. A conspicuously longer or shorter correct answer is a tell — and
   uniformity, not brevity, is what removes it.

#### How many senses per option

This is the direct mitigation for the polysemy risk in §4: the more senses the correct option
shows, the likelier it contains the one you actually know. But it multiplies by four.

The reading view's popup uses `SENSE_LIMIT = 5` with a "Show N more" expander
(`DocumentViewPage.tsx:42`), and each `GlossSense.gloss` is itself a `string[]` of phrasings. Five
senses across four options is ~60 phrases on a single card — unreadable on a phone.

**Decided: two senses per option, with all glosses inside each sense, identical across options.**
JMDict's first sense already bundles synonyms ("to be audible, can hear, can be heard"), which
absorbs most of the "I knew a different phrasing" risk on its own; a second sense covers the
common case where a word's real ambiguity is sense 1 versus sense 2.

```
  ·· · ·· · 聞こえてる ···

  1  to be audible, can hear, can be heard · to sound (like), to come across as   ←
  2  to call out, to shout, to yell · to be known as, to be famous
  3  to fall silent, to go quiet · to die down
  4  to echo, to resound, to reverberate · to be rumoured
```

Precisely: show `min(2, target_sense_count)` senses on **every** option, and prefer distractors
with at least that many senses so no option is visibly shorter. A one-sense target gets one-sense
distractors.

The reveal is unaffected — it reuses the existing `SenseBlock` at `SENSE_LIMIT = 5` with its
expander, so you still see the word's full range after answering. Worth a separate constant
(`OPTION_SENSE_LIMIT = 2`) declared next to `SENSE_LIMIT` so the relationship between the two
surfaces is visible rather than coincidental.

#### The prompt must not claim more than the card knows

**Decided: the question is "What are some of the meanings of this word?"** — not "what does it
mean here". The card genuinely cannot know which sense the line uses, and phrasing it as a
definite question makes the card lie. Show the count alongside the options (*"showing 2 of 8"*)
so incompleteness is visible rather than implied.

#### The 通り problem, and why automation can't solve it

A worked case that sets the limit of this design. JMDict has two entries:

| entry | reading | senses |
|---|---|---|
| 1432920 | とおり | 8 — ①avenue; street; way; road … ⑥**the same status or way; as (as expected, as I said)** ⑦understanding ⑧counter |
| 1432930 | どおり | 3 — ①in accordance with; following ②roughly ③Street |

Songs routinely use sense ⑥ (思った通り, その通り). The card would show senses ①–② — "avenue;
street" — which is not the meaning in play.

Neither the reading split nor POS ranking rescues this. Sudachi tags **every** context
identically — `名詞-普通名詞-助数詞可能`, normalized `通り`, reading `トオリ`:

```
思った通りだ   通り  トオリ  名詞-普通名詞-助数詞可能
その通りだよ   通り  トオリ  名詞-普通名詞-助数詞可能
予定通りに進む  通り  トオリ  名詞-普通名詞-助数詞可能   ← actually よていど"お"り
広い通りを歩く  通り  トオリ  名詞-普通名詞-助数詞可能
二通りの方法   通り  トオリ  名詞-普通名詞-助数詞可能
```

So identical tokens produce **one card** for all uses, and `rank_senses()` receives the same POS
for all eight senses and cannot reorder them. There is no signal to automate on.

**Decided: showing a sense the song doesn't use is acceptable, and often useful.** A card is about
the *word*, not the occurrence. Learning that 通り also means "avenue; street" is worth knowing the
next time you meet it in the wild, even when this song means ⑥. This is why the prompt asks for
*some* of the meanings — the card is deliberately teaching range, and the reveal's full sense list
is where that lands.

So no sense pinning, no sense-level card keys, and no neighbour-token disambiguation heuristic.
The apparent problem was mostly a mis-framing of what a vocabulary card is for.

**But the reading underneath it can genuinely be wrong — and that must be fixable from the card.**

The one automatic step that *is* wrong here is the reading. Sudachi reads 予定通り's 通り as トオリ
when it is actually よていど**お**り, so the gloss comes from entry 1432920 (とおり) when 1432930
(どおり — "in accordance with; following", as sense ①) is the better match. That entry is
unreachable *automatically*, but not unreachable full stop: a manual reading correction sets
`selected_reading`, and `own_gloss_key` then keys the token as `(通り, どおり)` — reaching the right
entry, whose leading senses then fit the song. This is a real correction already available in the
reading view, and it is exactly the fix a mis-glossed 通り needs.

**Decided: cards carry a "wrong reading?" affordance** that opens the alternates inline and applies
a correction without leaving the session. The endpoints exist —
`GET /documents/{id}/tokens/{tid}/alternate-readings` and the batch
`POST /documents/{id}/tokens/reading` (`applyReading`), which already returns every affected token.

Behaviour, given §4's rule that the reading is half the card's identity:

1. **The current review is abandoned, unrated.** You were being asked about the wrong word; a
   rating would be noise in the review log.
2. **The correction repoints the song at a different card**, per §4. The new card enters as new.
3. **The old card is dropped only if nothing was learned on it** — no reviews yet means it was
   never really a card, so delete it silently. If it *has* review history, keep it (and say so):
   that history is real knowledge about a real word, exactly as with 辛い/からい.

This makes the study session a discovery surface for annotation errors, which is a nice loop:
reviewing a song improves the song's own reading data, and the reading view gets better as a side
effect of studying. It also reinforces the harvest rule from §4 — don't auto-enroll tokens whose
reading is still an unreviewed default guess.

The correct option is the **top-ranked sense** via the existing `rank_senses()`. Order is
randomized per presentation.

**An option is correct because it belongs to the target word, not because it shows the sense we
picked.** That distinction matters for polysemous words — see §4's note on `rank_senses()`
flattening every entry that matches the reading into one list.

Auto-enrolled. This is the bulk of the deck.

### Type B — Conjugation / grammar

> The line plays. The predicate group is bracketed, one element highlighted.
> **What is って doing here?** Pick from four.

```
  君 の 声 が [聞こえ てる んだ って]
                          ▲
  1  quoting: says that, or I hear that   ←
  2  of, 's; or makes a clause a noun
  3  and, then; links to what follows
  4  although, even though
```

**Decided: multiple choice over the grammar notes.** This is the best-fitting card in the whole
design, because the answer space is *already a closed, hand-authored set* — distractors come free,
and the fuzziness that made this card unfair to self-grade ("quoting: says that, or I hear that" —
close enough?) stops mattering entirely once you're choosing rather than judging.

**Distractors come from the same category as the target**, which is what makes them hard rather
than decorative: て vs で, たら vs ば vs ても, れる vs せる, の vs って. Those groupings already
exist in `grammar.py` — as *source comments* (`# Auxiliaries (助動詞)`, `# Particles (助詞)`,
stems of そうだ/ようだ/みたいだ, helper verbs). Turning them into a structured field alongside each
note is the one small content change this card needs.

This is the one the app is unusually well equipped for. `backend/app/grammar.py` already builds
**predicate groups** — bunsetsu like 欲し/てる/ん/だ/って glossed as a unit — and `_GRAMMAR_NOTES`
is a hand-written table of ~85 learner-facing explanations keyed by `normalized_form`:

```python
"てる":  "short for ている: is doing, or the resulting state",
"って":  "quoting: says that, or I hear that",
"のに":  "although, even though",
"ちゃう": "short for てしまう: end up doing, or do completely",
```

with `grammar_note()` falling back to "particle" / "suffix" / "grammatical ending" for anything
unlisted. `GrammarLegend.tsx` already holds the matching frontend table with conjugation forms
and example sentences. The reveal side of this card is **already authored** — it's the same
content the Grammar Rules modal shows.

**Decided: these cards key on the grammar term, not on the word.** There are ~85 of them, ever —
a small fixed deck — and the example line is drawn from whatever song you're currently studying,
so the card stays fresh without multiplying. Learning what って does is a single thing to learn,
not a fact you relearn per verb. (The rejected alternative, a card per word-plus-inflection,
balloons the deck and teaches the same point across dozens of verbs.)

```
Deck size: ~85 cards, lifetime

  って  — seen in 12 songs, stability 34d  ● mature
  てる  — seen in 31 songs, stability 61d  ● mature
  のに  — seen in 3 songs,  stability 4d   ○ learning

Today's line for って:
  君 の 声 が 聞こえ てる んだ [って]
  → quoting: says that, or I hear that
```

Auto-enrolled, but naturally capped at ~85 lifetime cards. A consequence worth noting: because
the example rotates, the same card can be easy in a familiar line and hard in a new one — that's
desirable, but it means these cards will show more rating variance than vocabulary cards.

### Type C — Production / locate (EN→JA)

> The line plays. **Which part of this line means "can hear"?**
> Click it.

The line renders as clickable tokens; you pick the span, graded against the token's character
offsets. It's the closest thing in the deck to the actual skill of following a song in real time,
and the only card whose answer space is wide enough to earn Easy (see the rating map below).

Where the target is a predicate group or an accepted phrase, the whole group is the correct
answer, since that's the unit that carries the meaning.

**Decided: opt-in, default off.** Recognition and production are genuinely separate skills and
deserve separate scheduling, but enabling this roughly doubles the daily load — so it starts off
and you flip it on once the queue feels comfortable. Still open whether that toggle is global or
per song.

### Deliberately deferred

*Given a dictionary form and a target meaning, produce the conjugated form* — "take 聞こえる, make
it 'is doing'" → type 聞こえてる. This looks like it needs a conjugation generator, which Sudachi
isn't. **It doesn't:** the card was harvested from a real lyric, so the song's own
surface string is the gold answer. Exact match after kana normalization, no generator, no fuzzy
matching — and `wanakana` is already a dependency, so romaji input converts as you type.

It's the one card that would be both objective *and* full production, which makes it the obvious
next addition. The open problem is variants: ている and てる both express "is doing" and only one
is in the song, so a defensible answer can miss the gold string. Solvable (accept any form whose
auxiliary shares a `normalized_form`), but it's the reason this isn't in v1.

### The kanji sidebar

**Decided: kanji get a sidebar on the reveal, never a card of their own.**

Dedicated kanji cards would break three constraints the rest of the deck meets. They have no line
to play, since 聞 never appears in a song — 聞こえてる does. They have no objectively gradable
question: kanji meanings are fuzzy glosses ("hear, ask, listen"), and asking for a reading in
isolation has no single right answer, since 通 carries two on'yomi and eight kun'yomi and which
one applies depends entirely on the surrounding word. And they don't serve the motivating
question, because a song can be followed by ear with no kanji knowledge at all.

The cost of that choice is real and worth stating: kanji recognition will lag vocabulary. Knowing
涙 inside a song is not the same as recognising it in a novel. The sidebar softens that; it does
not fix it. The signal to revisit the decision is already in the data — Type A failures on words
whose *meaning* is known but whose written form isn't are kanji weakness surfacing as vocabulary
failure.

#### What it shows

Every kanji in the target word or group, on the reveal only. The prompt stays dimmed and focused.

```
聞   ブン・モン ・ き(こえる)                        grade 2 · freq 319
     hear, ask, listen
     radical 耳 ear ・ also 門
     also in your deck:  新聞 (mature) · 聞く (learning)
```

- **All on'yomi.** Almost always one or two, so the full list costs nothing.
- **Only the kun'yomi in play**, with a `+N more` count. This is exactly where "show both standard
  readings" breaks down: 通 has 8 kun'yomi, 下 has 12, 生 has 18 — while their on'yomi are two
  apiece. The contextual reading is the useful one anyway.
- **Meanings, grade and frequency**, free from KANJIDIC2 — enough to distinguish "you will meet
  this one everywhere" (生: grade 1, freq 29) from "this one is rarer" (涙: grade 8, freq 1381).
- **The radicals it's built from**, in two tiers. See below — the two available sources answer
  different questions and the distinction matters.
- **Cross-links into your own deck**, which is the part a dictionary cannot do. Seeing 聞 beside
  新聞 is a link being made rather than passive exposure, and `study_cards.lookup_form` is short
  enough that a `LIKE '%聞%'` scan is fine at this scale.

Size and layout are left open: 勝利の女神 contributes four kanji, and a predicate group can
contribute more.

#### Data, and three matching wrinkles

KANJIDIC2 ships with `jamdict`, already a dependency, so this adds no packages.
`Jamdict().lookup('通')` returns `.chars[0]`, whose `rm_groups[0]` carries `on_readings`,
`kun_readings` and `meanings`, alongside `stroke_count`, `grade` and `freq`.

The contextual reading is already computed. `build_furigana_spans` splits **per character**, even
inside compounds, and returns hiragana:

```
女神      → [{'text': '女', 'reading': 'め'}, {'text': '神', 'reading': 'がみ'}]
聞こえてる  → [{'text': '聞', 'reading': 'き'}, {'text': 'こえてる', 'reading': None}]
```

Matching the two sources needs three normalizations:

1. **Okurigana markers.** KANJIDIC writes kun readings as `き.く`, `とお.り`, `-どお.り`. Compare
   against the stem before the dot, and strip leading hyphens.
2. **Rendaku.** 女神 gives 神 the reading がみ, while KANJIDIC lists かみ. Voiced initials have to
   be unvoiced before comparison.
3. **Script.** On'yomi are katakana (ブン); kun'yomi and furigana readings are hiragana (き).

Where no kun reading matches — a jukugo read with on'yomi — showing the on'yomi list alone is the
correct outcome, not a failure to handle.

#### Radicals: two sources, two different questions

`jamdict` carries both, and they are not interchangeable.

**KANJIDIC2's classical radical** (`.radical`) is the single semantic key, and it comes with an
English name and stroke count already attached:

```
聞 → 耳-ear[sc:6]      通 → 辵-walk[sc:7]     涙 → 水-water[sc:4]
神 → 示-spirit[sc:5]   生 → 生-life[sc:5]
```

Every one of those is meaningful: 聞 is an ear at a gate, 涙 is water, 神 relates to the spirits.
This is the tier to lead with.

**KRADFILE** (`jamdict.krad`) decomposes a kanji into its visual components, which is a different
and noisier thing:

```
聞 → 耳, 門           clean and meaningful
通 → 辶, 用, マ        マ is a stroke shape, not a semantic unit
涙 → 戸, 氵, 大, 一, 尸  over-decomposed: 涙 is 氵 + 戻, and 戻 is 戸 + 大
神 → ｜, 日, 礻, 田     ｜ and 日/田 are fragments of 申
```

It decomposes recursively to atomic pieces and includes stroke fragments, so presented raw it is
as likely to mislead as to help.

**Decided: lead with the classical radical and its English name, then show the remaining KRADFILE
components as a muted secondary line.** The first tier is always meaningful; the second is a
useful "what else is in here" hint as long as it is visibly subordinate rather than presented as
semantic structure. Capping the second tier is reasonable — 涙's four leftovers earn little.

**A fourth matching wrinkle.** KANJIDIC gives the classical radical in its **standalone** form,
but the kanji contains its **variant**:

| kanji | classical | as it actually appears |
|---|---|---|
| 涙 | 水 | 氵 |
| 神 | 示 | 礻 |
| 通 | 辵 | 辶 |

Displaying "水 water" beside 涙 when the visible component is 氵 invites exactly the confusion this
sidebar exists to prevent. KRADFILE supplies the variant form, so the fix is to render the
classical radical using whichever KRADFILE component corresponds to it — which needs a small
standalone-to-variant mapping (水→氵, 示→礻, 辵→辶, 手→扌, 心→忄, 火→灬, 犬→犭, 艸→艹, and a couple
of dozen more). Finite, well documented, and worth getting right, since it is the difference
between a radical that teaches and one that confuses.

### Grading is objective on every card type

**Decided: there is no self-rating anywhere.** You never judge your own recall; every card has a
checkable answer, and the rating is computed.

| Type | Input | Graded against |
|---|---|---|
| A — Recognition | Pick 1 of 4 English glosses | The target's top-ranked sense |
| B — Conjugation | Pick 1 of 4 grammar notes | `_GRAMMAR_NOTES[normalized_form]` |
| C — Production / locate | Click a token in the line | The token's `char_begin`/`char_end` |

### Mapping objective results onto FSRS's four ratings

**Decided: correctness plus latency, with multiple choice capped at Good.**

| Result | Typed / click-in-line | Multiple choice |
|---|---|---|
| Wrong | 1 Again | 1 Again |
| Correct, slow | 2 Hard | 2 Hard |
| Correct | 3 Good | 3 Good |
| Correct, fast | 4 Easy | **3 Good** (capped) |

The cap exists because a four-option card has a 25% blind-guess floor, and FSRS cannot tell a
lucky guess from knowledge — it just sees Good and grows stability. Capping means a guess can
never compound into a long interval.

The principle is really *Easy requires a low guess probability*, not *Easy requires typing* —
which is why Type C qualifies despite being a click: its answer space is every token in the line,
not one of four.

**Consequence worth naming: with the default card set, Easy is unreachable.** Types A and B are
both multiple choice, and Type C ships off — so nothing can earn a 4. Two ways to read that:

- *It's fine.* Good still compounds; Easy is an accelerator, not a requirement. And the
  **push-out ladder from §1 is the intended fast path** for words you already know, which is
  exactly the case Easy would have served. The two decisions fit together.
- *It's a drag.* Auto-enrollment pulls in words you know, and without Easy each one needs several
  Good reviews or a manual push-out to get out of your way.

The first reading is the working assumption, since the push-out button already exists for
precisely this. It is flagged because it is the kind of thing that feels wrong three weeks in,
not on day one.

### What this trades away

Free recall is a stronger exercise than recognition — that's well established, and choosing from
four options is easier than producing an answer from nothing. So objectivity costs some
pedagogical strength on the meaning cards. That's a real trade, made deliberately: a grade you
can't fudge is worth more here than a harder exercise you can.

Two gaps it leaves, both additive later if wanted:

- **Nothing tests kanji readings.** Reasonable given the app's kana-literacy assumption and the
  fact that the reading view furiganas everything — but it does mean the deck never asks how a
  word is pronounced.
- **Nothing tests production from scratch.** Type C asks you to *locate* a word, not generate it.
  The typed-conjugation card below is the natural place that would go.

### Latency thresholds

"Slow" and "fast" need numbers. Start with flat per-type constants (answering a 4-option card in
under ~3s is fast; over ~10s is slow) and revisit once there's real data — a median-of-your-own-
history baseline is better but needs the review log to exist first. The thresholds must be
recorded alongside each review so a later change doesn't silently reinterpret old ratings.

---

## 4. Which word a card is about

### The reading is part of the card's identity

This is the answer to "how does a card know which word it is": **the resolved reading is half of
the key**, so a reading change isn't a detail about a card — it's a different card.

The existing chain, which the design attaches to rather than replaces:

```
tokens                                   conflicts
  normalized_form ──────┐                  token_id ──────┐
  part_of_speech        │                  kind           │  'heteronym' | 'no_kana_anchor' | …
  gloss_lookup_id ──┐   │                  value          │  {reading, citation_reading, …}
                    │   │                  selected       │  ≤ 1 true per token (partial uniq idx)
                    │   └────────┬──────────────────────── ┘
                    │            │
                    │   own_gloss_key(normalized_form, part_of_speech, selected_reading)
                    │            │      glosses.py:452
                    ▼            ▼
             gloss_lookups (lookup_form, reading)   ← UNIQUE
                  entries JSONB
                  source  'jmdict' | 'jmdict_miss' | 'english_stub' | 'composite'
                           │
                           │  the card copies this pair; it does not reference the row
                           ▼
             study_cards (user_id, lookup_form, reading)   ← UNIQUE
```

`own_gloss_key` is the whole mechanism:

```python
if selected_reading is not None:
    return (normalized_form, selected_reading)      # a reading was picked
return citation_key(normalized_form)                # (form, mixed_reading(form))
```

and `selected_reading` comes from the selected conflict row —
`COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading')` (`glosses.py:835`).

So for 辛い, picking からい and picking つらい produce **two different `gloss_lookups` rows and
therefore two different cards** — spicy and painful, scheduled independently. Which is right:
they really are different words that happen to share a spelling. Conversely 聞こえてる and
聞こえた collapse to one card, because `lookup_form` is the *normalized* form, not the surface.

Three consequences fall out, and they need handling:

**1. Changing a reading after enrolment repoints the song at a different card.** You study 辛い as
からい for three months, then decide the song means つらい. The token's `gloss_lookup_id` moves, the
derived association follows it, a fresh つらい card starts at zero — and the からい card keeps its
full history, possibly orphaned (which the all-songs queue from below catches). That's correct
behaviour, but it must be *said out loud* in the UI at the moment of the change, or progress
appears to vanish for no reason:

> *Changing this reading to つらい starts a new card. Your からい card keeps its history.*

One refinement, since §3 makes reading correction a first-class action **from inside a study
session**: drop the old card silently when it has **no reviews yet**. Nothing was learned on it,
so it was never really a card — it was an auto-enrolment acting on a reading that turned out to be
wrong. Keep it, and say so, the moment it has any review history.

**2. Don't auto-enroll tokens whose reading is still unresolved.** Note the comment on
`gloss_key` (`glosses.py:442`): *"For a flagged token, this is also the key of the default option
create_conflicts selects."* A flagged heteronym is glossed under the **default** candidate until
you choose — so auto-enrolling it means building review history on a guess that a later
correction will discard. **Added to the harvest rule: skip tokens with `needs_review` and no
selected conflict.** Manual enrollment from the gloss popup can still override, since that's an
explicit choice. This also gives the existing reading-review workflow a second purpose beyond
display: it gates what enters your deck.

**3. A card is a pointer to a word identity, never a copy of its content.** Since migrations
0013–0015 can empty `gloss_lookups`, a card's join can miss — and then there's no gloss to render
and no distractors to build. The fix is **on-demand rehydration through the existing
`plan_glosses()` / `store_glosses()` pipeline** when the queue builder finds a key uncached. Do
*not* snapshot the gloss onto the card: that would survive cache invalidation by preserving
exactly the stale content the invalidation exists to replace.

### One residual sharp edge

`(lookup_form, reading)` is unique in `gloss_lookups`, but `source` is not part of that key, and
`rank_senses()` flattens *all* JMDict entries matching the reading into one list. So a
genuinely polysemous word has several unrelated senses under one card.

That matters for objective grading: if the correct option shows sense 3 and you were thinking of
sense 1, you could reject your own right answer. The fix is in how the option list is built —
**an option is correct because it belongs to the target word, not because it's the sense we chose
to display.** Show the top-ranked sense (most likely to be recognised), draw distractors from
*other words*, and reveal the full sense list afterwards so the range gets learned. Residual risk
on very polysemous words is real but small.

## 5. Which line plays

Cards are **global per word** — learn 涙 in one song, and it isn't a fresh card in the next. So
the line is not a property of the card; it's chosen **when the queue is built**, preferring an
occurrence in the song you're currently studying and falling back to any song that has the word.

This is what makes "study this song" work as a *filter* rather than a separate deck of duplicate
cards, and it has a nice side effect: a word you first learned elsewhere shows up in the new
song's own line, which is exactly the review you want.

**Not every document can do audio.** A song needs both a `youtube_video_id` and line timings
(`lrclib_lines`, or `edited_lines` from the timing editor) to play. Without them the card falls
back to text-only with the line still shown. The UI should make that degradation quiet, not an
error — and this is a real argument for the LRCLIB work landing first.

### When the lyrics change underneath a card

This is a live hazard, not a hypothetical. `get_document` (`backend/app/main.py:201`) refreshes
from LRCLIB **on every read**, and if `lrclib_replaces_text` is true and upstream text has
changed, `_store_lrclib_lyrics` calls `_delete_tokens` (`main.py:282`) — deleting every token and
every conflict row for that document, then replacing the text. Documents created with LRCLIB
lyrics default to `lrclib_replaces_text = True` (`main.py:179`), so this can fire from someone
merely opening a song.

**Almost nothing needs recovering, by construction.** That's the payoff of the two structural
choices already made — the natural key and the derived association:

| | Survives? | Why |
|---|---|---|
| Cards + all FSRS state | **Yes** | Keyed on `(user, lookup_form, reading)`; no FK to `tokens` or `gloss_lookups` |
| Review history | **Yes** | FK to cards; `document_id` points at a row that isn't deleted |
| Suspended / removed state | **Yes** | Lives on the card row |
| Type B conjugation cards | **Yes** | Keyed on the grammar term — entirely lyrics-independent |
| Type C answer offsets | **Yes** | Chosen at queue-build time, never stored |
| Card ↔ song association | **Recomputes** | Derived by joining cards against `tokens`, so re-tokenization restores it |

For any word still present in the new lyrics, the association simply reappears the next time the
queue is built. There is no repair step because there is no stored link to corrupt.

**The one real gap: words that left the song.** If LRCLIB's version drops a verse, those cards
still exist with full history, but they're no longer in *any* song — and since the session flow is
per-song ("Study this song"), nothing can reach them. They stay due forever and are never shown.

Three fixes, in order of how much they're worth:

1. **An all-songs review queue.** This is the actual fix, and it's worth having regardless of
   lyric churn — a queue that ignores document boundaries makes orphans reachable by definition.
   Without it, per-song study has a permanent leak.
2. **An orphan view, free of charge.** `first_seen_document_id` survives the wipe, so "cards that
   came from 雲の糸 but are no longer in it" is already answerable with no new storage.
3. **Surface the change instead of swallowing it.** After a refresh alters the word list, say so:
   *"雲の糸's lyrics changed upstream: 88 words → 82. 6 of your cards are no longer in this song."*
   A silent readiness score jumping from 41% to 46% because the denominator moved is worse than a
   sentence explaining it.

A fourth option, if the diff matters more later: store an **enrollment record**
(`document_id, lookup_form, reading, enrolled_at`) at enrollment time. Note this contradicts the
"don't store derived data" argument from §6 only in appearance — the *live* association stays
derived and self-healing, while this is a deliberately historical record of what you once enrolled
from this song. Staleness is the feature. Not needed for v1, since `first_seen_document_id`
covers the useful case.

**Worth knowing separately:** this same code path already destroys `conflicts` rows — your
reading and phrase selections — on any upstream text change. That's pre-existing behaviour with
nothing to do with flashcards, but it's the same hazard class, and it's the kind of thing worth
deciding on deliberately rather than discovering.

---

## 6. Song-level progress, and reviewing a song rather than a card

Cards are the unit of scheduling, but the song is the unit you actually care about. So the app
needs a per-song aggregate — and a mode that studies a song as a song.

### "Song readiness" — one number per song

FSRS gives retrievability per card (`get_card_retrievability`), so a song-level score is a
roll-up of the cards belonging to that song's words.

**Definition: the occurrence-weighted mean retrievability across *all* of the song's harvestable
words, counting words with no card yet as 0.**

Two deliberate choices in there:

- **Unenrolled words count as zero.** If the average only covered enrolled cards, a song where
  you'd seen 10 of 88 words would read 95% and be actively misleading. Counting the rest as 0
  makes the number mean "how much of this song is in your head", which is the question being
  asked, and it climbs as you enroll.
- **Weighted by occurrence count.** A word sung six times in the chorus matters more to
  following the song than a hapax in verse two. Token counts are already there, so this is free.

Alongside it, two legible secondary counts: **coverage** (cards created / harvestable words) and
**mature** (stability ≥ 21 days — adopting Anki's convention, which is backed by far more data
than anything we'd pick).

```
雲の糸                                      readiness 41%
  ████████░░░░░░░░░░░░
  88 words · 34 enrolled · 12 mature · 9 due today
```

Compute it on read from `stability` + `last_review`; **don't store it.** A denormalized score
column would go stale on every review and every enrollment, and retrievability decays with wall
time anyway, so any cached value is wrong the moment it's written. If the query gets expensive
later, cache it with a TTL rather than maintaining it transactionally.

This also gives the documents list a natural sort ("least ready first") and a nudge worth having:
*"雲の糸 has drifted to 41% — run through it?"*

### Run-through mode

Distinct from the card queue: **play the song start to finish, pausing on the lines that contain
your weakest words.** Line order, not due order. This is the mode that matches "I want to be able
to follow this song tonight", and it's the one that most justifies the app existing.

**Open question — should a run-through affect scheduling?** Recommend **no** for v1: it's
practice, it doesn't log reviews, it doesn't move due dates or the readiness number. Reasoning: a
run-through of a 90-word song would otherwise consume your entire queue in one sitting and pull
every stability estimate toward "reviewed early, recalled fine". Anki's nearest equivalent
(filtered decks / cram) makes rescheduling an explicit toggle, which is probably where this ends
up too.

The honest cost of that choice: practice that visibly doesn't move the progress bar feels
unrewarding. Worth deciding with eyes open — the alternative is a number that's easy to inflate.

---

## 7. Session flow

1. **"Study this song"** from the document page. First visit auto-enrolls the song's words.
2. Queue = cards due today whose word appears in this song, **plus** up to 10 new cards from it
   (the per-song limit from §2 — Anki's default is 20, but 10 suits songs, where you want to
   actually finish the sitting).
3. Cards are mixed across types, with the constraint that the same word's recognition and
   production cards don't appear back to back.
4. Per card: **the line auto-plays** → pick your answer with `1`–`4` (or click, on Type C) →
   the result and full reveal appear together, already graded. Space replays the audio, `!`
   pushes the card out, `-` removes it. There is no separate reveal-then-rate step, because
   there is nothing left for you to rate.
5. End-of-session summary: reviewed, **accuracy** (now a real number, not a self-report), what's
   left, next due, and the song's new readiness.

**Autoplay with a persistent mute.** Audio plays on card entry by default, with a mute toggle
that survives reloads — `usePersistentState` (the `song-study:` localStorage wrapper) already
exists for exactly this, so it's a few lines. Muting keeps the lyric line and the dimming; it
only silences playback, so a muted session is still a usable study session on a train.

### Which tokens become cards

Not every token is vocabulary. The pool is tokens whose gloss came from a real JMDict headword —
excluding `gloss_ignored` (names and non-words you already flagged), `english_stub` (Latin-script
words routed away from JMDict), `composite` glosses (A-split breakdowns and katakana-as-hiragana
fallbacks are explanations, not headwords), particles and auxiliaries (grammar, which Type B
covers), and — per §4 — **tokens whose reading is still a default guess**.

As built (step 2), that last rule is `needs_review` with a `heteronym` or `oov` reason. The default
option is always created *selected*, so "no selected conflict" never happens; what a pick changes
is `needs_review`, which any pick clears — including re-picking the default. A `no_kana_anchor`
flag doesn't gate: the reading is certain, only its furigana split isn't. **The rule holds back a
lot:** on the 蜘蛛の糸 test fixture it excludes 47 of 159 words (人, 水, 花, 日, 事, …), nearly all
of whose default readings are right. That's the decided trade — enrolling late over building
history on a guess — but it means reviewing readings is what unlocks much of a song's deck.

An **accepted phrase** (この期に及んで) is one word, keyed on its headword; the particles inside it
are part of the headword, not grammar.

Predicate groups look like an awkward case — the group's gloss is a composite, so the head verb
has no headword row of its own. Type B dissolves that: **the group is the
conjugation card, and the head verb is separately harvested as a Type A card** from its own
`normalized_form`. Nothing gets skipped.

A word sung in **katakana for emphasis** (ココロノコエ) is glossed as the words its hiragana splits
into (心の声). **Decided:** such a line links to those words' cards. It counts toward the song's
cards and can be the line a card plays. It never harvests a card, because turning kana into kanji
is a guess (コエ could be 声 or 越え), just as a heteronym's reading is. Adding one of its words by
hand is still allowed (step 8).

Each word links under the spelling its gloss shows (アイタイ's あう is 会う, the entry of its
top-ranked sense), so it reaches the card a kanji spelling of the word gives. Linking to every card
with the same reading instead was rejected: it avoids the guess only by being certainly wrong
whenever two homophones are both carded, and it leaves no single choice to correct. The guess is
treated as a heteronym's default is: taken, and correctable (step 8). Where the gloss's spelling
differs from the spelling Sudachi gives the kanji word (分かる vs 解る), the line doesn't link.

---

## 8. What the experience needs from the data

Not a migration — just the inventory, so we know what's cheap and what isn't.

**Already there:**

- Word identity — `gloss_lookups (lookup_form, reading)` is unique and document-independent
- Ranked senses, dictionary-form notes, furigana spans — all on the existing `Token` payload
- Predicate groups and `grammar_note()` — `backend/app/grammar.py`
- Grammar explanations and examples — `_GRAMMAR_NOTES`, `GrammarLegend.tsx`
- Line timings — `documents.lrclib_lines` / `edited_lines`; playback — `YouTubePlayer.tsx`,
  `LinePlayButton`
- Token character offsets (`char_begin`/`char_end`) — enough to locate a token within its line

**Needs building:**

- A **user** — nothing in the app has one today, so there's nowhere to hang study state.
  Confirmed staging: seeded single user now, OAuth at deploy time.
- **Card + review-log storage**, holding FSRS's `state / step / stability / difficulty / due /
  last_review` plus an append-only review log (needed later for personal parameter fitting)
- A **line-index helper on the backend** — the frontend currently derives a token's line by
  counting `\n`; the queue builder needs the same thing server-side
- **An all-songs queue** in addition to the per-song one, so no card can be stranded (§5)
- **Settings** — global desired retention and production-cards on/off; per-song new-card limit
- **A suspended flag** on cards, plus the gloss-popup add/restore affordance in the reading view
- **Occurrence counts per word per song** for readiness weighting — derivable from `tokens` with
  a `GROUP BY`, no new storage
- **A category field on each grammar note** — the groupings exist in `grammar.py` only as source
  comments, and Type B's distractors need them as data
- **Distractor selection** for Types A and B — POS-matched, same-song-preferred, near-synonym
  guarded, length-normalized. New logic, but it reads only data that already exists
- **An option-list renderer** that shows glosses *without* readings — `SenseBlock` and
  `GlossDetails` both show the reading, so neither can be reused for the prompt side
- **Per-review latency** on the review log, plus the thresholds in force at the time, so ratings
  stay interpretable if the thresholds change
- **KANJIDIC2 and KRADFILE lookups** through the existing `jamdict` dependency, plus kun-reading
  matching (okurigana, rendaku, script) against `furigana_spans`, and a standalone-to-variant
  radical mapping (水→氵, 示→礻, 辵→辶, …)
- **Reading correction from inside a session** — reuses `GET /documents/{id}/tokens/{tid}/alternate-readings`
  and `POST /documents/{id}/tokens/reading`; new work is the card-side flow, not the endpoints

**One constraint worth carrying forward now, because it's easy to get wrong:** migrations 0013,
0014 and 0015 `DELETE FROM gloss_lookups` as a deliberate cache-invalidation pattern whenever
gloss logic changes. Study cards must therefore **not** hold a foreign key into that table — they
should store the natural `(lookup_form, reading)` pair and join for display. Otherwise the next
change to `glosses.py` cascade-deletes real review history.

**Library:** `py-fsrs` (`pip install fsrs`, Python 3.10+, FSRS-6, 21 parameters). The TypeScript
port `ts-fsrs` is the same project but wrong-side — scheduling has to be server-side since due
dates are shared state. Default parameters are fitted on ~727M reviews and are fine indefinitely;
`fsrs[optimizer]` trains personal ones later from the review log.

---

## 9. Decided

- **Grading is objective on every card type — there is no self-rating anywhere.**
- **Type A picks the correct gloss from four English-only options**, readings omitted so you
  can't match kanji to kana instead of knowing the meaning. The app assumes perfect
  hiragana/katakana literacy, so meaning is what's worth testing.
- **Type B picks the correct grammar note from four**, with distractors from the same category.
- **Every Type A option shows two senses**, all glosses within each, uniform across options — the
  hedge against polysemy, since the app can't know which sense the song intends. The reveal keeps
  the popup's existing five-sense limit.
- **The Type A prompt is "What are some of the meanings of this word?"**, with a visible "2 of N"
  count, because a definite question would claim knowledge the card doesn't have.
- **A card may show a sense the song doesn't use, and that's fine** — it teaches the word's range
  for the next time you meet it. No sense pinning, no sense-level keys (§3).
- **Cards carry a "wrong reading?" affordance** that applies a correction inline via the existing
  alternate-readings endpoints. The current review is abandoned unrated, the song repoints to a
  different card per §4, and the old card is deleted only if it had no reviews.
- **Ratings are computed from correctness + latency, and multiple choice caps at Good**, so a
  lucky guess can't compound into a long interval. A consequence: with the default card set,
  Easy is unreachable and the push-out ladder is the intended fast path for known words.
- **Conjugation cards key on the grammar term** (~85 lifetime), with the example line rotating
  from whatever song you're studying.
- **Vocabulary cards dim the line except the target**, brightening on reveal.
- **Production/locate cards are opt-in, default off.**
- **Enrollment is automatic**, which is what makes the "I already know this" push-out
  load-bearing rather than a nicety.
- **Desired retention is a global user setting** (0.90 default), surfaced as consequences rather
  than a bare number. Global because cards are shared across songs.
- **New cards per day is per song**, default 10, in the same settings surface as retention.
- **Audio autoplays** on card entry, with a mute that persists across reloads.
- **Push-out ladder is 1 / 3 / 6 months.**
- **Removal suspends rather than deletes**; you re-add a word by finding it in the lyrics and
  adding it from the gloss popup, which restores its existing history.
- **"Known" means stability ≥ 21 days**, adopting Anki's mature threshold.
- **Songs get a readiness score** — occurrence-weighted mean retrievability over all harvestable
  words, unenrolled counting as 0 — computed on read, never stored.
- **Run-through mode** studies a song in line order; for v1 it's practice and does not reschedule.
- **An all-songs review queue exists alongside per-song study**, so cards can't be orphaned and
  stranded when a song's lyrics change upstream (§5).
- **The resolved reading is half the card's identity** (§4). 辛い/からい and 辛い/つらい are two
  cards; 聞こえてる and 聞こえた are one. Changing a reading therefore starts a new card and must
  say so in the UI.
- **Unresolved readings are not auto-enrolled** — a flagged heteronym is glossed under a default
  candidate, and building review history on a guess is worse than enrolling late.
- **A card points at a word identity and never snapshots its gloss**; an uncached key is
  rehydrated through the existing `plan_glosses()` / `store_glosses()` pipeline.
- **Kanji get a reveal-side sidebar, never cards of their own** — all on'yomi, the contextual
  kun'yomi, meanings, grade and frequency, the classical radical with its English name over a
  muted component breakdown, and links to other words in your deck (§3).
- **The doc lives at `docs/flashcards.md`.**

## 10. Still open

1. **Production cards** — global toggle, or per song? (The enable/disable decision is settled;
   only its scope isn't.)
2. **Should a run-through log reviews?** No for v1, with the cost noted in §6 — the progress bar
   won't move for practice. Anki makes this a toggle, and this probably will too.
3. **Readiness on the documents list** — compute for every song on every list render, or only for
   the song you open? The list is paginated, so N songs means N roll-ups.
4. **Option count** — four everywhere, or more? Six drops the guess floor from 25% to 17% but
   makes the card slower to read and harder to fit on a phone.
5. **Is Easy-unreachable acceptable?** Discussed in §3. Provisionally yes, since push-out covers
   the same need — but it is worth revisiting after a few weeks of real use.
6. **Latency thresholds** — flat constants to start, or wait for the review log and use a
   personal median?
7. **Typed conjugation production** (§3, deferred) is now known to be gradable against the song's
   own surface string. Promote it to v1, or keep it as the first follow-up?

---

## 11. Build order

Each step is a PR that stands on its own. Per the working agreement, **start each only when
asked**.

**0 — This document** → `docs/flashcards.md`. The repo has no `docs/` directory yet, so this
creates it. Everything below references it.

**1 — Users and ownership.** Migration adding `users`, a seeded local user, and
`documents.owner_id`; document routes scoped to the current user. No UI, no study code. Ships
independently and unblocks the rest.
*Watch:* the current-user dependency must default to the seeded user, or all 19 test modules
break — they call route functions directly rather than over HTTP.

**2 — Card storage and harvest.** Migration for `study_cards` / `study_reviews`; the harvest rule
(§7) including the `needs_review` exclusion; card keys derived through the existing
`own_gloss_key()`; the enrollment path. No scheduling yet.
*Watch:* no foreign key into `gloss_lookups` (§5), and rehydrate uncached keys through
`plan_glosses()` / `store_glosses()` rather than snapshotting a gloss.
*As built* (`backend/app/cards.py`, migration 0018) — what later steps build on:
- `study_cards` has a `kind`: `recognition` (Type A, keyed `(lookup_form, reading)`) or `grammar`
  (Type B, keyed on the grammar term with `reading` NULL), unique per user with `NULLS NOT
  DISTINCT`. Type C can become a third kind sharing a word's key, so its scheduling stays separate.
- Grammar cards come only from grammar *attached* in a predicate group or accepted phrase, and
  only for terms with their own entry in `_GRAMMAR_NOTES` — the generic "particle" fallback has
  nothing to test. A particle after a noun outside any group gives no card.
- Cards store `alt_lookup_form` (the token's dictionary form): the second spelling
  `plan_glosses()` needs to rehydrate a word like さり気ない, whose normalized form さり気無い has no
  JMDict entry. It's a lookup input, not gloss content. `gloss_sources()` is the rehydration call.
- The FSRS columns default to py-fsrs 6's new card: state 1 (Learning), step 0, due now.
- `study_reviews` has no cascade from cards, so a card with history can't be deleted; it records
  `correct`, `duration_ms` and the `fast_ms` / `slow_ms` thresholds beside `rating`.
- `enroll_new_words(conn, user_id, document_id, limit)` creates cards most-sung word first and
  never restores a suspended card; step 3's per-song daily limit supplies `limit`.
  `PUT /documents/{id}/tokens/{tid}/card` is the manual add/restore, which overrides
  `gloss_ignored` and an unreviewed reading but still needs a JMDict headword.

**3 — Scheduling.** The `fsrs` dependency, the review endpoint, the rating map (correctness +
latency, multiple choice capped at Good), push-out and remove, the per-song queue **and the
all-songs queue**, the per-song new-card limit, the retention setting.
*Watch:* a manual push-out is a reschedule, never a logged rating.
*As built* (`backend/app/study.py`, migration 0020) — what later steps build on:
- Ratings come from the card's `kind` alone: `LATENCY_MS` holds each kind's fast/slow thresholds
  (3 s / 10 s for both, flat as §3 starts) and `MULTIPLE_CHOICE_KINDS` the kinds capped at Good,
  which today is both. Type C, when it arrives, is a third kind that isn't in that set. The client
  sends only `correct` and `duration_ms`; the thresholds are recorded on each `study_reviews` row.
- `POST /cards/{id}/review`, `/push-out` (`months` 1, 3 or 6 → 30, 90 or 180 days) and `/suspend`.
  A push-out sets state Review, stability to the number of days, `last_review` to now, and keeps
  the card's difficulty — or, for a card never reviewed, the one an Easy answer would give it. It
  writes no `study_reviews` row. A suspended card can't be reviewed (409); restoring is still
  `PUT …/tokens/{tid}/card`.
- `POST /documents/{id}/study` is the per-song queue and the one place a song enrolls: it enrolls
  up to `documents.new_cards_per_day` (default 10) less the cards created from that song in the
  last 24 hours, then returns the due cards whose word or grammar term the song has a token for.
  A day is a rolling 24 hours, not a calendar day, to avoid needing a time zone. A word added by
  hand counts against the limit, since the card doesn't record how it began. `GET /study/queue` is
  the all-songs queue, with no enrollment. Both are ordered by due date; a card is due when
  `due <= now()`, so a learning card comes back in minutes.
- A song's cards are found by `document_card_keys`, which reads the tokens the way a hand-add does
  (`explicit=True`), not the way the harvest does: a card added by hand for a word with an
  unreviewed reading would otherwise never show up in its own song's queue.
- `users.desired_retention` (default 0.90, 0.75–0.95) via `GET`/`PUT /study/settings`;
  `documents.new_cards_per_day` via `GET`/`PUT /documents/{id}/study/settings`. Changing
  retention leaves existing due dates alone.
- Deferred, since neither was in this step's list: choosing which line a card plays (§5), now in
  step 4, and spacing a word's recognition and production cards apart (§7), now with Type C under
  "Later". The queues return bare cards, ordered by due date.

**4 — Card content.** Type A's option builder — POS-matched, same-song-preferred, near-synonym
guarded, sense-count matched, two senses each — and Type B's, which first needs the category
groupings in `grammar.py` promoted from source comments to data. Pure backend and the subtlest
logic in the feature, so it earns its own PR and its own tests.

Also here, because it completes the queues step 3 left as bare cards: **choosing each card's
line** (§5) — prefer an occurrence in the song being studied, fall back to any song with the word,
and text-only when a song has no audio — which needs the backend line-index helper from §8 (the
frontend derives a token's line by counting `\n`). A grammar card takes its example line from
whatever song is being studied. The all-songs queue must still return a card whose word is in no
song, with no line.
*Watch:* the line is chosen when the queue is built and never stored (§5), so the queue endpoints
grow a line field rather than the cards gaining a column.
*As built* (`backend/app/card_content.py`, `grammar.py`, migration 0022) — what later steps build on:
- Both queues return `QueuedCard`s: the card's row plus `line`, `options`, `answer` (an index into
  `options`) and, for a word, `senses` — all of them, ranked for the line's part of speech, for the
  reveal. Line and options are drawn afresh on every queue build and never stored. The client still
  grades the pick itself and sends only `correct`.
- `line` has the song, the line's `index` (into `text.split("\n")`, which is also its timing's
  index — `line_index()` is the backend helper from §8), its `text`, and `focus` / `group` as
  [begin, end) offsets in it: 聞こえ within 聞こえてるんだって for a group's head word, the token for a
  grammar term, the whole phrase for an accepted one. `token_id` is for step 8's reading
  correction. `audio` (video id, start, end) is present only when the song has a video and the line
  a timing with some length, edited timings taking LRCLIB's place as on the song's page.
- The per-song queue plays a line of the studied song; the all-songs queue, any song with the word.
  Within those, a line that plays beats a text-only one, and otherwise it's chosen at random so the
  line rotates. A card in no song gets no line, and its senses keep JMDict's order, since there's
  no part of speech to rank them for.
- Type A: every option shows `OPTION_SENSE_LIMIT = 2` senses, or the target's one. Wrong options
  come from the line's song first (its words as the harvest finds them), then the user's other
  carded words (only then are every song's tokens loaded, and 30 are sampled), then another part
  of speech. The POS class is Sudachi's major POS, or `phrase` for an accepted phrase. A wrong
  option with fewer senses than the others is used after every full one but before another part
  of speech. The near-synonym guard turns away a candidate sharing a gloss, a meaning-bearing word,
  or a JMDict entry with the target's first five senses (as many as the reading view shows), or a
  meaning with another option. Matching words is light stemming over the gloss without its
  parentheticals and function words, so an irregular form slips through ("heard" against "hear").
  The same spelling under another reading is never an option. When the song and the deck run dry,
  a card gets fewer than four options rather than none.
- Type B: `_GRAMMAR_NOTES` is grouped by category — `auxiliary` (taking in the そう/よう/みたい
  stems), `particle`, `helper` — and wrong notes come from the term's own category. Category alone
  wasn't enough: many notes describe their grammar alike (ば "if" and たら "if, when"; から and ので;
  the five sentence-final emphasis particles), and either would be a defensible answer for the
  other. `_OVERLAPPING_NOTES` lists those groups, and no two of a group share a card. Being
  confusable doesn't put grammar there — を/が/は and ば/ても are the distinctions to test. A test
  checks that every term gets four options of its own category with no overlap.
- Found on the way: `rank_senses` put する's "to do" last. `_SUDACHI_TO_JMDICT_POS` listed only the
  verb classes seen in one document, missing the suru, several Godan and every archaic class, and
  that sense carries no transitivity tag to match on instead. A 動詞 sense is now any tag naming a
  verb (`_is_verb_sense`), less auxiliaries and nouns taking する. Migration 0022 drops the cached
  group glosses whose pieces carry a newly counted tag, since a group's pieces were ranked when it
  was cached. Since 0023 they refer to their lookups and are ranked when shown, so a ranking change no longer
  needs a migration.

**5 — Kanji sidebar data.** Backend only: KANJIDIC2 and KRADFILE lookups through the existing
`jamdict` dependency, the contextual kun'yomi matched against `furigana_spans`, the classical
radical resolved to the variant form the kanji actually contains, and the deck cross-link query
(`LIKE '%聞%'` over `study_cards.lookup_form`). This produces the sidebar payload; the reveal that
renders it arrives in step 6, so nothing is visible at the end of this step.
*Watch:* four kinds of quiet wrongness in one place — okurigana markers, rendaku, script, and the
standalone-to-variant radical mapping. A wrong reading looks entirely plausible on screen, so this
step lives or dies by its tests. A jukugo with no matching kun reading showing on'yomi alone is
the correct outcome, not a gap to fill.
*As built* (`backend/app/kanji.py`) — what step 6 renders:
- `QueuedCard.kanji` lists one entry per distinct kanji of the card's group, in order, built when
  the queue is: `character`, `on_readings` (all), `kun_readings` (only those the word uses, as
  `き(こえる)`) with `more_kun` for the rest, English `meanings`, `grade`, `frequency` (both
  nullable), `radical` (`character`, `meaning`), `components` and `deck_words`. A kanji with no
  KANJIDIC2 entry (々) is left out. A grammar card gets the kanji of the group it's in.
- The group's kanji are read off its tokens' furigana as the page shows it (override before
  Sudachi's split), so 神 in 女神 is がみ. A card whose word is sung in katakana, or is in no song,
  takes its kanji from its key instead (`kanji_in_word`), since no token writes them.
- Which kun reading a word uses: the stem before the dot, hyphens dropped, compared as the
  hiragana reading; a voiced reading that matches nothing is tried unvoiced (rendaku). Where
  several share the stem (き.く, き.こえる) the one whose okurigana the word has wins, read off the
  dictionary form where the kanji sits at the same place in it, so 聞いた (from 聞く) is き(く). A
  span of several kanji (今日 as きょう, or a reading that didn't split) has one reading between
  them, so none of its kanji gets a kun reading. Nothing marks which on'yomi the word uses.
- The radical is KANJIDIC2's classical one, shown as the variant KRADFILE finds in the kanji
  (`_RADICAL_VARIANTS`, 34 radicals, derived by comparing the two across every kanji). KRADFILE's 辶
  is the compatibility character U+FA66, so its components are NFC-normalized as they're read, and
  a test checks every variant in the table occurs in KRADFILE. The other components leave out the
  radical and the bare strokes (一｜ノ丶乙マ), and stop at three — 涙 is 氵 with 戸 大 尸.
- `deck_words` are the user's unsuspended word cards, other than the card shown, whose
  `lookup_form` has the kanji: five at most, shortest first, each `new`, `learning` or `mature`
  (reviewed, in Review state, with stability of 21 days or more). One query for the whole queue.
- Found on the way: the queue fetches the furigana of the tokens it needs in one query after
  choosing each card's line, rather than `_token_rows` carrying it for every token; and
  `glosses.get_jamdict` and `tokenization.is_kanji` lost their underscore, as `kanji.py` is the
  first module to share them.

**6 — The study UI.** The route, the card frame with dimming, autoplay plus persistent mute,
keyboard handling, reveal, session summary, and the kanji sidebar from step 5 rendered on the
reveal. Extract the shared gloss rendering out of `DocumentViewPage.tsx` rather than duplicating
it.
*Watch:* audio needs a `youtube_video_id` **and** line timings, so this is the step that depends
on the queued LRCLIB work. Also the pending `.new-document-form` CSS narrowing, which currently
overrides every document-page button and will catch this page too. A line sung in katakana
(§7) shows the card's word in kanji (声) beside the highlighted katakana (コエ) on the prompt, not
just on the reveal. Take the spelling from `Line.written_as`, which marks a katakana occurrence; the
UI can't infer it, because a conjugated surface still shows its dictionary form only on the
reveal.

**7 — Progress.** Song readiness (§6), its surfacing on the documents list, and run-through mode.

**8 — Correction and deck management.** The "wrong reading?" flow from inside a session (§3), and
the gloss popup's add / remove / restore affordance (§1).
*Watch:* the popup is already crowded and its edge-nudge positioning is delicate — this is a real
UI change, not a bolt-on. A katakana word's gloss (§7) offers an add for each of its words whose
lookup is a JMDict hit, though the harvest never adds them. `enroll_token` takes one word per
token today, so it has to grow a way to name the piece as well as the token. "Wrong reading?"
(`Line.token_id`) doesn't fit a katakana line, since the katakana is its reading. What can be
wrong there is which word each piece is (§7), so this step adds that correction, built the way a
heteronym's is: the gloss's spelling is the default, and the user can pick another of the
JMDict entries with the piece's reading (合う for アイ). The pick is stored per token and
piece, like a selected conflict, and becomes the piece's card key and `Line.written_as`.
How the katakana splits into words still has no correction flow.

**Later, in rough order of value:** Type C production cards (opt-in, default off), which also
brings the queue-ordering rule that a word's recognition and production cards don't appear back to
back (§7), and a third card kind outside `MULTIPLE_CHOICE_KINDS` so Easy becomes reachable · typed
conjugation production, now known to be gradable against the song's own surface string · OAuth and
deployment · personal FSRS parameters from the accumulated review log.

### Which model to run each step with

A heuristic about task shape, not a benchmark claim.

**Model** answers *how subtle is this?* — **Opus 5** where a mistake is silent or the surrounding
code is delicate; **Sonnet 5** where the spec is tight and the work is pattern application across
breadth; **Haiku 4.5** for mechanical steps with one obvious right answer. Switch with `/model`;
`/fast` gives Opus faster output without dropping to a smaller model.

**Effort** answers a different question — *how much of this is already decided?* — and the two
are independent. Set it with `/effort`. Steps this document has fully specified can run at lower
effort on a capable model; steps where the implementer still has to work something out need
higher effort even when the code is ordinary. Effort trades time and tokens for thoroughness, so
these are **starting points, not floors**: escalate a step that stalls rather than beginning
everything at `max`. `xhigh` and `max` are deliberately absent below — reserve them for a step
that has already failed at its recommended level, or for debugging something that makes no sense.

| Step | Status | Model | Effort | Why |
|---|---|---|---|---|
| 0 — Doc | Done | Sonnet 5 | low | Prose and git mechanics, fully specified |
| 1 — Users and ownership | Done | Sonnet 5 | medium | Repetitive route scoping, but one trap earns the extra care: the current-user default that keeps the existing tests passing |
| 2 — Card storage and harvest | Done | **Opus 5** | **high** | Interacts with the gloss cache. A wrong FK or a wrong harvest rule fails *silently* and shows up later as lost review history or a deck full of junk |
| 3 — Scheduling | Done | Sonnet 5 | medium | `py-fsrs` does the hard math and this document fixed the rating map, so most of it is transcription; the one subtlety is that a push-out is a reschedule, never a logged rating |
| 4 — Card content | Done | **Opus 5** | **high** | The most judgment-heavy logic in the feature — near-synonym rejection and distractor plausibility are semantic calls, not mechanical ones |
| 5 — Kanji sidebar data | Done | Sonnet 5 | **high** | Tightly specified, so an Opus-grade model isn't needed — but okurigana, rendaku, script and the radical variant mapping are four quiet failure modes in one step |
| 6 — Study UI | Not started | Sonnet 5 | medium | A new page is conventional React against a specified layout |
| 6 — …the `DocumentViewPage` extraction | Not started | **Opus 5** | **high** | Pulling the gloss rendering out of a 2,508-line file whose positioning already caused a flicker bug is not conventional |
| 7 — Progress | Not started | Sonnet 5 | medium | SQL aggregation against a clearly specified definition |
| 8 — Correction and deck management | Not started | **Opus 5** | **high** | Lands in the crowded gloss popup and its `useLayoutEffect` edge-nudge — the exact code that needed a bug fix for initial-render flicker |

For the later items: Type C and OAuth/deployment suit Sonnet 5 at medium; typed conjugation
production wants Opus 5 at high, since the ている/てる variant-matching problem is where it gets
subtle.

The pattern worth noticing: the Opus steps are the ones touching **existing, subtle code**
(`glosses.py`'s caching, `DocumentViewPage.tsx`'s positioning) or making **semantic judgments**.
The Sonnet steps are the ones where this document has already done the deciding.

Model and effort *mostly* line up here, which is a sign this document did its job rather than a
rule to generalize. **Step 5 is where they come apart, and it is the instructive case:** the kanji
data work is specified down to the wrinkles, so Sonnet is the right model — but four kinds of
silent wrongness share one step, so the effort stays high anyway.

Where a step is still underspecified — the open questions in §10, or anything renegotiated at
implementation time, such as the kanji sidebar's size and layout — raise the effort regardless of
which model is running it. Underspecification and quiet failure, not difficulty, are what effort
is for.

### Verification

- `cd backend && pytest`, with new coverage for: the harvest rule's exclusions; a review advancing
  `due` and appending a review row; the rating map, including the multiple-choice cap; distractor
  selection (same POS, no near-synonyms, matched sense counts); readiness counting unenrolled
  words as zero; a reading correction repointing the song at a different card.
- Kanji sidebar specifically, since every one of its failures is silent: 聞 in 聞こえる matches the
  kun reading `き.こえる` past its okurigana dot; 神 in 女神 matches `かみ` despite reading がみ; 涙
  renders its radical as 氵 rather than the standalone 水; a jukugo read with on'yomi shows the
  on'yomi list and does not report a missing kun match.
- Tests run against `song_study_test` through `tests/support.py` only — never `DATABASE_URL`, and
  no manual curl or browser checks against the real database.
- Manual pass: `alembic upgrade head`, confirm existing documents get an `owner_id`, study a song,
  confirm `due` moves and `study_reviews` grows.
- There is still no frontend test runner in this repo; adding one is out of scope.
