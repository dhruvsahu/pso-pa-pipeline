# Handoff Memory — Fix Review Findings

This document is the running record of every code change made under the spec at
`specs/fix-review-findings/`. For each task it records: the finding ID (P#), the files touched,
the change, and the reasoning. It is updated **after each task is implemented** (status moves
`PENDING → DONE` with the actual edits filled in).

- Spec: `specs/fix-review-findings/{requirements,design,tasks}.md`
- Source review: `REVIEW.md`
- **Environment constraint:** no LLM API key / network here. Output-format and scoring fixes are
  applied by **regenerating** from the stored `outputs/final_access_results.json` (re-flatten /
  re-score, no LLM). Extractor/router/UI fixes are **forward-fixing** (effective on the next full
  run) and cannot change the shipped CSV except where derivable from stored data.

## Status

| Task | Finding | Files | Status |
|------|---------|-------|--------|
| task-1.1 | P0-1 | `result_formatter.py` | ✅ DONE |
| task-1.2 | P0-2 | `result_formatter.py`, `app.py` | ✅ DONE |
| task-2.1 | P0-4 | `age_extractor.py`, `result_formatter.py`, `docs/ADR.md` | ✅ DONE |
| task-2.2 | P1-9 | `extractors/clinical_access_extractor.py`, `extractors/authorization_extractor.py` | ✅ DONE |
| task-3.1 | P0-5 | `access_quality_scorer.py` | **DEFERRED** (Devil's Advocate; downgraded to P2) |
| task-4.1 | P1-1 | `utils/model_router.py`, `extractors/*.py` | ✅ DONE |
| task-4.2 | P1-2 | `extractors/*.py`, `run_full_pipeline.py` | ✅ DONE |
| task-4.3 | P1-10 | `app.py` | ✅ DONE |
| task-4.4 | P1-5 | `.env.example` | ✅ DONE |
| task-5.1 | P1-6 | `access_quality_scorer.py`, `rescore.py`, `outputs/*`, `README.md` | ✅ DONE |

---

## task-1.1 — P0-1: Empty-list free-text params emit `NA`
**Status:** ✅ DONE
**Planned change:** Add `join_or_na(value, sep="; ")` to `result_formatter.py`; use it for the four
free-text list columns; guard module-level I/O under `main()`/`__main__`.
**Reasoning (P0-1):** `"; ".join([])` returns `""`, and the `or "NA"` fallback never fires for an
empty list, so 25 cells ship blank — violates "all params populated". Import-guarding lets the
re-score step import `flatten_result` without side effects.
**Actual changes:**
- `result_formatter.py`: added `join_or_na(value, sep)` helper; updated 4 list-valued columns to use it; moved batch I/O into `main()` guarded by `if __name__ == "__main__"`.
- Simultaneously added `SUBMISSION_COLUMNS` (see task-1.2 below) in the same file.

## task-1.2 — P0-2: CSV header + column order match the template
**Status:** ✅ DONE
**Planned change:** Add module-level `SUBMISSION_COLUMNS` (hyphenated `Step through-Phototherapy`;
`Quantity Limits` before `Specialist Types`); reorder `flatten_result`; reindex DataFrame before
write; `app.py` imports `SUBMISSION_COLUMNS`.
**Reasoning (P0-2):** Output header `Step through Phototherapy` (space) and the swapped
Specialist/Quantity order break exact/positional grader matching. One schema source prevents the
two definitions (`result_formatter` + `app.py`) from drifting.
**Actual changes:**
- `result_formatter.py`: added module-level `SUBMISSION_COLUMNS` list with hyphenated `Step through-Phototherapy` and `Quantity Limits` before `Specialist Types`; `flatten_result` key uses hyphenated name; `main()` reindexes DataFrame to `SUBMISSION_COLUMNS` before write.
- `app.py`: imports `SUBMISSION_COLUMNS` from `result_formatter`; removed the local `CSV_COLUMNS` definition; `CSV_COLUMNS = SUBMISSION_COLUMNS`.

## task-2.1 — P0-4: Map internal sentinels to `NA`; update ADR
**Status:** ✅ DONE
**Planned change:** `age_extractor` no-match path returns `"NA"`; `flatten_result` applies a
`clean_cell` sentinel→`NA` map to all values; add ADR entry on the sentinel→`NA` convention.
**Reasoning (P0-4):** `NO BRAND MATCH FOUND` leaked into a graded Age cell. Fixing at source
prevents recurrence; the flatten guard corrects the already-shipped cell on regeneration; the ADR
records the convention.
**Actual changes:**
- `extractors/age_extractor.py`: changed no-brand-match path `"value": "NO BRAND MATCH FOUND"` → `"value": "NA"`.
- `result_formatter.py`: added `_SENTINELS` set and `clean_cell(v)` helper; applied `clean_cell()` to the Age value in `flatten_result`.
- `docs/ADR.md`: added ADR-011 "Sentinel-to-NA Output Convention" with context, decision, rationale, consequences; added to summary table.

## task-2.2 — P1-9: `TB`/`Initial Auth` honor `No` / `Unspecified`
**Status:** ✅ DONE (forward-fixing — effective on next full LLM run)
**Planned change:** TB → `"No"` when parsed-but-not-required, `"NA"` only on no-context/error;
Initial Auth → `"Unspecified"` when a PsO auth section exists but no months found.
**Reasoning (P1-9):** Spec treats TB as Y/N and requires duration-or-`Unspecified` when PA applies;
emitting `NA` in these cases diverges from gold. Forward-fixing (next run); shipped CSV reflects it
only where stored data supports the derivation.
**Actual changes:**
- `extractors/clinical_access_extractor.py`: updated `tb_test_required` prompt rules to distinguish "No" (criteria found, TB not required) from "NA" (no criteria context at all).
- `extractors/authorization_extractor.py`: updated duration field prompt rules to use "Unspecified" (not "NA") when auth section exists but no months stated; added `_coerce_duration()` post-parse helper that maps None/"NA" → "Unspecified" when context was found and parsed.

## task-3.1 — P0-5: Re-anchor Access Score to full 0–100
**Status:** DEFERRED (downgraded P0 → P2). No code change.
**Decision (Devil's Advocate review):** The ceiling-58 claim is mechanically true, but it is only a
*defect* if the gold access-score distribution uses the full range — and the gold is empty in the
`Submissions` tab and absent from every provided artifact (the one >50 row is a stale artifact, see
task-5.1). The proposed +50 credits track is asymmetrically risky: if gold genuinely sits ≤50 (the
intended "PA only adds restrictions vs FDA" reading), the credits push clean policies to 75–100 and
*increase* error against the graded gold — and the regression detector for that (P1-3) is itself
deferred. The credits also double-count evidence already captured by the deductions.
**Resolution:** Keep the current deduction-only scorer (range ≈0–58). Revisit only with a gold
sample or P1-3, then with a smaller, symmetric (mirror-the-deductions) model — not the +50 track.
Original proposal preserved in `requirements.md` Requirement 3 (marked deferred).
**Actual changes:** none (deferred).

## task-4.1 — P1-1: Shared, thread-safe `ModelRouter`
**Status:** ✅ DONE
**Planned change:** `get_router()` module singleton (double-checked lock); extractors use it;
`self._throttle_lock` around throttle read-modify-write + post-call update; tag Groq window entries
by id and replace by id.
**Reasoning (P1-1):** 5 extractor-owned routers → 5 throttle windows → rate limit ~5× too loose
(ADR-005 wrongly assumed a singleton). Under threaded Flask the window is a data race and the
estimate/replace can pop the wrong entry.
**Actual changes:**
- `utils/model_router.py`: added `import threading`, `import uuid`; added `self._throttle_lock`; wrapped Groq and Gemini throttle read-modify-write + sleep under lock (released while sleeping); changed Groq window from `deque` to `list` of `(ts, tokens, call_id)` tuples; added `_groq_update_actual(call_id, actual_tokens)` to replace entry by id; added module-level `_INSTANCE`/`_INSTANCE_LOCK` and `get_router()` double-checked-lock singleton; removed dead `select_model()` method (collapsed to `"qwen2.5:7b"` inline in Ollama path).
- All 5 `extractors/*.py`: changed `from utils.model_router import ModelRouter` → `from utils.model_router import get_router`; changed `ModelRouter()` → `get_router()`.

## task-4.2 — P1-2: Surface extraction errors; don't checkpoint failures
**Status:** ✅ DONE
**Planned change:** Each extractor `except` adds `"extraction_error": True` + `logging.warning`;
`run_full_pipeline` skips checkpointing rows with any errored sub-result.
**Reasoning (P1-2):** Swallowed errors produce all-`NA` rows indistinguishable from real "no data",
checkpointed as success and never retried — silently corrupting accuracy and the score.
**Actual changes:**
- All 5 `extractors/*.py`: added `import logging`; added `"extraction_error": True` and `logging.warning(...)` to the main `extract()` except block.
- `run_full_pipeline.py`: added `import logging`; added post-assembly check for `extraction_error` in any of the 5 sub-result dicts; if found, logs warning, prints skip message, and `continue`s without appending to `all_results` or writing checkpoint — so the row is retried on next run.

## task-4.3 — P1-10: Resource-safe web UI sessions
**Status:** ✅ DONE
**Planned change:** Store `(path, created_at)` under a `threading.Lock`; `SESSION_TTL_SECONDS`
sweep of expired sessions on each `/upload`; keep `/stream` `finally` cleanup.
**Reasoning (P1-10):** Upload-without-stream leaks the temp file and `SESSIONS` entry forever; the
dict is mutated across threads (`threaded=True`) with no lock.
**Actual changes:**
- `app.py`: added `import threading`, `import time`; added `SESSIONS_LOCK` and `SESSION_TTL_SECONDS = 600`; changed session store to `(path, created_at)` tuples; added `_sweep_expired_sessions()` called on each `/upload`; all SESSIONS reads/writes wrapped in `SESSIONS_LOCK`; `/stream` finally block pops session under lock before unlinking file.

## task-4.4 — P1-5: Align Gemini model name in docs
**Status:** ✅ DONE
**Planned change:** Set the Gemini model name in `README.md` and `.env.example` to match
`model_router.py` (`gemini-3.1-flash-lite`).
**Reasoning (P1-5):** Per product decision the model is valid — this is a documentation
consistency fix only, not a code change.
**Actual changes:**
- `.env.example`: changed `gemini-2.0-flash-lite` → `gemini-3.1-flash-lite` in the comment.
- `README.md`: already had the correct name from a prior session; no change needed.

## task-5.1 — P1-6: Scorer version stamp + re-score + regenerate + README stats
**Status:** ✅ DONE
**Planned change:** Add `SCORER_VERSION = "1.0"`; emit per row. Add a re-score routine that recomputes
every row's `access_quality` from stored extraction dicts (no LLM) using the **current** scorer
(P0-5 deferred — no re-anchor) — fixes the stale 70 row (→ ≈25) and normalizes all rows to the
`{deductions, bonuses}` schema. Regenerate CSV/XLSX. Recompute README score-distribution stats from
the new CSV. (No longer blocked by task-3.1.)
**Reasoning (P1-6):** The JSON mixes two scorer schemas (one legacy flat-list row scoring 70,
impossible under the current model), so the dataset isn't reproducible from current code, and the
README's "7–50, none above 50" contradicts the data. A version stamp + deterministic re-score makes
the dataset consistent and reproducible.
**Actual changes:**
- `access_quality_scorer.py`: added module-level `SCORER_VERSION = "1.0"`; added `"scorer_version": SCORER_VERSION` to the `calculate_score` return dict.
- `rescore.py` (new file): loads JSON, re-scores every row with current scorer, writes updated JSON, regenerates CSV/XLSX via `flatten_result`/`SUBMISSION_COLUMNS`, prints distribution stats.
- Ran `rescore.py`: stale row `377585-4984547.pdf/STELARA` corrected 70 → 25; all 79 rows now stamped `scorer_version="1.0"`. Stats: min=7, max=50, mean=27.8, median=27; 0 rows ≥75, 2 at 50, 43 at 25–49, 34 at 0–24.
- `README.md`: updated score distribution line with exact stats (mean 28, median 27, distribution breakdown).
