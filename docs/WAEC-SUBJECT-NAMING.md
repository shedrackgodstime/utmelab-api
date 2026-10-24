# WAEC subject naming

WAEC's current Nigerian entry regulations are the authority for display names.
The examiner subject listing is used as a secondary check for paper-level names.
The bank must not create a subject because a source or an old database row uses
a different label.

## Current naming decisions

| Official or paper label | Bank slug | Decision |
| --- | --- | --- |
| General Mathematics | `general-mathematics` | Canonical production slug after the duplicate-row merge. |
| Agricultural Science | `agricultural-science` | Use the syllabus and paper name. WAEC's entry list shortens the category to Agriculture. |
| Financial Accounting | `financial-accounting` | Keep the paper name used by the WAEC examiner listing and production. |
| Visual Arts | `visual-arts` | Use the examiner subject name; the entry list shortens it to Visual Art. |
| Catering Craft Practice | `catering-craft` | Keep the production/source slug; use the entry-list display name Catering Craft. |

The following must be treated as separate naming checks before ingestion:

- Accounting versus Financial Accounting
- Agriculture versus Agricultural Science
- Visual Art versus Visual Arts
- Catering Craft versus Catering Craft Practice
- Nigerian History versus History
- Hausa, Igbo and Yoruba versus their paper labels Hausa Language, Igbo Language and Yoruba Language

Production remains the authority for the slug used by the bank. A display-name
correction must not silently rename or duplicate a production subject.
