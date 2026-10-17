# Questions about the codebase

Written while reading `src/` and `prototyping/` at commit `49a7963`. Not
findings. These are things I could not settle by reading, and several of them
change what I would advise next.

Answers can be short. A one-liner in place is enough, or edit the question
directly if it is asking the wrong thing.

---

## 1. Which surfaces count as done?

I am treating this as a question about scope rather than about code, because
getting it wrong wastes everyone's time.

Some parts of this service are filled in and being worked on properly. Others
are started and will grow, and reading them as finished produces findings that
are just "this is not finished yet".

Which routes and which modules are complete enough to be held to the standard
you want them at, and which are still filling in? I will not raise anything
against a surface you tell me is in progress, including auth gaps, missing
pagination, or handlers that are thinner than the finished ones.

`src/api/v1/novels.rs` is the case that made me ask: `list` and `detail` take
no `AuthedKey` while the nested `questions` handler does. If novels is a
surface still being built, that is the answer and the question closes.

> **Answer.** Scope is everything under `src/`; there is no surface I am
> deliberately leaving half-built. `prototyping/` and `utmelab-api-old/` are
> baseline and archive, not surfaces. The `novels` asymmetry was an oversight,
> not a preview: `list` and `detail` now take `AuthedKey` and
> `require(SCOPE_READ_CATALOG)`, so every `api/v1` read is key-gated. Raise
> anything you find in `src/`.

## 2. Health probe timing under load

`prototyping/NOTES.md` line 58 records that with the gate in place, burst
queueing still delayed everything on 4 workers, and `/health` timed out at 8s
during a `-c200` run. It proposes two options: lower `DB_MAX_CONCURRENT`, or
serve health from a separate listener.

`src/` keeps `DB_MAX_CONCURRENT` at 16 and serves `/health` from the same
listener as everything else.

Was either mitigation dropped on purpose? The prototype's `/health` was a
static string and much cheaper than the real readiness check, so the comparison
may not carry over.

> **Answer.** Dropped on purpose. `/health` is a constant handler mounted before
> the contract guard and outside the DB gate: it awaits nothing on the guest or
> the DB, so a `-c200` burst of DB-bound handlers cannot make it queue. The
> readiness work moved to `/ready`, which does touch the replica. Measured on
> this box with the gate closed: `/health` ~0.5 ms while `questions` was
> shedding. The mitigation was unnecessary once the cheap probe and the DB
> probe were separated.

## 3. `DB_MAX_CONCURRENT`

The same note suggests 8 rather than 16. What is it set to on the VPS, and what
was the reasoning for the value that was chosen?

> **Answer.** 16 (`DEFAULT_DB_MAX_CONCURRENT`, and `.env` on this box). It is the
> ceiling on concurrent DB work and the connection pool is sized to match it: 8
> left reads queueing behind the pool on a small worker count, 16 keeps more
> reads in flight without overrunning the sync engine's single IO worker that
> pulls and pushes share. Tuned, not settled — the pending capacity pass will
> confirm it under load. I cannot read the VPS value from here; it comes from the
> same `.env` shape.

## 4. Turso internal tables

`prototyping/NOTES.md` line 51: `/db-sync` reported 5 tables against 1 for
remote, "local file includes internal sync bookkeeping tables".

`src/store/catalog.rs::fetch_table_names` filters with
`name NOT LIKE 'sqlite_%' AND NOT LIKE 'turso_%'`. Is that filter matched to
the names turso actually uses for its internal tables?

This is worth pinning down because the result is exposed two ways, both to any
valid key: `GET /v1/meta/tables` and the `mcp` `list_tables` tool.

> **Answer.** No, the filter did not match. The engine's bookkeeping lives at
> `turso_sync_last_change_id` (caught) and `__turso_internal_mvcc_meta`, which
> starts `__turso_` and matched neither pattern (`LIKE` also treats `_` as a
> wildcard, so the pattern was looser than it read). Fixed deny-by-default:
> `core::catalog::INTROSPECTABLE_TABLES` is the single allowlist, and both
> `fetch_table_names` and `fetch_rows` consult it.
>
> While pinning this I found the same surface was a data hole, not just a name
> leak: `fetch_rows` ran `SELECT * FROM "{table}"` for any `ident`-valid name,
> so `GET /v1/meta/rows/api_keys`, `/dashboard_users`, and `/sessions` returned
> credential and token hashes to any `read:catalog` key — which is the default
> scope. Those now answer 404; `questions`/`novel_questions` (which carry the
> withheld answers) are off the allowlist; nothing off the allowlist is listed.
> Tests pin both the predicate and the store guard.

