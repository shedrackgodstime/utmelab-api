# UTME Lab Bank - Error Handling, Testing & Gaps Analysis

## 🔑 Environment Keys: What We Have

### Local `.env` (utmelab-bank/.env):
| Variable | Value/Status | Purpose |
|----------|-------------|---------|
| `GITLAB_TOKEN` | `[REDACTED]` | GitLab API access for media figures |
| `TURSO_PROD_DATABASE_URL` | `[REDACTED]` | Production catalog (read-only) |
| `TURSO_PROD_AUTH_TOKEN_READONLY` | `[REDACTED]` | Read-only token for production |
| `TURSO_BANK_DATABASE_URL` | `[REDACTED]` | Bank staging database |
| `TURSO_BANK_AUTH_TOKEN` | `[REDACTED]` | Bank database auth token |
| `GITLAB_MEDIA_REPO` | `shedrackgodstime/utmelab-bank` | GitLab repo for figure storage |
| `OCR_API_KEY` | `[REDACTED]` | OCR space API for figure text extraction |
| `NVIDIA_API_KEY` | `[REDACTED]` | NVIDIA provider API key |
| `NVIDIA_API_KEY_01` through `05` | Empty | Backup NVIDIA accounts (failover pool) |
| `OPENAI_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Default NVIDIA-compatible base URL |
| `OPENAI_MODEL` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Default text/vision model |
| `OPENAI_IMAGE_MODEL` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Default image model |
| `OPENAI_IMAGE_SECOND_MODEL` | `meta/llama-3.2-90b-vision-instruct` | Second witness image model |
| `GITLAB_HOST` | `gitlab.com` | GitLab host (default) |
| `MEDIA_BRANCH` | `main` | GitLab branch for figures |

### GitHub Secrets (shedrackgodstime/utmelab-api):
| Secret | Purpose |
|--------|---------|
| `GITLAB_ACCESS_TOKEN` | GitLab API token (for CI/CD) |
| `TURSO_DB_TOKEN_READONLY` | Read-only Turso token |
| `TURSO_DB_URL` | Turso database URL |
| `TURSO_PIPELINE_DB_TOKEN` | Pipeline DB token |
| `TURSO_PIPELINE_DB_URL` | Pipeline DB URL |
| `TURSO_PROD_DB_TOKEN` | Production DB token |
| `TURSO_PROD_DB_URL` | Production DB URL |
| `TURSO_UTMELAB_BANK_DB_TOKEN` | Bank DB token |
| `TURSO_UTMELAB_BANK_DB_URL` | Bank DB URL |
| `VPS_HOST`, `VPS_PORT`, `VPS_USER` | VPS deployment variables |
| `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS` | VSS SSH deployment |

### GitHub Variables (shedrackgodstime/utmelab-api):
| Variable | Value | Purpose |
|----------|-------|---------|
| `UTMELAB_BANK_AI_IMAGE_SECOND_MODEL` | `opencode/nemotron-3.5-super-vl-free` | Overrides default image model 2 |

---

## 🛠️ Error Handling: What's Working Well

### 1. **Structured Error Types** (excellent)
The system uses specific exception types that map to exit codes:
- `UsageError` → exit 2 (command misuse)
- `ConfigError` → exit 2 (missing configuration)
- `DatabaseError, MediaError, OpenCodeError, OpenAICompatibleError` → exit 1 (run failure)
- All other `Exception` → exit 1 + logging

```python
# cli.py main() exit code logic:
except UsageError as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 2
except ConfigError as exc:
    print(f"config: {exc}", file=sys.stderr)
    return 2
