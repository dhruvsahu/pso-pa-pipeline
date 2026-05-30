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

---

# Access Score re-anchor — spec `specs/access-score-reanchor/` (P0-5, deterministic full 0–100)

All 4 tasks DONE. Supersedes the earlier P0-5 deferral.

| Task | Files | Status |
|------|-------|--------|
| 1.1 re-anchor scorer | `access_quality_scorer.py` | DONE |
| 1.2 calibration fixtures | `test_scoring.py` | DONE |
| 1.3 re-score + regenerate | `rescore.py` (run), `outputs/*` | DONE |
| 1.4 docs | `README.md`, `docs/ADR.md` | DONE |

## task-1.1 — re-anchor `calculate_score` to full 0–100 (deterministic)
**Reasoning (P0-5):** old deduction-only model capped at ~58 → couldn't represent the objective's
75/100 anchors. Reopened after the Devil's Advocate review because the objective text explicitly
requires the full 0–100 scale; built deterministically (no LLM) to avoid eval-model rate-limit cost.
**Changes (`access_quality_scorer.py`):** `SCORER_VERSION "1.0" → "2.0"`; `bonuses` list renamed to
`credits` (incl. existing TB-waived/age-less entries). Added an **either/or** credit track mirroring
the deductions: no step therapy **+10**, no phototherapy **+3**, no specialist **+5**, no reauth
**+5**, no quantity limit **+3** (age-less **+5** and TB-waived **+3** already existed). Each
dimension yields a deduction OR a credit, never both; score clamped `[0,100]`. Category cutoffs
(`<25/<50/<75/≥75`) and the single-source `fda_alignment` (P3-6) were already correct → unchanged.
`score_breakdown` now `{deductions, credits}`.
**Verified:** no `bonuses` refs remain; `py_compile` OK.

## task-1.2 — calibration fixtures
**Changes:** added `test_scoring.py` asserting the three anchors (unrestricted ≥75, max-restrictive
≤10, parity-with-PA ≈50). **Result:** PASS on the first weight set — `unrestricted=79, max=0,
parity=45`. No tuning needed.

## task-1.3 — re-score stored JSON + regenerate outputs
**Changes:** ran `python rescore.py` (recompute every row's `access_quality` from stored extraction
values under v2.0 — no LLM) then `python result_formatter.py` (rebuild CSV/XLSX).
**Verified before → after:** range `7–50 → 10–76`; mean `27.8 → 36.7`; median `27 → 33`; all 79 rows
`scorer_version=="2.0"` with `credits` breakdown; **2** policies now reach Preferred (≥75); CSV 79
rows, 0 blanks, in `[0,100]`. Category split: 17 Highly Restricted, 43 Restricted, 17 FDA Parity,
2 Preferred.

