# Newton’s Second Law — finish checklist (authored product unit)

Status: **finished (v1, authored)**. Reviewed against the project’s “finished topic” criteria.

## Scope
- Topic: Newton’s Second Law of Motion (concept of a system), as presented in OpenStax College Physics (m42073).
- In scope: Concept anchor + definitional Statements + the empirical law Statement + the “related to First Law” Statement + supporting Concepts (acceleration, net external force, mass, system, Newton’s First Law minimal) + external placement (none found) + usable Study page.
- Out of scope: full treatment of weight/free-fall derivations beyond what the Study page summarizes, projectile/other contexts, rotational analogs, exercises beyond the included practice prompts.

## Sources (attributed)
- `sources/attributions/source-openstax-m42073.json` (OpenStax College Physics, m42073; CC BY-NC-SA 4.0, non-commercial staging; attribution required). Study page cites this source.

## Artifacts (product tree)
- Knowledge concepts: `knowledge/concepts/concept-*.json`
- Knowledge statements: `knowledge/statements/statement-*.json`
- Knowledge relations: `knowledge/relations/relation-newtons-second-law-related-to-first-law.json`
- External: `external/placements/newtons-second-law.json` (content-based ID; no exam placements recorded; maps to core IDs if added later)
- Study (folder-per-topic, under `study/topics/newtons-second-law/`):
  - Metadata: `topic.json`
  - Topic outline: `topic.md`
  - Explanation: `explanation.md`
  - Examples: `examples/lawnmower.md`
  - Media: `media/` (optional)
  - Finish note: `FINISH.md`

## Criteria check (summary)
1. Authored in OpenLearn form from sources (not copied capture JSONs into product): yes.
2. Sources + license recorded: yes.
3. Identity/scope ours; external separate: yes.
4. Definition gate: all `complete` Concepts have `definition_refs` to `definitional` Statements: yes (validated).
5. Status/fidelity explicit: yes.
6. No dangling core refs in this set: yes (validated).
7. External mapped to core IDs only: yes.
8. Study separated and usable (outcome, explanation, worked example, practice, teaching/AI notes): yes (v1).
9. Validates: `python3 openlearn/work/validate.py openlearn/knowledge openlearn/external openlearn/sources/attributions openlearn/study` → 18 records, 0 errors, 0 warnings.
10. Reviewable note (this file): yes.

## Known gaps / follow-ups
- The relation “closely related to First Law” is kept as a vague typed relation + supporting Statement; could be tightened later.
- Practice items in Study are minimal (2 prompts); can be expanded with vetted exercises later.
- No exam/syllabus placements recorded for this capture; if/when mapped, add them in `external/placements/` pointing to these core IDs.
