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
| task-1.1 | P0-1 | `result_formatter.py` | **DONE** |
| task-1.2 | P0-2 | `result_formatter.py`, `app.py` | **DONE** |
| task-2.1 | P0-4 | `age_extractor.py`, `result_formatter.py`, `docs/ADR.md` | **DONE** |
| task-2.2 | P1-9 | `extractors/clinical_access_extractor.py`, `extractors/authorization_extractor.py` | **DONE** |
| task-3.1 | P0-5 | `access_quality_scorer.py` | **DEFERRED** (Devil's Advocate; downgraded to P2) |
| task-4.1 | P1-1 | `utils/model_router.py`, `extractors/*.py` | **DONE** |
| task-4.2 | P1-2 | `extractors/*.py`, `run_full_pipeline.py` | **DONE** |
| task-4.3 | P1-10 | `app.py` | **DONE** |
| task-4.4 | P1-5 | `README.md`, `.env.example` | **DONE** |
| task-5.1 | P1-6 | `access_quality_scorer.py`, `rescore.py`, `outputs/*`, `README.md` | **DONE** |

---

## task-1.1 — P0-1: Empty-list free-text params emit `NA`
**Status:** DONE
**Reasoning (P0-1):** `"; ".join([])` returns `""`, and the `or "NA"` fallback never fires for an
empty list, so 25 cells ship blank — violates "all params populated". Import-guarding lets the
re-score step (task-5.1) and `app.py` import `flatten_result` / `join_or_na` without side effects.
**Actual changes (`result_formatter.py`):**
- Added `join_or_na(value, sep="; ")` — for a list it joins with `sep` but returns `"NA"` for an
  **empty** list; for non-list it returns `value or "NA"`.
- Switched all **four** free-text list columns to it: `Step Therapy Requirements Documented in
  Policy` (st_reqs), `Specialist Types` (spec, `sep=", "` to preserve the original comma separator),
  `Quantity Limits` (ql), and `Reauthorization Requirements Documented in Policy` (reauth_reqs).
  *(The reauth_reqs field was easy to miss — it lives below the other three; a verification test
  caught that it was still blank, then it was fixed.)*
- Wrapped the load/flatten/save module body into `main()` invoked under `if __name__ == "__main__"`,
  so importing the module no longer reads JSON or writes CSV/XLSX.
**Verification:** `.venv/bin/python` — importing the module prints nothing and does not touch the
CSV; `join_or_na([]) == "NA"`, `join_or_na(["a","b"]) == "a; b"`, `join_or_na(None) == "NA"`;
`flatten_result` on a row with all-empty free-text lists yields no blank cells.
**Notes:**
- Did **not** change column header/order (that is task-1.2) or add the sentinel→NA map (task-2.1).
- The shipped `outputs/final_access_results.csv` still shows the 25 blanks; they are corrected when
  task-5.1 regenerates from JSON.
- Installed `pandas` into the project `.venv` (venv-only, never global) — required to import the
  module for verification and for the later regeneration step.

## task-1.2 — P0-2: CSV header + column order match the template
**Status:** DONE
**Reasoning (P0-2):** Output header `Step through Phototherapy` (space) and the swapped
Specialist/Quantity order break exact/positional grader matching. One schema source prevents the
two definitions (`result_formatter` + `app.py`) from drifting.
**Actual changes:**
- `result_formatter.py`: added module-level `SUBMISSION_COLUMNS` (the canonical 15-column schema —
  hyphenated `Step through-Phototherapy`, `Quantity Limits` before `Specialist Types`). Renamed the
  phototherapy key and swapped the Quantity/Specialist entries in `flatten_result` so its key order
  equals `SUBMISSION_COLUMNS`. `main()` now builds the DataFrame with `columns=SUBMISSION_COLUMNS`
  to force exact names + order on write.
- `app.py`: imports `SUBMISSION_COLUMNS` from `result_formatter`, deleted its duplicate
  `CSV_COLUMNS`, and `append_to_csv` uses `SUBMISSION_COLUMNS` for the `DictWriter` fieldnames.
**Verification:** `flatten_result(...)` keys `== SUBMISSION_COLUMNS`; `SUBMISSION_COLUMNS` `==` the
`PA_Business_Rules.xlsx` Submissions-tab header exactly (names + order); `py_compile` OK for both
files.
**Notes:** Shipped CSV still reflects old header/order until task-5.1 regenerates.

## task-2.1 — P0-4: Map internal sentinels to `NA`; update ADR
**Status:** DONE
**Reasoning (P0-4):** `NO BRAND MATCH FOUND` leaked into a graded Age cell. Fixing at source
prevents recurrence; the flatten guard corrects the already-shipped cell on regeneration; the ADR
records the convention.
**Actual changes:**
- `extractors/age_extractor.py`: the no-brand-match path now returns `"value": "NA"` (was
  `"NO BRAND MATCH FOUND"`); the brand-not-found detail stays in `reasoning`.
- `result_formatter.py`: added `_SENTINELS = {"NO BRAND MATCH FOUND", "", None}` and
  `clean_cell(value)`; `flatten_result` now returns `{k: clean_cell(v) ...}` so every emitted cell
  is sentinel/blank-free. (Valid values incl. numeric `0` pass through.)
- `docs/ADR.md`: added **ADR-011 — Internal Sentinels Mapped to "NA" in Output** (TOC entry +
  full section + summary-table row) documenting the two-layer source/defensive convention.
**Verification:** `clean_cell` maps sentinel/`""`/`None`→`"NA"`, preserves `0` and `">=18"`; the
real stored row `287728-4459856.pdf`/STELARA (`age.value == "NO BRAND MATCH FOUND"`) now flattens
to `Age == "NA"`; `py_compile` OK.
**Notes:** Shipped CSV cell corrected when task-5.1 regenerates.

## task-2.2 — P1-9: `TB`/`Initial Auth` honor `No` / `Unspecified`
**Status:** DONE
**Reasoning (P1-9):** Spec treats TB as Y/N and requires duration-or-`Unspecified` when PA applies;
emitting `NA` in these cases diverges from gold. Forward-fixing (next run).
**Actual changes:**
- `extractors/clinical_access_extractor.py`: rewrote the TB prompt rule — since the retrieved text
  *is* the brand's criteria, absence of a TB requirement means **"No"**, not unknown; the model is
  told to return only `"Yes"`/`"No"` for TB (removed `"NA"` from the TB allowed-values list). The
  context-found return now defaults `tb_test_required` to `"No"` (was `"NA"`); the empty-context
  guard and the `except` path still return `"NA"`.
- `extractors/authorization_extractor.py`: in the context-found branch, compute
  `init_auth = parsed_output.get("initial_authorization_months")` and coerce
  `None/""/"NA" → "Unspecified"` (an auth section was retrieved ⇒ PA applies ⇒ rule forbids `NA`).
  The empty-context guard still returns `"NA"`. (The prompt already distinguished
  `Unspecified`/`NA`.)
**Verification (stubbed context + LLM):** TB context-found & omitted → `"No"`, no-context → `"NA"`;
Initial Auth context-found & LLM `"NA"` → `"Unspecified"`, no-context → `"NA"`. `py_compile` OK.
**Notes:** Forward-fix only — the shipped CSV (regenerated by task-5.1 from the **stored** JSON)
will not change for these two columns, because re-scoring/re-flatten does not re-run the LLM. Effect
appears on the next full pipeline run.

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
**Status:** DONE
**Reasoning (P1-1):** 5 extractor-owned routers → 5 throttle windows → rate limit ~5× too loose
(ADR-005 wrongly assumed a singleton). Under threaded Flask the window is a data race and the
estimate/replace could pop the wrong entry.
**Actual changes:**
- `utils/model_router.py`:
  - Added module-level `get_router()` — double-checked-lock singleton (`_ROUTER_SINGLETON`,
    `_ROUTER_SINGLETON_LOCK`).
  - `__init__`: added `self._throttle_lock = threading.Lock()` and `self._groq_uid` counter.
  - Groq window entries are now `(timestamp, tokens, uid)`. `_groq_throttle` runs its
    read-modify-write **inside** `self._throttle_lock`, returns the entry's `uid`, and releases the
    lock before `time.sleep`. New `_groq_record_actual(uid, actual_tokens)` replaces the entry by
    **uid** (not by position or by matching the estimate). `generate()` (Groq) captures `groq_uid`
    and calls `_groq_record_actual` instead of the old pop-if-matches-estimate logic.
  - `_gemini_throttle` likewise wraps its read-modify-write in the lock and sleeps outside it.
- `extractors/{age,clinical_access,authorization,utilization_management,step_therapy}_extractor.py`:
  import `get_router` and call `get_router()` instead of `ModelRouter()`.
- `pipeline_runner.py` / `run_full_pipeline.py`: **no change needed** — they never constructed a
  router directly (only via extractors); the comments referencing ModelRouter remain accurate.
**Verification:** `get_router()` returns the same instance twice; `AgeExtractor` and
`ClinicalAccessExtractor` share that one instance; two `_groq_throttle` calls with the *same*
estimate get distinct uids, and `_groq_record_actual(uid1, 4242)` updates entry0 only, leaves
entry1=1000, window size stays 2 (no wrong-entry pop). `py_compile` OK for router + all extractors.
**Notes:** Installed `groq`, `google-generativeai`, `ollama`, `python-dotenv` into the project
`.venv` (venv-only) to import the router for testing. (A `google.generativeai` deprecation
FutureWarning prints on import — library-level, unrelated to these changes.)

## task-4.2 — P1-2: Surface extraction errors; don't checkpoint failures
**Status:** DONE
**Reasoning (P1-2):** Swallowed errors produce all-`NA` rows indistinguishable from real "no data",
checkpointed as success and never retried — silently corrupting accuracy and the score.
**Actual changes:**
- All five extractors (`age`, `step_therapy`, `authorization`, `utilization_management`,
  `clinical_access`): added `import logging`; the `extract()` `except Exception as e` block now
  calls `logging.warning("... failed for %s / %s: %s", brand, pdf_name, e)` and adds
  `"extraction_error": True` to the returned fallback dict (NA values retained so scoring still
  runs, but the row is now distinguishable from genuine no-data).
- `run_full_pipeline.py`: after assembling `final_result`, it computes `errored = [...]` over the
  five sub-results; if any has `extraction_error`, it prints `[SKIP CHECKPOINT] ...` and `continue`s
  **without** appending/writing the checkpoint — so the `(filename, brand)` key stays out of
  `completed_keys` and is retried next run.
**Verification:** `AgeExtractor().extract(pages=None, ...)` (forces an internal exception) returns
`extraction_error=True` and logs `"Age extraction failed"`; the skip-detection list comprehension
flags the errored sub-result. `py_compile` OK for all extractors + `run_full_pipeline.py`.
**Notes:** Left `authorization`'s `reauthorization_required: False` bool sentinel as-is (that is the
separate, out-of-scope P2-3 consistency item).

