# Pilot 003 — The Fundamental Theorem of Calculus (theorem + proof)

Status: pilot/draft. Not production data. Purpose: test a **theorem with proof** in OpenLearn, especially derived Statements and the Procedure/Study boundary for proofs.

Source: `utmelab-bank/data/concepts/math_integration_fundamental.json` (“The Fundamental Theorem of Calculus”).

## What this pilot tests

- A named theorem as a Concept anchor + linked theorem Statements.
- Statements with status `derived/proved`, explicit scope/conditions, and source fidelity.
- **Proof-as-Procedure vs specific proof-as-Study**: reusable proof method vs a particular derivation/walkthrough.
- A theorem with two parts (Part 1: integrals/antiderivatives; Part 2: evaluation theorem).
- External placements (JAMB/WAEC integration topics) outside core.
- Source attribution/license + fidelity notes.

## Deliberate pilot variation

The theorem’s key referenced concepts (`definite integral`, `antiderivative`) are **not defined in this capture**; they are assumed from prior sections. Their Concept records are marked `definition_fidelity: not extractable from this capture`. Review whether assumed/dangling definitions are acceptable in a pilot graph.

## Files

- `source-attribution.json`
- `source-fidelity.json`
- `concept-fundamental-theorem-of-calculus.json`
- `concept-definite-integral.json`
- `concept-antiderivative.json`
- `statement-ftc-part1.json`
- `statement-ftc-part2.json`
- `procedure-prove-ftc-part1.json`
- `procedure-prove-ftc-part2.json`
- `study-proof-ftc-part1.json`
- `study-proof-ftc-part2.json`
- `study-topic-section.json`
- `external-placement.json`

## Review questions

1. Is the **specific proof** correctly placed in Study (derivation/walkthrough), while the **reusable proof method** is a Procedure?
2. Are the theorem Statements correctly `derived/proved`, or should they be `definitional`/`empirical` in some sense?
3. Is `concept:fundamental-theorem-of-calculus` the right anchor, or should the theorem be a bundle with two separate theorem Statements and no Concept anchor?
4. Are assumed concepts (`definite integral`, `antiderivative`) acceptable as placeholders, or must definitions be extracted before recording the theorem?
5. Does the external layer cleanly hold JAMB/WAEC integration placements?
6. Is the license (`CC BY-NC-SA 4.0, non-commercial staging`) a blocker for intended use?

## Not done

- No migration/schema commitment.
- No app/tooling.
- No full block audit of examples/exercises; proof text summarized/condensed, not fully transcribed.
