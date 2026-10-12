# Rich text — one `RichText` type for every text field

**Status:** decided and recorded (**D60**, **D61**), **not implemented**. Nothing in
`src/`, `data/` or `tools/` has changed.
**Found:** 2026-10-12, while discussing whether `emphasis` belonged on explanations
and passages. **Affects:** the whole schema — every text-bearing field, both
loaders, the OpenAPI, all three Python tools, and the docs.

> **Where the authority is.** The decision itself is D60 and D61 in
> `QUESTION_BANK_DECISIONS.md` — that is the law, and this file is only the
> working note behind it. If the two ever disagree, the log wins.

---

## 1. Why this came up

D54 (`emphasis`) and D55 (`image`) were each correct for one symptom. But the
source material arrives as **HTML**, and it carries more than underline:

- inline marks — `<u> <em> <strong> <s> <span class=…>`
- scripts — `<sub> <sup>` (chemistry is a real subject; valency is broken without this)
- block structure — `<p> <div> <br>` (a passage that is really four paragraphs)
- figures — `<img>`

So the pipeline was being extended **one field per formatting need**: underline,
then image, then bold in explanations, then paragraph breaks, then sub/superscript.
Each one is a schema change, a loader rule, an OpenAPI change, and a special case
every consumer has to learn.

## 2. The trap in the evidence we already had

**The bank cannot tell us what is coming.** It is the output of a policy, not a
sample of reality. Three measured facts:

1. `clean()` (harvest.py:138) runs `re.sub(r"<[^>]+>", " ", fragment)` — every tag
   becomes a space. Then line 144 runs `re.sub(r"\s+", " ", …)` — **all** whitespace
   collapses, so `<p>` boundaries die in the same step.
2. That single line is why D54 exists at all. Markup loss is not a one-off defect;
   it is the harvester's standing policy.
3. `FIGURE_HINT` (harvest.py:212) **refuses and drops** any row whose stem says
   "diagram below" with no image. Correct as an integrity rule — but it means
   diagram questions are *absent from the bank*, not rare in the wild.

> **Rule for whoever picks this up: never infer "what content looks like" from
> `data/questions.json`.** It has been filtered twice.

## 3. What was decided (D60 / D61)

One shape, everywhere:

```rust
pub struct RichText { pub text: String, pub inline: Vec<Inline> }
pub struct Inline  { pub start: u32, pub len: u32, pub kind: InlineKind }
pub enum InlineKind {
    Bold, Italic, Underline, Strike, Subscript, Superscript,
    Image { url: String },
}
```

Applied to stems, every option, `key_point`/`body`/`trap`, passage text and
novel-question text. `emphasis` becomes an `Underline` mark; `image` becomes an
`Image{url}` mark. **Both are deleted, not deprecated** — nothing consumes the API
yet, so the break is free.

Three rules that make it enforceable:

- offsets are **Unicode characters**, never bytes; a mark running past the end of
  its text is refused at load (D54's integrity bar, moved — not lowered)
- marks may **share an identical range** (bold+underline) but **never partially
  overlap**
- **paragraph breaks are `\n\n` in plain text.** No block layer. A blank line
  already means that to everyone, and a second structural concept is the
  complexity this decision exists to remove

## 4. Why this and not inline markup

Checked against real assessment APIs, not intuition:

| API | Stem | Approach |
|---|---|---|
| **Google Forms** | `Item.title` — plain `string` | **no rich text at all**, deliberately |
| **Canvas LMS** | `question_text`, `answer_text`, comments — plain | no emphasis field |
| **Examplary** | accepts a **safe HTML subset**, strips the rest | inline |
| **Quizlet** | literal markers `*bold*` `_underline_` | inline — and [documented consumer bug](https://github.com/ImGajeed76/quick-cards/issues/8) where asterisks render literally on screen |

The two teams that chose inline markup are the two that leaked it. And the one
piece of good news in our own data: **`\(…\)` already survives**, because the
source ships LaTeX as plain characters rather than tags, so `clean()` passes it
through. 100 stems, 251 options carry it today.

**Markdown is a trap, not the answer** — CommonMark has no underline at all, so
emphasis would have to mean something it does not mean.

## 5. Implementation surface (not yet touched)

- `src/bank/model.rs` — `Question.text`, `Choice.text`, `Explanation.{key_point,body,trap}`,
  `Passage.text`; **delete** `emphasis: Option<String>` (:125) and `ImageRef` (:84)
- `src/bank/view.rs` — `RenderedQuestion` (:24), `RenderedNovelQuestion` (:62, which
  currently has **neither** `emphasis` nor `image` — a real gap, not an oversight)
- `src/bank/json.rs:369` — the current substring validator becomes a bounds check
- `src/api/openapi.rs` + regenerate `site/openapi.json`
- `src/import.rs` (:240–242 sets `emphasis: None`)
- `data/questions.json` — **2,289 rows** migrate `{text}` → `{text, inline}`
- `tools/harvest.py` (`clean()` → `clean_inline()` + `clean_blocks()`),
  `tools/propose_emphasis.py` (proposes `emphasis` substrings), `tools/review.py`
- `site/src/content/docs/docs/guides/` — see §7

## 6. Open questions (answer before implementing, not during)

1. **Does `clean()` get paragraph breaks from `<p>`, `<br>`, or both?** `<br>` is
   a line break, `<p>` a paragraph — collapsing both to `\n\n` loses the
   distinction. Lean: `<p>` → `\n\n`, `<br>` → `\n`.
2. **Should `image` keep an `alt`?** D55 called it free later because `ImageRef`
   was a struct; as an enum variant it costs one field, still free. Say whether
   it ships now.
3. **Do marks belong on novel-question explanations too?** `RenderedNovelQuestion`
   embeds an `Explanation`, so yes by construction — confirm that is intended.

## 7. Suggested order

1. Rust types + load-time bounds/overlap validation, with tests **before** any data moves
2. Migration script for the 2,289 rows; run it; verify counts and a spot-check
3. `tools/` updates, then a full clean harvest to prove D61 end to end
4. Regenerate `site/openapi.json`, confirm the reference builds
5. **Only then** rewrite the docs — `emphasis` is undocumented in the guides today,
   and the LaTeX sentence under-describes which fields may carry math
6. `cargo test` green, clippy clean, then commit

## 8. Do not

- **Do not deprecate.** No alias, no `#[serde(alias)]`, no shadow field. The user
  was explicit: break now, keep it clean.
- **Do not add a block/rich-text document model.** D60 is deliberately the thinnest
  thing that covers every case named. `text` stays plain so grep, diff, equality
  and substring search keep working.
- **Do not let `emphasis` come back** on explanations, passages or options as a
  special-case field. That is the exact drift D60 exists to prevent.