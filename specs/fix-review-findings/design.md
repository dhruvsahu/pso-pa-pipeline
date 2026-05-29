# Design — Fix Review Findings (P0/P1 subset)

## Overview

The fixes touch five layers: the **output formatter** (`result_formatter.py`, `app.py`), the
**scorer** (`access_quality_scorer.py`), two **extractors** (`age_extractor.py`,
`clinical_access_extractor.py`, `authorization_extractor.py`), the **router**
(`utils/model_router.py` + extractor constructors + runners), and the **web UI** (`app.py`).
A final **regeneration** step rebuilds the shipped `outputs/` artifacts from the stored
extraction JSON.

This design keeps the parts the review praised untouched: the step-therapy slot/counting logic,
the retrieval passes, and the (Filename, Brand) row coverage.

## Key design decision: regenerate vs. re-run

Because there is **no LLM access in this environment**, we cannot re-run extraction. We split
the work:

| Fix | Mechanism | Reflected in shipped CSV? |
|-----|-----------|---------------------------|
| P0-1, P0-2 | Re-flatten stored JSON → CSV/XLSX (`result_formatter.py`) | Yes |
| P0-4 (leaked cell) | Defensive sentinel→`NA` map in `flatten_result` | Yes |
| P1-6 | Re-score stored extraction values with the **current** scorer, no LLM, then re-flatten | Yes |
| P0-4 (source), P1-9, P1-1, P1-2, P1-10 | Forward-fixing code | Only on next full run |
| ~~P0-5~~ | **DEFERRED** — see component 2 | n/a |

The re-score routine is the linchpin: `access_quality_scorer.calculate_score` already takes the
five extractor result dicts as input, and those dicts are stored verbatim under each row in
`final_access_results.json`. So re-scoring is a pure function of stored data.

## Component changes

### 1. Output formatter — `result_formatter.py`, `app.py` (P0-1, P0-2, P0-4 cell)

- Add a single helper:
  ```python
  def join_or_na(value, sep="; "):
      if isinstance(value, list):
          return sep.join(value) if value else "NA"
      return value or "NA"
  ```
  Use it for the four free-text list columns (`st_reqs`, `spec`, `ql`, `reauth_reqs`). This fixes
  the empty-list→blank bug (Req 1.3, 1.4).
- Add a sentinel guard applied to every emitted value:
  ```python
  _SENTINELS = {"NO BRAND MATCH FOUND", "", None}
  def clean_cell(v): return "NA" if v in _SENTINELS else v
  ```
  Apply at the end of `flatten_result` (Req 2.1, 2.2).
- Define the column order once as `SUBMISSION_COLUMNS` (a module-level list) with
  `Step through-Phototherapy` hyphenated and `Quantity Limits` before `Specialist Types`
  (Req 1.1, 1.2, 1.5). `app.py` imports `SUBMISSION_COLUMNS` instead of redefining `CSV_COLUMNS`.
- The `flatten_result` return dict keys are reordered to match `SUBMISSION_COLUMNS`; the batch
  writer reindexes the DataFrame to `SUBMISSION_COLUMNS` before `to_csv`/`to_excel`.
- Guard the module-level I/O (read JSON / write CSV+XLSX) under a `main()` called from
  `if __name__ == "__main__"` so importing `flatten_result` has no side effects (needed so the
  re-score step can import it cleanly).

### 2. Scorer re-anchor — `access_quality_scorer.py` (P0-5) — DEFERRED

**Not implemented this iteration.** A focused Devil's Advocate review concluded the re-anchoring
is asymmetrically risky without a gold access-score sample (which does not exist in the provided
data) or the P1-3 validation harness (deferred): if the gold genuinely sits ≤50, a +50 credits
track would push clean policies to 75–100 and *increase* error against the graded gold, and we
would ship it blind. The credits also double-count evidence already captured by the absent
deductions.

**Retained current behavior:** start at 50 (FDA parity), deduction-only logic, reachable range
≈0–58, category cutoffs `<25` Highly Restricted / `25–<50` Restricted Access / `50–<75` FDA
Parity / `>=75` Preferred Access (unchanged). The `score_breakdown` keeps its existing
`{deductions, bonuses}` shape.

The original proposed credits model (no-step +20, no-reauth +10, no-QL +5, no-specialist +5,
age ≤FDA +5, TB-waived +5) is preserved in git history / `requirements.md` Requirement 3 as the
starting point **if** P0-5 is revisited — but only as a smaller, symmetric (mirror-the-deductions)
model gated on validation.

### 3. Scorer version + re-score — `access_quality_scorer.py` + regeneration (P1-6)

- Add `SCORER_VERSION = "1.0"` constant (documents the **current**, un-re-anchored scorer; P0-5
  deferred); `calculate_score` includes `"scorer_version": SCORER_VERSION` in its output (Req 4.1).
- Add a `rescore_stored_results()` routine (a small function/script, e.g. `rescore.py` or a
  `--rescore` mode) that loads `final_access_results.json`, and for each row calls
  `calculate_score` with the stored `age`/`step_therapy`/`authorization`/
  `utilization_management`/`clinical_access` dicts, replacing the `access_quality` block
  (Req 4.2, 4.3). No LLM. This fixes the stale 70 row — under the current scorer that row
  re-scores to ≈25 (brand_steps=2, reauth=Yes), so the reproducible max returns to ≈50 and the
  legacy flat-list `score_breakdown` is replaced by the standard `{deductions, bonuses}` schema.