except (DatabaseError, MediaError, OpenCodeError, OpenAICompatibleError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 1
except Exception as exc:
    logging.getLogger(__name__).exception("the run failed")
    print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1
```

### 2. **Gate-Level Error Containment** (excellent)
Every gate refusal stays on the row as a `StagingItem.error`. Rows don't disappear:
- `result.skipped` = source validation errors, production already has it, DEDUPED finished rows
- `result.failed` = actual crashes/exceptions
- `result.blocked` = gate refused the row (kept in bank with reason)

### 3. **Dry-Run Safety Net** (excellent)
Every task supports `--dry-run`:
- `fetch --dry-run` probes source without writing
- `capture --dry-run` lists what would be captured without touching DB
- `tag/media/explain/review/ready --dry-run` notes intentions without committing

### 4. **Idempotent Operations** (very good)
Tasks can be safely rerun:
- `fetch` row in one scope query doesn't re-load finished rows
- `capture` reindexes from content after upload
- `index` reloads production without wiping bank
- State transitions use `assert_transition` to prevent illegal moves

---

## 🧪 Testing: Comprehensive but Missing Types

### ✅ What's Well-Tested (32 test files)
- **Gate rules** (test_gate.py): 60+ tests covering defects, judgements, duplicates, passage, placement
- **Models** (test_models.py): 50+ tests for pydantic model validation, freezing, external keys
- **Tasks** (test_tasks.py): End-to-end flow from fetch through ready, plus edge cases
- **State machine** (test_state_machine.py): Transition validity
- **Dedupe** (test_dedupe.py): Fingerprint-based duplicate detection
- **Media checks** (test_media_checks.py): Image validation, OCR status
- **Config** (test_config.py): Settings loading, .env parsing

### ❓ What's Not Tested (gaps)
Looking at the test structure, there are **no network-dependent live tests** by default (they're marked `live:` and opt-in). Good.

But I should check: are there any **unmodeled error paths**?

### 🔍 Specific Gaps Identified

#### 1. **Media Service Error Handling** (checks/media/service.py)
The `MediaService.apply()` method wraps `DescribeImageConsensus` - if both models fail, the error propagates up. But what happens if **one model succeeds and one fails**? Looking at the code in `tests/test_tasks.py`:
```python
described = await media(runtime, OPTIONS)
assert described.ok, described.errors
assert described.done == 1  # or skip/fail
```
The test asserts `.ok` but doesn't test the failure path where witnesses disagree.

#### 2. **Provider Failover in Edge Cases** (adapters/providers/factory.py)
The `openai.config` has sophisticated failover rules, but I need to verify the **code** actually implements them. The `error_policy` says:
- `failover_to_next_account`: `["rate_limit", "quota", "timeout", "provider_unavailable"]`
- `do_not_failover`: `["authentication", "invalid_request", "input", "output", "schema", "policy", "not_found"]`

But does the provider factory respect these? Need to check `create_text_provider` and `create_describer`.

#### 3. **Long SQL Queries** (ruff E501 violations)
Two lines too long (>100 chars) in `adapters/catalog.py`:
- Line 79: SQL query with column names and table
- Line 104: Subquery with dynamic placeholders

These are cosmetic but violate the project's own 100-char limit.

#### 4. **Media Check Complexity** (ruff C901)
`adapters/media/checks.py:check_media` has cyclomatic complexity of 16 (limit is 10). The function handles:
- Hash validation
- Byte size check
- Image reading/verification
- MIME type detection
- Dimension validation
- Width/height matching
- OCR status classification
- Status determination (invalid/review/ok)

This is logically dense but functionally complete. The complexity comes from covering all validation cases in one function.

#### 5. **No Test for `review` with Failed Gate** 
Looking at `test_tasks.py`, there's no test where a row fails the gate and then goes to review. The `review` step only processes `State.ENRICHED` rows, which have already passed the gate. This is by design, but worth documenting.

#### 6. **`process` Preset with Failed Rows** 
The `process` preset runs `capture → tag → media → explain → review → ready`. But what if some rows fail at `media` (witnesses disagree)? The preset continues with remaining rows, but the failed rows stay in the bank. There's no test verifying the preset's behavior when individual tasks fail.

---

## 🧩 Code Gaps & Recommendations

### Gap 1: **Provider Failover Not Verified**
**File**: `adapters/providers/factory.py`  
**Issue**: The `error_policy` in `openai.config` defines failover rules, but I haven't verified the code respects them.  
**Recommendation**: Add a test that switches API keys and verifies the next account is used on rate_limit/quota errors.

### Gap 2: **Long Import Lines** 
**File**: `adapters/catalog.py` lines 79, 104  
**Issue**: SQL query strings exceed 100-char limit.  
**Fix**: Break the strings or use variable assignment.

### Gap 3: **`check_media` Cyclomatic Complexity**
**File**: `adapters/media/checks.py`  
**Issue**: Complexity 16 > limit 10.  
**Recommendation**: Split into sub-functions:
- `validate_image_hash()`
- `validate_image_dimensions()`  
- `validate_ocr_status()`
- `determine_media_status()`

### Gap 4: **No Test for `ready` with Unmet Conditions**
**File**: `test_tasks.py`  
**Issue**: The `ready` step has conditions (explanatory text, figures described, etc.), but there's no test verifying what happens when conditions **aren't** met.  
**Recommendation**: Add a test that rows with missing explanations stay at `described` state and get blocked by `ready` with specific reason.

### Gap 5: **Provider Health Check Not Integrated**
**File**: `runtime.py` `open_pipeline_runtime()`  
**Issue**: The `openai.config` has `health_probe_before_reenable` and `reserve_unknown_quota`, but I need to check if the provider code actually performs health probes.  
**Recommendation**: Verify `create_text_provider`/`create_describer` implement health checking.

---

## 📊 Summary: What's the Priority?

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| **High** | Provider failover not tested | 1 day | Ensures robustness when NVIDIA API rate-limits |
| **Medium** | `check_media` complexity | 2 days | Improves maintainability, reduces bugs |
| **Medium** | Long SQL lines in catalog.py | few minutes | Ruff compliance |
| **Low** | `ready` conditions not tested | 1 day | Better coverage of edge cases |
| **Low** | Health probe integration | 2 days | Enables automatic account failover |

---

## ✅ Bottom Line

The system has **solid error handling** structured around:
1. Specific exception types → exit codes
2. Row-level error tracking (nothing disappears)
3. `--dry-run` safety for every task
4. Idempotent, rerunnable operations

The **main gaps** are:
1. **No tests for provider failover** when API limits are hit
2. **Complex `check_media` function** that could be refactored
3. **Minor ruff violations** (E501, C901)
4. **Missing edge-case tests** for `ready` conditions

The `openai.config` routing logic is well-designed (failover/do_not_failover policies), but the **code implementation** could use verification through tests.

**Would you like me to:**
1. Fix the ruff violations (E501/C901)?
2. Refactor `check_media` to reduce complexity?
3. Add test coverage for provider failover?
4. Add a test for `ready` with unmet conditions?
5. Something else?