## 5. Unpushed writes and `pull()`

The Turso sync docs describe `pull()` as: roll the local database back to the
last synced state, apply remote changes, then replay unpushed local changes on
top. All-or-nothing.

`src/store/write.rs::execute_write` writes locally, then pushes, and its module
comment says a push failure means "local row exists, cloud lags until the next
push".

If the push fails and a background `pull()` then runs, is that local row
guaranteed to survive the rollback-and-replay? The comment asserts it is. I
cannot tell from the code whether the assertion holds for a row whose push
never succeeded.

> **Answer.** It holds, and where the engine cannot replay it errors instead of
> dropping. `turso_sync_engine` 0.8.3 `apply_changes` is the rollback-and-replay
> the docs describe — explicit "collect local changes for replay" and "replay
> local changes" phases — and its own `local_only` test shows a never-pushed
> change surviving an apply. The unwired path returns
> "replace-base page apply with pending local CDC changes is not wired yet: …
> need replay" rather than discarding. Two caveats: a replay failure surfaces as
> an error, not silent loss; and in this process the guarantee is belt-and-braces
> anyway, because `execute_write` holds `write_mutex` across `execute` + `push`
> and the pull loop takes the same mutex.

## 6. Retryable write errors

`src/store/mod.rs::is_busy` retries when the message contains `locked` or
`busy`.

The turso repo's own `concurrent_writes.rs` example treats three things as
retryable: `Error::Busy`, `Error::BusySnapshot`, and a message containing
`conflict`.

Does a write conflict on this engine actually surface as one of the strings
`is_busy` matches? If conflicts arrive as `conflict`, they would skip the retry
and go straight to the client.

> **Answer.** It could miss one, and no longer will. `upstream()` erases the
> `turso::Error` variant into a `String`, so `is_busy` only ever matches text.
> Busy/BusySnapshot print "database is busy" (matched), but the engine branches
> on a `"conflict"` status for commit conflicts and the old matcher lacked
> `conflict` — those skipped the retry and went straight out. Widened to also
> match `conflict`. The durable fix is to classify `Error::Busy`/`BusySnapshot`
> before stringifying; that needs the store closures to carry the typed error,
> so it is a follow-up, not a one-liner.

## 7. Subject pool size

`store::catalog::subject_rows` returns a whole subject's questions with no
LIMIT, and `core::papers::assemble` works over the whole pool. That is
understood for paper assembly.

Roughly how many questions does the largest subject hold today, and what is it
expected to be at launch? It bears on whether this stays a deliberate design or
becomes the memory ceiling on a 1.5 GB box.

> **Answer.** Largest today (2026-10-17): `computer-studies` (JAMB) 193 questions,
> then `use-of-english` 167, `biology` 114, `government` 111,
> `literature-in-english` 108. A whole-subject read is therefore ~200 rows, low
> tens of KB — no memory ceiling at this scale, so whole-pool assembly stays a
> deliberate design. If a subject ever reaches the thousands, `subject_rows` is
> the single place to page.

## 8. Response sizes and the concurrency limit

`src/api/middleware.rs` collects every `GET` response body into memory so it
can hash it, capped at 1 MiB. What is the largest response actually served, and
what is `CONCURRENCY_LIMIT` set to on the VPS rather than left at the 1000
default?

> **Answer.** `.env` sets `CONCURRENCY_LIMIT=1000` (the default): it caps
> simultaneous in-flight requests, not DB work — the DB gate is the real
> throttle. Largest GET is a 200-question page (`questions?per_page=200`, the
> explanation-bearing worst case); the 200 largest question rows sum to 117 KB of
> text+options before JSON overhead, well under the 1 MiB collect backstop, so no
> served response approaches the cap.

## 9. Cookies in production