## task-4.3 — P1-10: Resource-safe web UI sessions
**Status:** DONE
**Reasoning (P1-10):** Upload-without-stream leaks the temp file and `SESSIONS` entry forever; the
dict is mutated across threads (`threaded=True`) with no lock.
**Actual changes (`app.py`):**
- Added `import time`, `import threading`.
- `SESSIONS` now maps `session_id → (path, created_at)`, guarded by `_SESSIONS_LOCK`; added
  `SESSION_TTL_SECONDS = 600`.
- New lock-guarded helpers: `_register_session(path)`, `_get_session_path(sid)`,
  `_discard_session(sid)` (idempotent pop + unlink), and `_sweep_sessions()` (pops + unlinks any
  session older than the TTL).
- `/upload` calls `_sweep_sessions()` then `_register_session(...)`. `/stream` reads the path via
  `_get_session_path(...)` and its `finally` calls `_discard_session(session_id)` (replaces the
  raw `os.unlink` + `SESSIONS.pop`).
**Verification:** registered 2 sessions; forcing one past the TTL and sweeping removes it and
unlinks its temp file while the fresh one survives; `_discard_session` called twice is a no-op the
second time and unlinks the file; `_get_session_path("nope")` → `None`. `py_compile` OK.
**Notes:** Installed `flask` into the project `.venv` (venv-only) to import `app.py` for testing.

