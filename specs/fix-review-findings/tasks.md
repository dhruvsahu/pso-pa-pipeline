# Tasks — Fix Review Findings (P0/P1 subset)

One task per in-scope finding. Tasks are implemented **one at a time**. Each task updates
`../../handoff-memory.md` with the files changed, the reasoning, and the finding ID before being
marked complete.

> Re-score / re-flatten regeneration uses the stored `outputs/final_access_results.json` only —
> no LLM call (see design "regenerate vs. re-run").

---

### task-1.1 — P0-1: Empty-list free-text params emit `NA`
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `result_formatter.py`
- **Change:** Add `join_or_na(value, sep)` helper; use it for `st_reqs`, `spec`, `ql`,
  `reauth_reqs` so an empty list yields `"NA"` not `""`. Guard module-level I/O under
  `if __name__ == "__main__"` (`main()`).
- **Outcome:** No free-text column can be blank; `flatten_result` is import-safe.
- **Context:** Req 1.3, 1.4. Verify against shipped CSV (currently 8 + 17 blanks).

### task-1.2 — P0-2: CSV header + column order match the template
- **BlockedBy:** task-1.1
- **Agent:** general-purpose
- **File:** `result_formatter.py`, `app.py`
- **Change:** Introduce module-level `SUBMISSION_COLUMNS` (hyphenated `Step through-Phototherapy`;
  `Quantity Limits` before `Specialist Types`). Reorder `flatten_result` keys to match; reindex the
  DataFrame to `SUBMISSION_COLUMNS` before writing. `app.py` imports `SUBMISSION_COLUMNS` instead of
  its own `CSV_COLUMNS`.
- **Outcome:** Output header equals the Submissions-tab header exactly (names + order).
- **Context:** Req 1.1, 1.2, 1.5. Single source of truth for the schema.

### task-2.1 — P0-4: Map internal sentinels to `NA`; update ADR
- **BlockedBy:** task-1.2
- **Agent:** general-purpose
- **File:** `age_extractor.py`, `result_formatter.py`, `docs/ADR.md`
- **Change:** In `age_extractor`, return `"NA"` (not `"NO BRAND MATCH FOUND"`) on the no-match path.
  In `flatten_result`, add `clean_cell` applying a known-sentinel→`NA` map to every emitted value.
  Add an ADR entry documenting the sentinel→`NA` output convention.
- **Outcome:** No graded cell contains an internal sentinel; shipped CSV corrected on regeneration.
- **Context:** Req 2.1, 2.2, 8.2. Affected row: `287728-4459856.pdf / STELARA`.

### task-2.2 — P1-9: `TB`/`Initial Auth` honor `No` / `Unspecified` semantics
- **BlockedBy:** task-4.2
- **Agent:** general-purpose
- **File:** `extractors/clinical_access_extractor.py`, `extractors/authorization_extractor.py`
- **Change:** TB → `"No"` when context parsed but TB not required, `"NA"` only on no-context/error.
  Initial Auth → `"Unspecified"` when a PsO authorization section exists but no month value is
  found, instead of `"NA"`. Update prompts + post-parse defaulting.
- **Outcome:** Forward-fixing: next full run distinguishes `No` from `NA` and uses `Unspecified`.
- **Context:** Req 2.3, 2.4. Note in handoff-memory that the shipped CSV reflects this only where
  stored data supports the derivation.

### task-3.1 — P0-5: Re-anchor Access Score to full 0–100 — DEFERRED (not implemented)
- **Status:** DEFERRED / downgraded to P2 after the Devil's Advocate review.
- **Rationale:** The ceiling-58 claim is mechanically true but is only a *defect* if the gold
  access-score distribution uses the full range — and the gold is empty in `Submissions` and
  absent everywhere. The proposed +50 credits track is asymmetrically risky: if gold sits ≤50, it
  *increases* error against the graded gold, and the detector for that (P1-3) is deferred. Decision:
  keep the current deduction-only scorer; revisit only with a gold sample / P1-3, then with a
  smaller symmetric model.
- **No file changes.** The current scorer is retained as-is (task-5.1 re-scores rows with it).