- After re-scoring, run the formatter to regenerate CSV/XLSX, then recompute README
  score-distribution stats (min/max/mean/median, count ≥75, category counts) from the new CSV
  and update the README block (Req 4.4).

### 4. Extractor value semantics — `clinical_access_extractor.py`, `authorization_extractor.py` (P1-9)

- **TB (clinical_access):** when context was found and parsed but TB is not required, return
  `"No"`; reserve `"NA"` for the no-context / error paths (Req 2.3). Update the prompt's allowed
  output set and the post-parse defaulting accordingly.
- **Initial Authorization (authorization):** when an approval/authorization section exists for
  the brand's PsO indication but no explicit month value is found, return `"Unspecified"` instead
  of `"NA"` (Req 2.4).
- These are forward-fixing (next full run). Where the stored JSON already distinguishes
  "context found" from "no context", the re-score/re-flatten may apply the No-vs-NA mapping;
  otherwise the shipped values are left as-is and the fix applies on re-run. This limitation is
  documented in `handoff-memory.md`.

### 5. Age sentinel at source — `age_extractor.py` (P0-4)

- The no-brand-match path currently returns `"NO BRAND MATCH FOUND"` as the age value. Change it
  to return `"NA"` (Req 2.1). The defensive flatten guard (component 1) is the belt-and-suspenders
  that also fixes the already-shipped cell.
- Add an ADR entry describing the sentinel→`NA` output convention (Req 8.2).

### 6. Shared, thread-safe router — `utils/model_router.py` + extractors + runners (P1-1)

- Add a module-level singleton accessor in `model_router.py`:
  ```python
  _INSTANCE = None
  _INSTANCE_LOCK = threading.Lock()
  def get_router():
      global _INSTANCE
      if _INSTANCE is None:
          with _INSTANCE_LOCK:
              if _INSTANCE is None:
                  _INSTANCE = ModelRouter()
      return _INSTANCE
  ```
- Each extractor `__init__` calls `get_router()` instead of `ModelRouter()` (Req 5.1).
- Add `self._throttle_lock = threading.Lock()` in `ModelRouter.__init__`; wrap the body of
  `_groq_throttle`, `_gemini_throttle`, and the post-call window update in the lock. The
  sleep-wait loop releases the lock while sleeping and re-acquires to re-check (Req 5.2).
- Tag each Groq window entry with a unique id and replace by id, not by matching
  `estimated_tokens` (Req 5.3).

### 7. Observable extraction failures — extractors + `run_full_pipeline.py` (P1-2)

- In each extractor's `except`, add `"extraction_error": True` to the returned dict and
  `logging.warning(...)` the exception (Req 6.1). Keep the all-`NA` values so scoring still works,
  but the flag distinguishes error from no-data.
- In `run_full_pipeline.main`, after assembling `final_result`, if any of the five extractor
  sub-dicts has `extraction_error`, do **not** append/checkpoint it as completed — log and skip so
  the resume logic retries it next run (Req 6.2, 6.3).

### 8. Resource-safe UI — `app.py` (P1-10)

- Replace `SESSIONS[id] = path` with `SESSIONS[id] = (path, time.time())`, guarded by a
  `threading.Lock` for all reads/writes (Req 7.2).
- On each `/upload`, sweep entries older than `SESSION_TTL_SECONDS` (e.g. 600s): unlink their temp
  files and pop them (Req 7.1, 7.3). Keep the existing `/stream` `finally` cleanup as the
  fast-path.

### 9. Documentation — `README.md`, `.env.example` (P1-5)

- Align the Gemini model name in `README.md` and `.env.example` to the name used in
  `model_router.py` (`gemini-3.1-flash-lite`). This is a doc-consistency change only — no code
  change, since the model is valid (Req 8.1).

## Data shapes

`access_quality` block after this work (current scorer schema + version stamp; P0-5 deferred so no
`credits` track):
```json
{
  "brand": "STELARA",
  "access_quality_score": 25,
  "access_category": "Restricted Access",
  "fda_alignment": "More restrictive than FDA label",
  "scorer_version": "1.0",
  "score_breakdown": { "deductions": ["..."], "bonuses": ["..."] }
}
```

## Testing strategy

- **Re-score determinism:** running the re-score routine twice yields identical JSON.
- **CSV conformance:** assert header equals the Submissions-tab header list exactly (names + order);
  assert 79 rows; assert zero blank cells; assert no value equals a known sentinel.
- **Score range:** assert all scores in `[0,100]` (current scorer; the ≥75 reachability assertion
  is deferred with P0-5). Assert the re-scored stale row (`377585-4984547.pdf`/STELARA) drops from
  70 to ≈25.
- **Router:** unit-test that two extractors share the same router instance; a threaded stress test
  that the window never exceeds target by more than one in-flight call.
- **UI:** unit-test that a session older than TTL is swept on the next upload.
- Use the `Reference` worked example (`250819`/Yesintek: age ≥6, brand 1, generic 1, photo No,
  TB Yes, init 6mo, reauth 12mo) as a cross-check fixture where feasible.