## task-4.4 — P1-5: Align Gemini model name in docs
**Status:** DONE
**Reasoning (P1-5):** Per product decision the model is valid — this is a documentation
consistency fix only, not a code change.
**Actual changes:**
- `.env.example` line 7: `gemini-2.0-flash-lite` → `gemini-3.1-flash-lite` (the only real
  inconsistency — it disagreed with the code).
- `README.md`: added the exact id `gemini-3.1-flash-lite` to the two Gemini rows (the backends
  table and the LLM-backends table), which already used the human name "Gemini 3.1 Flash Lite".
**Verification:** all Gemini references in `utils/model_router.py`, `.env.example`, and `README.md`
now read `gemini-3.1-flash-lite`; grep confirms no `2.0` remnants. No code change.

## task-5.1 — P1-6: Scorer version stamp + re-score + regenerate + README stats
**Status:** DONE
**Reasoning (P1-6):** The JSON mixed two scorer schemas (one legacy flat-list row scoring 70,
impossible under the current model), so the dataset wasn't reproducible from current code, and the
README's "7–50, none above 50" was contradicted by the actual max of 70. A version stamp +
deterministic re-score makes the dataset consistent and reproducible.
**Actual changes:**
- `access_quality_scorer.py`: added `SCORER_VERSION = "1.0"`; `calculate_score` now emits
  `"scorer_version": SCORER_VERSION` in its result.
