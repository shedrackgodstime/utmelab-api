# Questions about the codebase

Written while reading `src/` and `prototyping/` at commit `49a7963`. Not
findings. These are things I could not settle by reading, and several of them
change what I would advise next.

Answers can be short. A one-liner in place is enough, or edit the question
directly if it is asking the wrong thing.

---

## 1. Auth on the novel routes

`src/api/v1/novels.rs`. `list` and `detail` take no `AuthedKey`; the nested
`questions` handler does. Every other read route on that surface requires a
key.

Is that deliberate? If yes, a comment saying why would stop the next reader
from reading it as an oversight.

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

## 3. `DB_MAX_CONCURRENT`

The same note suggests 8 rather than 16. What is it set to on the VPS, and what
was the reasoning for the value that was chosen?

## 4. Turso internal tables

`prototyping/NOTES.md` line 51: `/db-sync` reported 5 tables against 1 for
remote, "local file includes internal sync bookkeeping tables".

`src/store/catalog.rs::fetch_table_names` filters with
`name NOT LIKE 'sqlite_%' AND NOT LIKE 'turso_%'`. Is that filter matched to
the names turso actually uses for its internal tables?

This is worth pinning down because the result is exposed two ways, both to any
valid key: `GET /v1/meta/tables` and the `mcp` `list_tables` tool.

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

## 6. Retryable write errors

`src/store/mod.rs::is_busy` retries when the message contains `locked` or
`busy`.

The turso repo's own `concurrent_writes.rs` example treats three things as
retryable: `Error::Busy`, `Error::BusySnapshot`, and a message containing
`conflict`.

Does a write conflict on this engine actually surface as one of the strings
`is_busy` matches? If conflicts arrive as `conflict`, they would skip the retry
and go straight to the client.

## 7. Subject pool size

`store::catalog::subject_rows` returns a whole subject's questions with no
LIMIT, and `core::papers::assemble` works over the whole pool. That is
understood for paper assembly.

Roughly how many questions does the largest subject hold today, and what is it
expected to be at launch? It bears on whether this stays a deliberate design or
becomes the memory ceiling on a 1.5 GB box.

## 8. Response sizes and the concurrency limit

`src/api/middleware.rs` collects every `GET` response body into memory so it
can hash it, capped at 1 MiB. What is the largest response actually served, and
what is `CONCURRENCY_LIMIT` set to on the VPS rather than left at the 1000
default?

## 9. Cookies in production

`src/auth/session.rs` sets `HttpOnly; SameSite=Lax`, with `Secure` only when
`COOKIE_SECURE` is on. `.env.example` has `COOKIE_SECURE=0`.

Is `COOKIE_SECURE=1` set in the production systemd environment? If Caddy is the
only path in, that closes it.

## 10. Instance count

Is the single instance a deliberate constraint or a current state?

It matters in two places. The in-process `write_mutex` is a complete guard
against a pull interleaving a local write only while there is one process; two
instances pulling and pushing the same cloud database have no shared lock. And
Turso resolves conflicts last-push-wins, which would then apply across
instances rather than being impossible by construction.

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

## 12. Decisions written down elsewhere

I have read `src/`, `prototyping/NOTES.md`, `docs/NOTES.temp.md`, `Cargo.toml`,
`.env.example`, and the workflow files.

Is there a design doc, an ADR set, or a roadmap outside this repo that states
intent for what is not built yet? Several calls would read differently against
a stated plan.

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
  `core::validate::ident` before it reaches SQL.
- No `std::sync` lock guard is held across an `.await` anywhere in `src/`.
- `mimalloc` is absent, which is correct: `prototyping/NOTES.md` line 47 records
  that turso installs its own global allocator.