## task-1.4 — docs (README + ADR)
**Changes:** README "Scoring Model" → v2.0 (deduction + credit tables, cutoffs, regenerated 10–76
stats, `test_scoring.py` note, and a note that competitive-positioning/100 isn't modelled). ADR:
added **ADR-016** (two-sided full 0–100) and marked **ADR-006 Superseded by ADR-016** (TOC +
summary-table rows updated). Note: ADR numbers 012–015 were already taken by the other-device
commit, so this is 016.

**Caveats carried forward:** weights are calibrated to synthetic anchors, **not** validated against a
gold Access Score (none provided; P1-3 validation harness still deferred). True 100 is unreachable
(max credit path ≈ +34 → ~84) because competitive formulary positioning isn't extracted.
**Also noted:** `outputs/*` are still git-tracked at `933aae2` (the P3-5 `git rm --cached` didn't
survive the earlier `reset --hard`) — untrack again before committing if desired.

---

# Review of v2.0 re-anchor → why we are changing the scorer AGAIN

A 5-perspective `/review` of the v2.0 re-anchor (see `REVIEW.md`, 2026-05-30) found a serious defect.
**Do not treat the v2.0 credit-for-absence model as final** — a follow-up spec
(`specs/fix-access-score-review/`) corrects it. Summary of why:

- **P0-1 (5/5 consensus): the credit track scored missing data (`"NA"`) as "restriction confirmed
  absent."** Measured on the 79 stored rows: `quantity_limits=="NA"` → +3 on **62 rows**;
  `specialist_types=="NA"` → +5 on **27**; `reauthorization_required=="NA"` → +5 on **14**;
  `brand_steps/generic_steps=="NA"` (parsed to 0) → +10 on **8**. Net: **68/79 rows (86%)** lifted by
  phantom credits (471 points); the **two "Preferred" rows (76)** are the **two all-`"NA"`
  extractions** (incl. the `NO BRAND MATCH FOUND` row). Counterfactual (NA→no credit): mean 36.7→30.5,
  category split 17/43/17/2 → 19/57/3/0 (**Preferred vanishes**). So "v2.0 reaches Preferred" was an
  artifact of extraction failure, not measured access.
- **P1-1 (decision: OPTION A):** even with perfect data, crediting the *absence* of step/QL/
  specialist/reauth (which the FDA baseline also lacks) inflated a true FDA-parity policy to ~76,
  breaking the objective's "50 = parity" anchor. **We chose option (a): credit ONLY strictly
  better-than-FDA terms (age-less-restrictive, TB-waived).** Consequence to record clearly: the
  absence-credits are removed, so for these PsO PA policies the practical ceiling returns to **~58**
  (50 + age 5 + TB 3) — the objective's 75/100 anchors are reachable only by hypothetically
  super-permissive/competitive policies that don't appear in this dataset. This is the **honest**
  reading (matches the original ADR-006 observation and the earlier Devil's Advocate analysis): PA
  policies only *add* restrictions vs the FDA label, so they sit at or below parity. Removing the
  buggy credits also resolves P0-1 as a side effect.
- **P1-2:** the `test_scoring.py` "parity" fixture (F3) wasn't a parity policy — it was a
  mid-restriction policy that netted to 45 by penalty/credit cancellation, so it never actually
  verified the 50-anchor and hid P0-1. Fixtures are being redone (true parity → ~50; unrestricted →
  the ~58 ceiling; add an all-`"NA"` fixture asserting ~50, NOT high).
- **P1-3 / P2 / P3:** spec weights diverged from code; `reauth != "Yes"` fragile; `_parse_min_age`
  drops `<` (3 rows get a contradictory −5); `SCORER_VERSION` is write-only (rescore.py doesn't log
  versions); regenerate-vs-rerun boundary under-documented; `PIPELINE_FLOW.md` still shows v1.0
  stats; README category notation overlaps at endpoints. All folded into the follow-up spec.

**Net for future readers:** the scorer is being moved from v2.0 (credit-for-absence, inflated) to a
corrected model under option (a) — deduction-driven with only better-than-FDA credits, faithful
50=parity, honest ~58 ceiling, and `"NA"` treated as *unknown* (neither credit nor penalty). Outputs
will be re-scored downward (Preferred band expected to empty out).

## Why option (a) caps at ~58, and the upper-range alternatives we considered

Question raised: "if option (a) caps ~58, how do we ever reach the objective's 75/100 anchors?"
Answer: **you cannot on a 'restrictions vs FDA label' axis** — a prior-authorization policy only
*adds* restrictions, and the FDA baseline for these brands already has no step/QL/specialist/reauth,
so the only better-than-FDA levers are age-younger (+5) and TB-waived (+3) → ceiling ~58. Reaching
75/100 requires changing *what the upper half measures*. Alternatives evaluated:

- **A — vs-FDA, credits only better-than-FDA (CHOSEN).** Faithful 50=parity; range ~0–58; 75/100
  unreachable for this dataset. Deterministic, no re-run. Safest if the hidden gold is also vs-FDA.
- **B — cohort-relative normalization.** Rank the 79 by restriction burden (least→~100, median→~50,
  worst→0). Guarantees full range, deterministic, no re-run — but 50 = "median policy" not literal
  FDA parity, and a score depends on the cohort.
- **C — generosity signals.** Add upside from already-extracted data (auth duration: FDA doesn't
  specify, so 12-mo/unspecified is more generous than 6-mo; broad age; TB-waived) → lenient policies
  climb to ~50–75. Deterministic, no re-run; does not reach a true 100.
- **D — competitive positioning.** Extract formulary tier / position vs competitors — the literal
  basis for "best access against all competitors." Most faithful, earns a real 100, but needs a new
  extractor + a **full LLM pipeline re-run** (eval-model token-budget cost).
- **E — GenAI holistic scoring.** LLM assigns 0–100 from the rubric. Full range, but
  non-deterministic + per-row LLM cost (deprioritized for reproducibility/rate-limits).

**Decision (user, 2026-05-30): go with A.** Rationale: there is **no gold Access Score** to validate
against, so any upper-range approach is a bet — and if the gold scored vs-FDA (PA policies ≤50),
reaching 75/100 would *increase* error. A is the faithful, deterministic, lowest-risk choice; the
75/100 region is accepted as unreachable for this dataset and that limitation is documented in
ADR-016. B/C/D/E remain on record (here + ADR-016 "Alternatives Considered") for future work if a
gold sample or competitive-positioning extraction becomes available.

---

# IMPLEMENTED — spec `specs/fix-access-score-review/` (v2.0 → v2.1, Option A). All tasks DONE.

| Task | Finding | Files | Status |
|------|---------|-------|--------|
| 1.1 | P0-1 + P1-1(a) | `access_quality_scorer.py` | DONE |
| 1.2 | P1-2 | `test_scoring.py` | DONE |
| 1.3 | P2-2 | `access_quality_scorer.py` | DONE |
| 1.4 | P2-1 | `access_quality_scorer.py` | DONE |
| 1.5 | P2-3 | `rescore.py` | DONE |
| 1.6 | P2-4 | `rescore.py`, `docs/ADR.md` | DONE |
| 1.7 | P3-3 | — | SKIPPED (optional refactor; not worth pre-commit churn) |
| 2.1 | — | `rescore.py`/`result_formatter.py` (run), `outputs/*` | DONE |
| 2.2 | P1-3, P3-1, P3-2 | `README.md`, `docs/ADR.md`, `docs/PIPELINE_FLOW.md`, reanchor spec | DONE |

**task-1.1 (P0-1 + P1-1a):** removed the five absence-credit branches (no-step +10, no-photo +3,
no-specialist +5, no-reauth +5, no-QL +3); kept only better-than-FDA credits (age-younger +5,
TB-waived +3). `"NA"`/missing now hits no branch → neutral. `SCORER_VERSION → "2.1"`.
**task-1.3 (P2-2):** age block now detects a `<` / "under" / "up to" upper bound and skips the
min-age comparison (no spurious −5, no contradictory message).
**task-1.4 (P2-1):** reauth deduction uses `str(reauth).strip().lower() == "yes"` (casing-proof).
**task-1.5 (P2-3):** `rescore.py` prints input `scorer_version` counts before overwriting.
**task-1.6 (P2-4):** `rescore.py` docstring + ADR-016 now state re-scoring reflects scoring-logic
changes only; extractor fixes need a full re-run.
**task-1.2 (P1-2):** fixtures rewritten — FDA-parity≈50, max≤10, most-permissive≈58 (≥50 & <75),
**all-`"NA"`≈50** (regression guard for P0-1).
**task-2.1 (re-score):** ran `rescore.py` + `result_formatter.py`. **Verified:** all 79 rows v2.1;
0 rows carry a removed absence-credit string; the two former all-`"NA"` "Preferred" rows
(`287728-4459856.pdf/STELARA`, `361202-4967201.pdf/TREMFYA`) **76 → 50**; range **7–50**, mean 27.8,
median 27, **0 rows ≥75**; categories 34 HR / 43 RA / 2 Parity / 0 Preferred; CSV 79 rows, 0 blanks;
re-score idempotent.
**task-2.2 (docs):** README scoring section → v2.1 (credit table = age/TB only, 7–50 stats,
half-open category notation, "why ~58" note pointing to ADR-016 alternatives). ADR-016 → Correction
with v2.1 numbers + regenerate-vs-rerun note; the withdrawn-v2.0 "10–76 / Preferred" consequence
struck through. PIPELINE_FLOW.md → version label v1.0→v2.1. `specs/access-score-reanchor/`
banner-superseded (prior turn).

**Verification:** `py_compile` OK (scorer, rescore, test_scoring, result_formatter);
`python test_scoring.py` PASS; no stale `v2.0`/`10–76`/`36.7` stats remain outside the struck/labeled
historical text.
**Net:** the score is now the faithful vs-FDA model (range ~7–50, 50=parity), the v2.0 NA-inflation
is gone, and the Preferred band is empty — the honest outcome for PsO PA policies under Option A.

---

# v2.2 — confirmed-only credit + review-fix pass (after the 2nd /review)

A second 5-perspective `/review` of v2.1 (resumed agents; see `REVIEW.md` dated 2026-05-30) confirmed
all v2.0 P0/P1 findings RESOLVED with no regressions, and raised P2/P3 follow-ups. Per user decision,
**P2-B was actioned** and the nits fixed. Changes:

**P2-B (over-correction) → v2.2 confirmed-only credit.** v2.1 removed *all* absence-credits, so a
*verified*-open policy scored the same as an unextracted one (both ~50). Added a **+2 confirmed-open
credit** per axis (`access_quality_scorer.py`) that fires ONLY on positive evidence of absence —
explicit `"No"` (phototherapy, reauth), empty list `[]` (specialist, QL), or both step counts
confirmed numeric `0` — and **never on `"NA"`**. Each axis is now tri-state: present→deduct,
confirmed-absent→+2, unknown→neutral (the tri-state the Architect originally recommended).
`SCORER_VERSION → "2.2"`. **Trade-off recorded (ADR-016):** 50 now = neutral/unknown baseline; a
fully-confirmed-open policy sits ~60; ceiling ~68 (confirmed +10, age +5, TB +3) — still <75 so
Preferred stays unreachable. `"NA"` remains neutral, so the P0-1 fix holds.

**P3-D — TB casing normalized** (`access_quality_scorer.py`): `tb_required`/`fda_tb` compared via
`.strip().lower()`, mirroring the reauth fix.

**P2-A — stale ADR lines fixed**: ADR-006 Status line and the ADR summary-table row no longer claim
"two-sided / full 0–100" (they were describing the withdrawn v2.0); both now state the vs-FDA /
ceiling-~68 / Option-A model.

**P3-E — fixtures** (`test_scoring.py`): rewritten for v2.2 — all-`"NA"`≈50 (regression guard),
confirmed-open≈60, max≤10, most-permissive≈68 (≥50 & <75), confirmed-open > all-NA, plus guards for
upper-bound age (`<18` → no deduction) and reauth casing (`"yes"` → −5).

**P3-F — `docs/PIPELINE_FLOW.md`**: scorer label `v1.0 → v2.2`; category list converted to half-open
notation; added the confirmed-open-credit note; stats updated to 9–50 / 29.7 / 29.

**P3-C — dead ≥75 band**: README + PIPELINE_FLOW category tables now annotate "Preferred [75,100] —
not reachable for this dataset (ceiling ~68)". Code branches retained (correct general definition).

**Re-scored (v2.2) + regenerated.** `rescore.py` (logged `{'2.1': 79} → 2.2`) + `result_formatter.py`.
**Verified:** all 79 rows v2.2; distribution **9–50, mean 29.7, median 29, 0 ≥75**; categories
34 HR / 43 RA / 2 Parity / 0 Preferred; credit footprint = 73 confirmed-no-photo + 2 confirmed-no-reauth
+ 2 age-younger, **0 from `"NA"`**; the two all-`"NA"` rows stay **50**; CSV 79 rows/0 blanks;
`test_scoring.py` PASS; `py_compile` OK.

**Not done (by design):** P3-G informational items (F4 input-shape comment, no-baseline brand reports
"FDA Parity" rather than "unknown", theoretical-vs-observed ceiling wording) — left as future flags;
P3-3 declarative-weights-table refactor still skipped.

**Doc trail updated:** `REVIEW.md` (2nd review), `docs/ADR.md` (ADR-016 v2.2 refinement + P2-A fixes),
`README.md`, `docs/PIPELINE_FLOW.md`, this file. `specs/fix-access-score-review/` carries a v2.2 note.

---

# P0-3 now FIXED (was deferred) + outputs re-synced to v2.2

Earlier P0-3 (Reauthorization Required derivation) was deliberately deferred. Now implemented per
user request. Also discovered the shipped `outputs/*` had drifted to **v1.0 scores** while the code
was v2.2 — re-scored to resync.

**P0-3 fix (`result_formatter.py`):** added `derive_reauth_required(reauth_required, reauth_dur,
reauth_reqs)` and wired it into `flatten_result`. Business rule: the column is **Yes/No, never
"NA"** — "Yes" if the policy states reauth required OR gives a reauth duration OR documents reauth
requirements, else "No". Applied at flatten time (the single chokepoint for both the batch CSV and
the Flask UI), so it covers regeneration and future runs without re-extraction.
**Result:** `Reauthorization Required` = 63 Yes / 16 No / **0 NA** (was 63/2/14). The 14 former-`NA`
rows all derived to "No" (none had a duration or requirements — correct, not arbitrary).

**Outputs resync:** ran `rescore.py` (logged `{'1.0': 79} → 2.2`) + `result_formatter.py`. Final
state: JSON+CSV all `scorer_version 2.2`; distribution **9–50, mean 29.7, median 29, 0 ≥75**; CSV 79
rows, header matches Submissions tab, 0 blanks. Code / docs / outputs are now all v2.2-consistent.

**Still open (deferred scope, not bugs):** notebook deliverable absent; `Age` never emits
"FDA labelled age" (P1-8); no gold-validation harness (P1-3). `REVIEW.md` is the user's restored
original full-project review (lists P0-3 etc. as open) — left as-is per user.