### task-4.1 — P1-1: Shared, thread-safe `ModelRouter`
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/model_router.py`, all 5 `extractors/*.py`, `pipeline_runner.py`,
  `run_full_pipeline.py`
- **Change:** Add `get_router()` module singleton (double-checked lock). Extractors call
  `get_router()` not `ModelRouter()`. Add `self._throttle_lock`; wrap throttle read-modify-write +
  post-call window update; tag Groq window entries with a unique id and replace by id.
- **Outcome:** One router per process; rate limit enforced globally; no window race/corruption.
- **Context:** Req 5.1–5.3. Corrects ADR-005's singleton assumption (update ADR note if present).

### task-4.2 — P1-2: Surface extraction errors; don't checkpoint failures
- **BlockedBy:** task-4.1
- **Agent:** general-purpose
- **File:** all 5 `extractors/*.py`, `run_full_pipeline.py`
- **Change:** Each extractor `except` adds `"extraction_error": True` and `logging.warning(...)`.
  `run_full_pipeline` skips checkpointing any row whose sub-results carry `extraction_error`.
- **Outcome:** Failed extractions are visible and retried on re-run; not recorded as success.
- **Context:** Req 6.1–6.3.

### task-4.3 — P1-10: Resource-safe web UI sessions
- **BlockedBy:** task-4.1, task-1.2
- **Agent:** general-purpose
- **File:** `app.py`
- **Change:** Store `(path, created_at)` under a `threading.Lock`; add `SESSION_TTL_SECONDS` and
  sweep expired sessions (unlink temp + pop) on each `/upload`; keep `/stream` `finally` cleanup.
- **Outcome:** No leaked temp files / session entries; thread-safe session store.
- **Context:** Req 7.1–7.3.

### task-4.4 — P1-5: Align Gemini model name in docs
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `README.md`, `.env.example`
- **Change:** Set the Gemini model name in both docs to match `model_router.py`
  (`gemini-3.1-flash-lite`). Documentation-only; the model is valid (not a bug).
- **Outcome:** Docs and code agree on the Gemini model name.
- **Context:** Req 8.1.

### task-5.1 — P1-6: Scorer version stamp + re-score + regenerate + README stats
- **BlockedBy:** task-1.2, task-2.1
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`, regeneration routine (`rescore.py` or `--rescore`),
  `outputs/final_access_results.json`, `outputs/final_access_results.csv`,
  `outputs/final_access_results.xlsx`, `README.md`
- **Change:** Add `SCORER_VERSION = "1.0"`; emit it per row. Add a re-score routine that recomputes
  every row's `access_quality` from stored extraction dicts (no LLM) using the **current** scorer
  (P0-5 deferred), fixing the stale 70 row (→ ≈25) and normalizing all rows to the
  `{deductions, bonuses}` schema. Regenerate CSV/XLSX via the formatter. Recompute and update README
  score-distribution stats from the new CSV.
- **Outcome:** One consistent scorer schema across all rows; reproducible dataset; README matches data.
- **Context:** Req 4.1–4.4. Capstone — depends on the final formatter (1.2) and sentinel map (2.1).
  No longer depends on task-3.1 (deferred); uses the current scorer.

---

## Dependency diagram

(task-3.1 / P0-5 is DEFERRED — removed from the active graph.)

```
task-1.1 (P0-1) ──► task-1.2 (P0-2) ──┬──► task-2.1 (P0-4) ──┐
                                       │                      │
                                       │                      ├──► task-5.1 (P1-6)
                                       │                      │
task-4.1 (P1-1) ──┬──► task-4.2 (P1-2) ──► task-2.2 (P1-9)   │
                  │                                           │
                  └──► task-4.3 (P1-10) ◄── task-1.2 ─────────┘
                                          (4.3 also blocked by 1.2)

task-4.4 (P1-5)  [independent]
```

Edges:
- task-1.2 ← task-1.1
- task-2.1 ← task-1.2
- task-2.2 ← task-4.2
- task-4.2 ← task-4.1
- task-4.3 ← task-4.1, task-1.2
- task-5.1 ← task-1.2, task-2.1
- task-1.1, task-4.1, task-4.4 are roots (BlockedBy none)

## Execution summary

- **Active tasks: 9** (task-3.1 / P0-5 deferred).
- **Stage 1 (parallel-safe):** task-1.1, task-4.1, task-4.4
- **Stage 2:** task-1.2 (←1.1), task-4.2 (←4.1)
- **Stage 3:** task-2.1 (←1.2), task-4.3 (←4.1,1.2), task-2.2 (←4.2)
- **Stage 4:** task-5.1 (←1.2,2.1)
- **Critical path:** task-1.1 → task-1.2 → task-2.1 → task-5.1 (4 stages)
- **Total stages:** 4

> Although several tasks are parallel-safe by dependency, they will be implemented **one at a
> time** per the user's instruction, each followed by a `handoff-memory.md` update.