- New `rescore.py`: `rescore_stored_results()` loads `outputs/final_access_results.json` and
  recomputes each row's `access_quality` from its STORED extraction dicts via the current scorer
  (no LLM, no PDF parse), writing the JSON back.
- Ran `python rescore.py` then `python result_formatter.py` to regenerate
  `outputs/final_access_results.{json,csv,xlsx}`.
- `README.md`: refreshed the score-distribution line to the regenerated numbers and added a
  reproducibility note.
**Verification (before → after re-score):** max `70 → 50`; count `>50` `1 → 0`; legacy-schema rows
`1 → 0`; `scorer_version=="1.0"` on all 79; the stale `377585-4984547.pdf/STELARA` row `70 → 25`
with a dict breakdown. **Regenerated CSV:** 79 rows; header `==` Submissions tab exactly; **0 blank
cells**; **0 sentinel cells**; formerly-leaked `287728-4459856.pdf/STELARA` Age `== "NA"`;
phototherapy header hyphenated; `Quantity Limits` before `Specialist Types`; score range 7–50.
New stats: min 7 / max 50 / mean 27.8 / median 27; categories 34 Highly Restricted, 43 Restricted,
2 FDA Parity. `py_compile` OK.
**Notes:** This regeneration is the single point where the P0-1/P0-2/P0-4/P1-6 fixes land in the
shipped CSV/XLSX. The forward-fix tasks (P1-9 etc.) affect only future full runs.

---

# Cleanup batch — spec `specs/cleanup-review-p2-p3/` (all P3 + P2-7, P2-8, P2-11)