`src/auth/session.rs` sets `HttpOnly; SameSite=Lax`, with `Secure` only when
`COOKIE_SECURE` is on. `.env.example` has `COOKIE_SECURE=0`.

Is `COOKIE_SECURE=1` set in the production systemd environment? If Caddy is the
only path in, that closes it.

> **Answer.** I cannot confirm the VPS from here. Locally `COOKIE_SECURE` is
> unset (false) and `.env.example` ships `0`. Flagging it as a deployment action,
> not a code fix: set `COOKIE_SECURE=1` in the systemd environment, since the code
> only sets `Secure` when that is on. Caddy-only ingress closes the other half.

## 10. Instance count

Is the single instance a deliberate constraint or a current state?

It matters in two places. The in-process `write_mutex` is a complete guard
against a pull interleaving a local write only while there is one process; two
instances pulling and pushing the same cloud database have no shared lock. And
Turso resolves conflicts last-push-wins, which would then apply across
instances rather than being impossible by construction.

> **Answer.** Deliberate for now, and the design depends on it. `write_mutex` is
> process-local: "a pull cannot interleave an unpushed local write" is true only
> while there is one process. Two instances sharing the cloud DB have no shared
> lock, and last-push-wins would apply across them. So single instance is a
> constraint of the current write path; scaling out needs a different
> coordination story, not just another replica.

## 11. WAL growth

The sync API exposes `stats()` (including `mainWalSize`, `revertWalSize`,
`cdcOperations`, `revision`, `lastPushUnixTime`) and `checkpoint()`, documented
as compacting the local WAL to bound local disk usage.

`src/state.rs::Metrics` tracks two pull counters and one timestamp. Nothing
calls `checkpoint()`, and `stats()` is not read anywhere. `docs/NOTES.temp.md`
records the `-wal` file sitting at 0, which suggests the engine checkpoints on
its own in current usage.

Is relying on that fine, or should WAL size and pending-change count be on the
status surface? On a 1.5 GB box those are the numbers worth watching.

> **Answer.** Relying on the engine is fine today: we have seen `-wal` at 0, and
> the engine checkpoints after applies. The numbers are still worth watching, so
> the right move is to surface them read-only on the admin status
> (pending-change count, WAL size, last push time) and keep `checkpoint()` out of
> our hands — forcing a checkpoint under load is worse than letting the engine
> decide. A small status-surface addition, not a correctness gap.

## 12. Decisions written down elsewhere

I have read `src/`, `prototyping/NOTES.md`, `docs/NOTES.temp.md`, `Cargo.toml`,
`.env.example`, and the workflow files.

Is there a design doc, an ADR set, or a roadmap outside this repo that states
intent for what is not built yet? Several calls would read differently against
a stated plan.

> **Answer.** No external design doc, ADR set, or roadmap. The in-repo record is
> `docs/NOTES.temp.md` (backlog + decisions) and `reviews/` (this file);
> `prototyping/` is the pre-`src/` baseline. If a plan is wanted, the honest move
> is to write it down here rather than assume one exists.

---

## Checked, looks right

Recording these so nobody repeats the work.

- The layer stack in `src/routes/mod.rs`. Repeated `.layer()` calls run
  bottom to top, and the comment about the slow timeout being outermost is
  consistent with that.
- Every `unwrap` and `expect` in `src/` sits inside `#[cfg(test)]`, which is
  what `docs/NOTES.temp.md` claims.
- The DB gate uses `try_acquire_owned`, so it fails fast instead of queueing.
- `execute_write` and `execute_ddl` hold `write_mutex` across the `push()`, not
  only the local write.
- SIGTERM is handled alongside Ctrl-C, which the prototype did not have.
- `verified_predicate` and `scope_predicate` interpolate only string literals
  and integers. The one user-supplied identifier, `fetch_rows`, is checked with
  `core::validate::ident` before it reaches SQL. (It is now *also* gated by the
  `core` allowlist, per Q4 — `ident` alone was not enough.)
- No `std::sync` lock guard is held across an `.await` anywhere in `src/`.
- `mimalloc` is absent, which is correct: `prototyping/NOTES.md` line 47 records
  that turso installs its own global allocator.