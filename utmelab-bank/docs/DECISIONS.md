# Decisions

Sealed 2026-10-21. These are the decisions. Where a decision is someone
else's to make, it says so and the bank is built so it does not block on it.

---

## D1. What the bank is

A content factory. It takes content in, decides whether it is sound,
enriches it, checks it, and hands over a **ready bundle**: content that is
complete, correct, placed and identified, so that placing it is a mechanical
step for whoever does that.

The bank does not serve, does not place, and does not build the API.

## D2. The stages

| Stage | What it does |
|---|---|
| **Intake** | Take content from a source and put it in the canonical shape. No judgement yet. |
| **Gates** | Decide whether it is sound, and say why when it is not. |
| **Review** | Check the content and record the check. |
| **Ready** | The output. A bundle with the counts and the reasons attached. |

## D3. The gate is strict, machine only, and total

**The default is fail.** Every rule that can detect a defect can block a row.
No rule is advisory. A flag that never blocks is a warning, and warnings get
ignored at volume.

The gate runs on 100% of rows. No human is in this loop. Every refusal is
counted per rule, so the weak sources are visible and fixable.

**Two kinds of refusal.**

*Defects.* Objective. A mark past the end of its text, an answer that names
no option, an unknown subtopic, a duplicate hash. The normal resolution is a
fix to the content.

*Judgements.* A rule that cannot tell a real defect from an ordinary word.
The figure hint is the only one. The row is refused, the refusal names the
rule, and a person says why it is fine.

**Both go to the same person, and both are resolved the same way.** The gate
refuses, and the person either fixes the content or records a clearance with
a reason. One queue, one mechanism, and nothing leaves the bank without a
person having looked at it. The severity stays on the issue, so the counts
still say what was objectively broken and what needed judgement.

**The clearance is recorded, never silent.** It names the rule, the person
and the reason, so the decision survives the row and the counts stay honest.

**Rules get tightened, queues do not grow.** A judgement rule that produces
a large false-positive class gets rewritten until the class is acceptable.
Only the residue goes to a person.

## D4. The human resolves the refusals, samples the passes, and sets policy

A person cannot review 100,000 questions. One to three minutes each is
1,500 to 5,000 hours, and there is one of them here whose job is the code.

So the human's job is three things, and none of them is a pass over the
content.

1. **Resolves the refusals.** The queue is the gate's failures, not the
   content. On the live bank that is 65 of 2,243 rows, and it is the only
   queue.
2. **Samples the passes.** Checks a sample to measure the AI's agreement
   rate, and settles the disagreements.
3. **Sets policy.** Decides the agreement rate below which content does not
   move.

The output of the human is a resolved queue, a number and a threshold, not a
queue position per row.

## D5. The AI review is the review at volume

The bank checks every row, at volume, for the things only judgement can
catch: the answer is correct, the explanation is right and teaches, the
question is answerable as written, the figure description matches the
figure, the topic placement is right.

Each check is recorded with its kind, its scope, the model that produced it
and the reason. A bulk run and a single careful check are different evidence
and stay different kinds.

**The AI's verdict is the review. The human audits the AI.**

## D6. The serving policy is not ours, and the bank does not wait for it

The API counts only a human pass toward servable. That is the API's contract
and it is not ours to change from here.

The bank produces content with an AI pass and a clear record of what a human
still has to sign. A bundle carries both the AI records and the human's
sample audit, so the evidence for a policy change comes with the content
rather than after it.

Until that policy changes, the bank still fills the bank. The content is not
wasted, it is staged and audited.

## D7. Re-review is continuous

Content in production is not finished. The bank re-checks live content on a
schedule: the hash drift check, the near-duplicate check against new
content, and the AI re-review of live rows.

A live row that fails a re-check comes back as work. The bank is a loop, not
a one-shot factory.

## D8. The catalogue is the placement authority

The catalog is read from production, never copied and never invented. A
question with no subtopic is not attributable to anything.

A topic's weight decides whether it is published. Today 3 of 583 topics
carry weight, so most verified questions sit on unpublished topics. That is a
catalog fact, not a content defect, and the bank does not paper over it.

## D9. Dedupe runs on two fingerprints

The **exact hash** catches a row copied verbatim. It never collides, so it is
a lookup, and the bank keeps a local index of the hashes it holds and the
hashes production holds so the check stays a lookup.

The **near-duplicate fingerprint** catches the reworded copy, which is the
duplicate that actually happens. At volume this is the rule that matters.

Both counts are reported. A duplicate is counted, never silently overwritten.

## D10. The shape of the content

* One `RichText { text, inline }` for a stem, every option, every
  explanation part, a passage's text and a novel question's text.
* A mark is `{start, len, kind}` with a flat lowercase kind. Offsets count
  Unicode characters. Identical ranges are allowed, partial overlap is not.
* **The key is `inline`.** The live tooling reads `inline`, so the bank
  writes `inline`.
* A passage is its own object with a kind, linked by id, because 28
  questions share 8 passages and `kind` is what tells a consumer how to read
  one.
* A figure is a zero length mark with a url and a position. The position is
  data, set by the reviewer, never inferred from the prose.
* `text_norm` is the full-Unicode lowercase. Python's `.lower()`, never
  SQLite's ASCII `lower()`.

## D11. The fingerprint is fixed

The content hash is the receipt that ties a review to the content it
reviewed. A content edit voids the review, so the hash has to be exact.

The algorithm is production's, unchanged. It is verified three ways on all
2,243 live rows, and the live contract test keeps the three agreeing.

## D12. Media: source url now, the bank owns the asset

The bank does not upload yet. The mark carries the source url, and that
renders today.

The bank does own the asset: the bytes, the sha256, the mime type, the alt
text, a description. When the asset exists, the url is swapped for the
bank's own at handover. Not urgent, and it does not block anything else.

## D13. Out of scope

* The Rust. We read it to learn the shape. It is an MVP in progress, so the
  design hangs on the content, not on its internals.
* Promotion. The bank stops at ready.
* Placing content in the served tables.
* Human verification writes to the served tables.

---

## The plan of record

1. **The gate.** Strict, machine only, 100% of rows, with the refusal counts.
2. **The passage as its own object.**
3. **The `inline` rename.**
4. **Dedupe**, exact and near-duplicate, with a local index.
5. **The AI review step**, wired to a task.
6. **The ready bundle**, with the counts and the reasons.
7. **The report consumer and the drift check.**

Media waits. It renders today, and it blocks nothing.

## The open decisions, and who owns them

| Decision | Owner | What the bank does meanwhile |
|---|---|---|
| Does an AI pass count toward servable? | the API's contract | Produces the content, records the AI pass, and ships the human's sample audit as the evidence for the change. |
| Who places a ready bundle, and when? | separate work | Makes the bundle self-describing and mechanically placeable, and idempotent. |
| What agreement rate is good enough? | the human | Measures it on a sample and reports it. |

None of them blocks the gate, and none of them blocks filling the bank.