All 9 tasks DONE. (P3-4 was already resolved by P0-1's `main()` guard — no task.)

| Task | Finding | Files | Status |
|------|---------|-------|--------|
| 1.1 | P3-1 | `extractors/step_therapy_extractor.py` | DONE |
| 1.2 | P3-2 | `extractors/step_therapy_extractor.py` | DONE |
| 1.3 | P3-3 | `extractors/{age,authorization,utilization_management,clinical_access}_extractor.py` | DONE |
| 1.4 | P3-5 | `.gitignore`, git index | DONE |
| 1.5 | P3-6 | `access_quality_scorer.py` | DONE |
| 1.6 | P3-7 | `utils/document_processor.py` | DONE |
| 2.1 | P2-7 | `utils/extractor_utils.py` | DONE |
| 2.2 | P2-8 | `access_quality_scorer.py` | DONE |
| 2.3 | P2-11 | `utils/document_processor.py` | DONE |

## task-1.1 — P3-1: remove leftover debug prints
Removed the three `print("... was used")` lines in `step_therapy_extractor.py`
(`extract_approval_section`, `extract`, `extract_step_therapy_requirements_with_llm`).
**Verified:** grep finds no "was used"; `py_compile` OK.

## task-1.2 — P3-2: restore `extract_approval_section` docstring
Removing the preceding print (task-1.1) made the triple-quoted block the method's first statement.
**Verified:** `StepTherapyExtractor.extract_approval_section.__doc__` is non-empty ("Extract ONLY the
approval criteria section…").

## task-1.3 — P3-3: repair extractor `__main__` self-tests
Found 4 of 5 harnesses still called the removed `extract(pdf_path=...)` form (only step_therapy was
correct). Fixed `age`, `authorization`, `utilization_management`, `clinical_access` to build pages
via `DocumentProcessor().process_pdf(pdf_path)` and call `extract(pages=…, brand=…, pdf_name=…)`.
**Verified:** no `pdf_path=` remains in any `__main__`; all extractors `py_compile`.
**Note:** this was *not* the no-op the spec anticipated — the broken calls were on a line separate
from `extract(`, so the earlier grep missed them; the awk-per-block check caught it.

## task-1.4 — P3-5: untrack artifacts + extend `.gitignore`
Added `.venv/`, `.DS_Store`, `*.exe`, `*.docx` to `.gitignore`. `git rm --cached` (working copies
kept) for `INSTALL_REQUIREMENTS.exe`, `PA_Business_Rules.xlsx`, `debug/*` (15 files), `outputs/*`
(6 files). **Verified:** `git ls-files` lists none of them; working copies still on disk;
`git check-ignore` matches `.venv/.DS_Store/*.exe/*.docx`. These are **staged untracks pending a
commit** the user controls (working tree unchanged).

## task-1.5 — P3-6: single-source category / fda_alignment
`fda_alignment` now derives from the **same score bands** as `access_category`
(`<50` → "More restrictive than FDA label", `50–<75` → "Near FDA parity", `>=75` → "Favorable
relative to FDA label"); removed the independent step-count branch.
**Verified:** swept 4×2×2×2×2×2×2×2 input combos → **0** category/alignment contradictions.
**Coordination:** `specs/access-score-reanchor/` task-1.1 will re-touch these bands; keep the
single-source derivation when it does.

## task-1.6 — P3-7: remove dead regex in `clean_text`
Removed the unreachable `\n{3,} → \n\n` substitution (the earlier `\n\s*\n+ → \n` already collapses
all blank-line runs). **Verified:** `clean_text` on blank-line-heavy input → `'A\nB\nC\nD'`
(unchanged behavior).

## task-2.1 — P2-7: balanced JSON extraction in `clean_json_output`
Replaced greedy `re.search(r"\{.*\}", …)` with `json.JSONDecoder().raw_decode` from the first `{`
(added `import json`); on failure returns stripped text so the caller's `json.loads` still raises.
**Verified:** trailing prose, ```` ```json ```` fences, nested objects, and extra braces all parse to
the intended object; a no-JSON string fails `json.loads` cleanly.

## task-2.2 — P2-8: robust `_parse_min_age`
Added `import re`; early-return `None` for `NA`/``/`FDA labelled age`/`No Age Restriction`; else
`re.search(r"\d+", s)` → int. Documented that `>`/`>=` map to the same integer threshold.
**Verified:** `>=6`/`6 years`/`>=6 years`/`>18`/`NA`/``/`FDA labelled age`/`No Age Restriction`
→ `6/6/6/18/None/None/None/None`.

## task-2.3 — P2-11: close fitz document
`process_pdf` now uses `with fitz.open(pdf_path) as doc:` so the native handle is released even on
exception. **Verified:** parses a real 36-page sample PDF; structure unchanged.
