# Docs IA Plan (pinned — do not drift)

Decision: exam bodies are DATA, not sidebar sections. One stable endpoint
surface; bodies + countries are enum filters. Growth = new catalog rows,
never redesign.

## Why (evidence)
- ALOC (aloc.com.ng, African exam API: WAEC/JAMB/NECO/POST-UTME) structures
  docs as: GETTING STARTED (intro/auth/pagination/migration) / API REFERENCE
  grouped by capability layers L1–L4, NOT by exam body / RESOURCES (errors,
  changelog, Swagger link, MCP, starter kits) / TUTORIALS & COOKBOOK.
  Exam coverage is one page + filter params. They do NOT dump openapi.json
  as the reference — curated pages + one external Swagger.
- Fern IA (multi-context): same API surface → one context + catalog; only
  split into "products" if surfaces fundamentally differ. New country ≠ new
  section unless its API differs. Additive URLs, reversible config.
- Scalar Starlight plugin (@scalar/starlight): one playground entry via
  scalarStarlight({ configuration: {url:'/openapi.json'}, pathname, label });
  supports MULTIPLE references, theming, auth try-it. Confirmed working path.

## Sidebar tree (intent-based, Diátaxis; slugs)
GETTING STARTED
  /docs                Introduction (what it is, who it's for)
  /docs/quickstart     First call in ~2 min: fetch a WAEC maths question
                       (curl + key; links to dashboard signin for the key)
  /docs/authentication API keys (get/rotate in dashboard), headers, key types
  /docs/environments   Base URLs, envs
  /docs/response       Response envelope: data / pagination / meta
  /docs/pagination     Cursors through banks
  /docs/handling-errors How to handle failures: retries, backoff, timeouts
                       (points to the full table at /docs/error-codes)
  /docs/limits         Rate limits & quotas (amounts when pricing lands)

EXAM CATALOG  ← WAEC / NECO / JAMB-UTME / POST-UTME / WAEC-Ghana ALL LIVE HERE
  /docs/catalog                 How coverage works; bodies are filters, not routes
  /docs/catalog/nigeria         WAEC, NECO, JAMB/UTME, POST-UTME (subjects, year ranges,
                                counts, codes)
  /docs/catalog/ghana           WAEC Ghana (subjects, year ranges, counts, codes)
  /docs/catalog/request         Coming soon / request coverage (future countries land here
                                as rows first, own page only when coverage is real)
  /docs/catalog/identifiers     Stable codes/slugs to pass as exam=/country= params
API REFERENCE (curated groups + ONE playground + spec download — NOT a spec dump)
  /docs/reference               How the reference is organized; auth for try-it
  /docs/reference/questions     List/get + filters (exam, subject, year, topic, difficulty)
  /docs/reference/catalog       Subjects, years, coverage counts
  /docs/reference/explanations  Fetch explanations
  /docs/reference/search        Full-text/topic search
  /docs/playground              Scalar interactive reference (plugin; themed; try-it key)
  /docs/spec                    Download OpenAPI 3.1 (Postman/Insomnia import)
GUIDES (task-based; grow freely, never restructure the tree)
  /docs/guides/filter           Filter by exam, subject, year
  /docs/guides/paginate         Walk a whole question bank
  /docs/guides/quiz             Build a timed quiz
  /docs/guides/cache            Cache + offline
RESOURCES
  /docs/errors                  Full error-code table
  /docs/changelog               Versioned changes
  /docs/glossary                Exam codes & terms

## Future-country extension rule (no redesign, ever)
1. New country/body ships as: enum values (exam=, country=) + catalog row/page.
2. NEVER new routes, sidebar sections, or version bumps for a coverage addition.
3. Catalog entry documents: code, country, subjects, year range, counts, example filter.
4. EXCEPTION: if a country needs a fundamentally different surface → add a
   second product space with switcher (Fern tier-2). Anticipated: no; planned: no.

## API-shape rule the docs impose on the Rust side (keeps tree stable)
- Routes stay body-agnostic: /questions, /questions/{id}, /subjects,
  /explanations/{id}, /search. Variety lives in query enums, not paths.
- Stable identifiers: exam codes (waec_ng, neco_ng, jamb, postutme, waec_gh),
  country codes (ng, gh, …), subject slugs. Documented once in Catalog.
- Spec hygiene = professional reference: every operation gets operationId,
  one-line summary, and at least one example (request + 200 + error),
  because Scalar renders those as the page. No summary → looks dumped.

## OpenAPI professionalism plan (your instinct, confirmed)
- Primary: hand-curated reference pages per capability group.
- Single Scalar playground entry (pathname/label set; brand accent; dark-mode
  aware; try-it sends the API-key header).
- Raw spec stays downloadable (GET /openapi.json) — Postman import, not sidebar.
- Later option: split Scalar into per-group references (multiple plugin
  instances) if the surface grows; only if needed.

## Deferred
- Pricing tiers/limits copy (until product exists); cookbooks/starter kits (later).
