# Rust service guardrails

**Scope:** the Rust API and its runtime dependencies only.

The site and `utmelab-bank` are outside this contract.

## Scale reference

The service must remain healthy when the remote content database reaches 4 GB.
The 4 GB figure leaves only about 1 GB below a 5 GB database limit. It is a
design reference, not permission to assume that the whole database fits in
memory.

The API serves a local synced replica. The replica is a serving copy, not an
application cache and not a second source of truth.

## Core rules

### Bounded memory

- A request must not load the whole content database into memory.
- List endpoints must paginate in SQL.
- Samples must use bounded-memory selection.
- Paper assembly must load only the candidate rows required for the result.
- Every request body, response collection, query limit, and text field needs a
  bound.
- A large database must increase query work, not process memory without a
  deliberate budget decision.

### Query discipline

- Filter, sort, aggregate, and limit in SQL where possible.
- Avoid unbounded `SELECT` operations on request paths.
- Avoid loading all IDs merely to choose a small random sample.
- Add indexes for filters and ordering that serve real API routes.
- Measure query plans and latency against representative large fixtures.
- Do not trade correctness for `ORDER BY random()` or another uncontrolled
  full-table operation.

### Single sources of truth

Each rule must have one owner.

- Route ownership belongs to the router inventory.
- Public and protected route behavior belongs to their router layers.
- Scope names belong to `src/auth/mod.rs`.
- Error codes and status mappings belong to `AppError`.
- Read columns and schema expectations belong to `store/schema.rs`.
- Database access belongs to `src/store/`.
- Domain decisions belong to `src/core/`.
- Runtime defaults belong to `src/config.rs`.
- OpenAPI is derived from the handlers and checked against the route inventory.

Consumers should not need to know which database query, handler, or surface
implements a rule.

### Reuse before duplication

- Reuse one handler when HTTP and MCP expose the same operation.
- Reuse one scope check for every surface that performs the same action.
- Reuse shared pagination, validation, decoding, error, and rendering logic.
- Do not copy SQL, response shapes, authentication rules, or configuration
  parsing into parallel modules.
- A new abstraction must remove a real duplication or protect a real boundary.

### Failure containment

- A slow or unavailable remote database must not block the entire process.
- Reads must use bounded timeouts and bounded concurrency.
- Saturation should return a controlled `503`, not queue without limit.
- Schema mismatch must fail closed for data routes.
- A failed sync must leave the last trusted replica available when safe.
- Idle sync may sleep to save VPS and remote resources, but the first database
  request after sleep must perform one locked refresh before serving.
- Active sync uses long-polling rather than fixed-interval remote requests.
- Long-poll duration must stay bounded, and write contention must remain
  observable through admin telemetry.
- Small discovery metadata may be cached only when bounded and keyed to the
  replica version. Question and passage content must remain database-backed.
- Handler panics must not terminate the process or drop unrelated requests.
- Internal errors must be logged without exposing database details or secrets.

### Write safety

- All writes use one guarded path.
- A local commit followed by a failed remote push must have explicit retry
  semantics.
- Retrying a client request must not create duplicate keys, reports, or other
  side effects.
- Mutating operations should use idempotency keys when a retry can repeat a
  side effect.
- Content reads and account writes must remain separate responsibilities.

### Security boundaries

- Master credentials stay outside client applications.
- Authentication must be enforced at the router boundary and again at the
  operation boundary when a capability differs.
- Scopes must match the operation they protect.
- Admin traffic must not silently bypass all abuse controls.
- Cookies must remain secure, HTTP-only, and same-site where applicable.
- Proxy-derived client identity is valid only while the loopback and proxy
  trust assumptions remain true.
- Logs must never contain raw API keys, passwords, sessions, or bearer tokens.

## Capacity expectations

The service should be evaluated against a large synthetic replica that models
4 GB of content, even when local development uses a much smaller database.

The capacity test must measure:

- resident memory during cold start and steady serving;
- replica sync time and disk growth;
- question listing and sampling;
- syllabus and coverage reads;
- paper assembly and scoring;
- concurrent reads;
- database saturation behavior;
- recovery after a failed pull or push.

The important result is not only average latency. The service must keep bounded
memory and bounded tail latency when the database is large or traffic exceeds
the configured capacity.

## Review questions

Every Rust service change should answer:

1. Does this load more data than the response needs?
2. Does this duplicate a rule that already has an owner?
3. Can a retry repeat a side effect?
4. What happens when the database is slow, unavailable, or has the wrong
   schema?
5. What happens at 4 GB of content and beyond?
6. Is the behavior covered by a focused test or measurement?
