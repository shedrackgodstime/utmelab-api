# Pilot 002 — Demand, Supply, and Equilibrium (Economics)

Status: pilot/draft. Not production data. Purpose: test a **true Model** case in OpenLearn, plus external placements and a Procedure candidate.

Source: `utmelab-bank/data/concepts/eco_demand_supply_equilibrium.json` (“Demand, Supply, and Equilibrium in Markets for Goods and Services”).

## What this pilot tests

- A genuine **Model** (components, assumptions, scope, predictions, limitations) — not just a convention/frame.
- Concept vs quantity distinction (demand vs quantity demanded; supply vs quantity supplied).
- Empirical law Statements (law of demand, law of supply) with ceteris-paribus conditions.
- Derived Statements/predictions from the model (surplus/shortage adjustment).
- A Procedure candidate (locate equilibrium from schedules/curves).
- External placement records (JAMB economics topics) living outside core.
- Source attribution/license + fidelity notes.

## Deliberate pilot variation

Definitions are embedded in Concept records (`definition` + `definition_fidelity`) instead of separate definition Statements. Review question: should definitions be separate Statements for this domain, or is embedding acceptable for Concept-heavy material?

## Files

- `source-attribution.json`
- `source-fidelity.json`
- `concept-demand.json`
- `concept-quantity-demanded.json`
- `concept-supply.json`
- `concept-quantity-supplied.json`
- `concept-equilibrium.json`
- `statement-law-of-demand.json`
- `statement-law-of-supply.json`
- `statement-equilibrium-condition.json`
- `statement-above-equilibrium-surplus.json`
- `statement-below-equilibrium-shortage.json`
- `model-demand-supply-equilibrium.json`
- `procedure-locate-equilibrium.json`
- `study-topic-section.json`
- `external-placement.json`

## Review questions

1. Is `model:demand-supply-equilibrium` truly a Model under the convention (components + assumptions + predictions + scope)? Does it need limitations stated more explicitly?
2. Should demand/supply definitions be separate definitional Statements instead of fields on Concept records?
3. Are the two adjustment claims (surplus/shortage) correctly `derived` Statements from the model?
4. Is “locate equilibrium” a Procedure or just an application of the equilibrium definition?
5. Does the external layer cleanly hold JAMB topics without contaminating core identity?
6. Is the license (`CC BY-NC-SA 4.0, non-commercial staging`) a blocker for intended use?

## Not done

- No migration/schema commitment.
- No app/tooling.
- No full block audit or extraction of demand/supply shifts (separate capture).
