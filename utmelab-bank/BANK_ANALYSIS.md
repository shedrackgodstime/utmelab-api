# UTME Lab Bank - Current State & Processing Plan

## Current Database State (from `utmelab-bank status`)

| State | Count | Meaning |
|-------|-------|---------|
| **deduped** | 3,057 | Passed gate + dedupe, waiting for figure capture |
| **catalogued** | 191 | Placed in catalog, waiting media description |
| **media_ready** | 0 | (not shown - likely included in catalogued) |
| **described** | 0 | Waiting for AI image descriptions |
| **enriched** | 0 | Waiting for explanations |
| **verified** | 0 | Waiting for human verification |
| **ready** | 38 | Ready for production (already through pipeline) |
| **rejected** | 164 | Filtered by gate (defects/judgements) |
| **index** | 5,535 total (2,243 production + 3,292 bank) | Production questions indexed |

## The Pipeline Backlog

```
3,057 deduped  → [capture] → [tag] → [media] → [explain] → [review] → [ready] → 38 already ready
     ↓              ↓        ↓         ↓        ↓        ↓        ↓
 figures    catalog   AI desc   explain  human   promote  production
                    step            es            to prod
```

## Key Observation: You're Not Alone — Use the Automation

The GitHub Actions `bank` workflow is **already configured** to run any task or preset via `workflow_dispatch`. You can process rows in **batches of 100** (the default `limit`), which is very manageable for one person.

### Automation Strategy: Run Tasks as GitHub Workflows

Each task can be triggered from the GitHub UI with different `--exam`, `--subject`, `--year`, and `--limit` parameters. No need to sit at a terminal.

### Step-by-Step Processing Plan

#### **Step 1: Capture Figures** (most critical first step)
```
 utmelab-bank capture \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100 \
   --dry-run  # first run to see what would happen
```

Then for real:
```
 utmelab-bank capture \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100
```

**Trigger via GitHub:** Use the `bank` workflow dispatch with:
- `command: capture`
- `exam: JAMB`
- `subject: biology`
- `year: 2024`
- `limit: 100`

**Why first:** Figures are captured while the source is alive. Rows left in `deduped` will lose their source connection over time.

#### **Step 2: Tag into Catalog**
```
 utmelab-bank tag \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100
```

**What it does:** Places deduped rows into the catalog with subtopics. Requires the production catalog to have the relevant topics/subtopics.

**Trigger via GitHub:** `command: tag` with same scope parameters.

#### **Step 3: Describe Media** (two-witness AI)
```
 utmelab-bank media \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100
```

**What it does:** Runs two AI models to describe captured figures. If they disagree, the row is rejected — this is quality control, not busywork.

**Trigger via GitHub:** `command: media`.

#### **Step 4: Explain** (write key points + body)
```
 utmelab-bank explain \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100
```

**What it does:** AI writes explanations for the rows. This is where the "enriched" state is reached.

**Trigger via GitHub:** `command: explain`.

#### **Step 5: Review** (human verification — **this still needs you**)
```
 utmelab-bank review \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 10
```

**What it does:** You review each row, verify the answer, and record the check. Even with 10 rows at a time, this is much more manageable than 100,000 all at once.

**Trigger via GitHub:** `command: review` with smaller `limit` (e.g., 10).

#### **Step 6: Promote to Ready**
```
 utmelab-bank ready \
   --exam JAMB \
   --subject biology \
   --year 2024 \
   --limit 100
```

**What it does:** Checks all conditions (explanatory text, figures described, etc.) and promotes to `ready` state. The 38 rows already at `ready` prove this works.

**Trigger via GitHub:** `command: ready`.

### Batch Processing Recommendation

**Don't try to process everything at once.** Use this cadence:

| Frequency | Task | Limit | Time Needed |
|-----------|------|-------|-------------|
| Daily | `capture` | 100 | ~5 min (API calls) |
| Daily | `tag` | 100 | ~2 min |
| Daily | `media` | 100 | ~10 min (two AI models) |
| Daily | `explain` | 100 | ~5 min (one AI model) |
| As needed | `review` | 10-20 | ~15 min (your verification) |
| Weekly | `ready` | 100 | ~2 min |

**Total per day: ~30 minutes of automated processing + ~15 minutes of your review time.**

### How to Trigger via GitHub Actions

1. Go to the **Actions** tab in the utmelab-bank repository
2. Select the **`bank`** workflow
3. Click **`Run workflow`**
4. Fill in the parameters:
   - `command`: `capture` (or tag, media, explain, review, ready)
   - `exam`: `JAMB` (or `ALL` for unscoped)
   - `subject`: `biology` (or subject slug)
   - `year`: `2024` (or target year)
   - `limit`: `100` (or smaller for review)
   - `provider`: `mock` (if no API keys) or `opencode` (default)

5. Click **Run workflow**
6. Watch the progress in real-time
7. Repeat for each task in the pipeline

### Minimizing Human Risk

**The system is designed to protect you:**

1. **Dry-run first** — every task supports `--dry-run` to see what would happen without writing
2. **Idempotent operations** — tasks can be safely rerun if something fails
3. **Row-level error reporting** — failed rows are marked with errors, not lost
4. **Batch sizes you control** — `limit` parameter lets you process 10 or 100 at a time
5. **The `review` step is the only human-dependent one** — but with small batches, this is very manageable

### What About Other Exams/Subjects?

The bank currently has data for:
- **JAMB** (just checked: biology 2024)
- The `status` output shows the system tracks multiple exams/subjects/years

If you need to process other combinations, just change the `--exam`, `--subject`, and `--year` parameters. The `ALL` option for exam/subject processes everything at once (use with caution and small limits).

### Current Progress Summary

- ✅ **38 rows** already through the full pipeline and ready for production
- ⚠️ **3,057 rows** stuck in `deduped` — need figure capture (Step 1)
- ⚠️ **191 rows** in `catalogued` — need media description (Step 3)
- ❌ **164 rows** rejected by gate — these had defects or judgements; review why they were rejected to improve source quality

### Next Immediate Action

**Run the capture task first** to get the 3,057 deduped rows into a state where figures are stored. This is the highest priority because:

1. Source data may not be available indefinitely
2. It unlocks all downstream steps
3. It can be done in batches of 100 via GitHub Actions with minimal supervision

**Command to start (via GitHub Actions or CLI):**
```
 utmelab-bank capture --exam JAMB --subject biology --year 2024 --limit 100
```

Then repeat for other subjects/exams, and progress through the pipeline step by step.

---
*This analysis is based on the actual bank database state. All tasks support `--dry-run` to preview before committing. The GitHub `bank` workflow is the recommended interface for single-person operation.*