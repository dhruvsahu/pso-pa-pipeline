# Code Review: PsO PA Pipeline — full project vs H1'26 Hackathon Problem Statement

**Date:** 2026-05-29
**Reviewers:** 5 local Claude agents — Chief Architect (system-design), Architect (architecture), Chief Programmer (code-quality), Requirements Analyst (requirements), Analyst (analysis)
**Scope:** Full pipeline source on the working tree (`main`): `app.py`, `pipeline_runner.py`, `run_full_pipeline.py`, `result_formatter.py`, `access_quality_scorer.py`, `utils/*`, `extractors/*`, docs, and the shipped `outputs/` + `PA_Business_Rules.xlsx`.

## Summary

The pipeline is functionally complete and well-conceived: 79/79 required (Filename, Brand) rows are produced (multi-brand handled), the step-therapy counting logic faithfully implements the Business-Rules spec, and the retrieval/deterministic-counting separation is genuinely good. The blocking problems are at the **output-contract** and **methodology** layers: 25 blank cells violate the "all params populated" rule, column header/order don't match the grading template, the `Reauthorization Required` derivation rule is unimplemented (14 invalid `NA` rows), the Access Score model is mathematically capped at ~58 so it can never reach the graded 75/100 anchors, and there is **no validation harness** against ground truth. Cross-cutting engineering issues (non-shared/non-thread-safe rate limiter, error-swallowing extractors, duplicated retrieval code, stale docs) follow.

Consensus counts are out of the **5** perspectives in this review.

---

## P0 — MUST FIX (5 issues)

### P0-1: Empty-list free-text params emit BLANK cells, not "NA"
- **Consensus:** 2/5 — **Flagged by:** chief-programmer, analyst
- **File(s):** `result_formatter.py:26-27, 36-39, 46-47`
- **What's wrong:** Precedence of `"; ".join(x) if isinstance(x, list) else x or "NA"` means an *empty list* hits the `if` branch → `"; ".join([])` → `""`. The `or "NA"` fallback only fires in the `else` (non-list) branch, so empty-list values become blank. Verified in the shipped CSV: **8 blank** "Step Therapy Requirements" + **17 blank** "Reauthorization Requirements" = **25 blank cells**.
- **Why it matters:** Directly violates the deliverable rule "All 13 parameters must be populated for each row."
- **Fix:** Helper `def join_or_na(v, sep="; "): return sep.join(v) if isinstance(v, list) and v else (v or "NA")` and use it for all four list-valued columns.

### P0-2: Output column header and order do not match the grading template exactly
- **Consensus:** 3/5 — **Flagged by:** chief-programmer, requirements-analyst, chief-architect
- **File(s):** `result_formatter.py:32, 36-39`; `app.py:38-39` (`CSV_COLUMNS`)
- **What's wrong:** (a) Header is `Step through Phototherapy` (space) but the Submissions tab requires `Step through-Phototherapy` (hyphen). (b) Column order ships `Specialist Types` before `Quantity Limits`; the template requires `Quantity Limits` (col 8) then `Specialist Types` (col 9). Both confirmed against `PA_Business_Rules.xlsx`. The schema is also defined twice (here and in `app.py`) with nothing keeping them in sync.
- **Why it matters:** A positional or strict-name grader misaligns two columns across all 79 rows and may fail the phototherapy column on the header mismatch.
- **Fix:** Restore the literal `"Step through-Phototherapy"` key and swap the two columns in **both** `flatten_result` and `CSV_COLUMNS`. Define the column list once and import it into `app.py`.

### P0-3: "Reauthorization Required" derivation rule is unimplemented → 14 invalid `NA` rows
- **Consensus:** 1/5 (corroborated by analyst's NA-convention data) — **Flagged by:** requirements-analyst
- **File(s):** `extractors/authorization_extractor.py`; `run_full_pipeline.py`; `result_formatter.py:44-45`
- **What's wrong:** Business Rules: *"If either Reauthorization Duration or Reauthorization Requirements is non-NA then this column should read 'Yes'"* — a Yes/No flag. The code passes the LLM's free value through; **14 of 79** rows read `NA` (not a permitted value).
- **Why it matters:** Wrong/invalid value on a graded parameter for ~18% of rows.
- **Fix:** Derive deterministically post-extraction: `"Yes" if (reauth_duration != "NA") or reauth_requirements else "No"`.

### P0-4: Internal error sentinel leaked into a graded cell
- **Consensus:** 1/5 — **Flagged by:** requirements-analyst
- **File(s):** `extractors/age_extractor.py` (no-match path) → `outputs/final_access_results.csv`
- **What's wrong:** Row `287728-4459856.pdf / STELARA` has `Age = "NO BRAND MATCH FOUND"`, an internal sentinel, not a valid Age value.
- **Why it matters:** Invalid value in a graded cell; signals the no-match path isn't mapped to the output convention.
- **Fix:** Map all internal sentinels to `"NA"` (or the appropriate value) before output.

### P0-5: Access Score model is structurally capped at ~58 — cannot reach the graded 75/100 anchors
- **Consensus:** 2/5 — **Flagged by:** requirements-analyst, analyst
- **File(s):** `access_quality_scorer.py` (starts at 50; only bonuses are TB-waived `+3` and age-less-restrictive `+5` = `+8` max)
- **What's wrong:** The problem defines 50=parity, **75=preferred**, **100=best/no restrictions**, but the model's reachable ceiling is ~58. Shipped scores: min 7, max 70, mean 28.3; **0 rows ≥75**, **0 rows =100**. (The lone 70 is a stale artifact — see P1-6.) Any policy the gold standard rates >58 can never be matched.
- **Why it matters:** Caps the entire "Access Score Accuracy" graded dimension; the top half of the mandated scale is unreachable by construction. The README reframes this limitation as an empirical finding ("no policy scores above 50").
- **Fix:** Re-anchor symmetrically around 50: award positive credit for genuinely-better-than-FDA terms (zero step therapy, broader age, longer auth/reauth durations, no QL/specialist/reauth) up to 100; calibrate against the gold Access Score.

---

## P1 — SHOULD FIX (10 issues)

### P1-1: `ModelRouter` is not a shared singleton and its throttler is not thread-safe
- **Consensus:** 3/5 — **Flagged by:** architect, chief-architect, chief-programmer
- **File(s):** each `extractors/*.py __init__` calls `ModelRouter()` (5 instances/run); `utils/model_router.py:68,88,97-150,160-198,266-277`; `app.py:196` (`threaded=True`)
- **What's wrong:** ADR-005 claims a singleton "one instance per pipeline run" — false. Five independent throttle windows mean the 15-RPM / 12K-TPM ceilings are enforced **per-extractor (~5× too loose)**. Under Flask `threaded=True` the rolling-window read-modify-write (and the Groq "replace estimate with actual" pop) is a data race that can corrupt the window.
- **Why it matters:** Defeats the rate limiter's purpose (relies entirely on 429 retries), undermining the checkpoint resilience story; latent corruption under the UI.
- **Fix:** One process-wide router shared across all extractors (inject it or a `get_router()` module singleton); guard deque mutations with a `threading.Lock`.

### P1-2: Extractor `except Exception` blocks swallow all errors and emit NA → checkpointed as success
- **Consensus:** 2/5 — **Flagged by:** chief-programmer, chief-architect
- **File(s):** `age_extractor.py:421-431`, `step_therapy_extractor.py:558-585`, `authorization_extractor.py:586-607`, `utilization_management_extractor.py:471-488`, `clinical_access_extractor.py:566-587`
- **What's wrong:** A JSON parse failure, KeyError, network/429-after-retries, or genuine bug all produce the same all-NA result as a legitimately empty policy. The batch runner never sees the exception (it's swallowed inside the extractor), so the NA row is **checkpointed as completed** and `completed_keys` never re-processes it; a score is still computed on NA values.
- **Why it matters:** Real failures are indistinguishable from real "no data," corrupting both extraction accuracy and the score, permanently.
- **Fix:** Add an `extraction_error` flag, log at WARNING, and skip checkpointing errored rows so re-runs retry them.

### P1-3: No validation/accuracy harness against ground truth
- **Consensus:** 2/5 — **Flagged by:** requirements-analyst, analyst
- **File(s):** entire repo (no accuracy/eval code exists)
- **What's wrong:** Both graded dimensions (per-param extraction accuracy, Access Score accuracy) are un-self-assessable. The Submissions `Access Score` column is empty (gold withheld); `Additional Extracted Data` covers entirely different policies (0/79 overlap). No code computes match rate / MAE.
- **Why it matters:** The team ships blind and cannot tune or defend results; the "average 28" claim only describes its own output.
- **Fix:** Build a harness joining `result.csv` to gold on (Filename, Brand): per-param normalized match rate + score MAE/correlation. Use the `Reference` worked example (`250819`/Yesintek) as a unit-test fixture now.

### P1-4: The (file, brand) work-list is fed from the ground truth; no brand discovery
- **Consensus:** 1/5 — **Flagged by:** analyst
- **File(s):** `assets/sample_batch.csv` vs `PA_Business_Rules.xlsx` Submissions tab (exact 79/79 set-match)
- **What's wrong:** "Which brands live in each PDF" — including all multi-brand cases — is read from the answer key rather than discovered, bypassing the hardest sub-problem the brief explicitly grades (multi-brand + scalability).
- **Why it matters:** The solution won't generalize to unseen PDFs where the brand list is unknown.
- **Fix:** Discover candidate brands from PDF text (the shipped `therapy_dictionary_normalized.csv` enables this) and derive the work list; report discovered-vs-supplied overlap as a metric.

### P1-5: Gemini model id `gemini-3.1-flash-lite` is invalid / inconsistent
- **Consensus:** 3/5 — **Flagged by:** chief-programmer, chief-architect, architect
- **File(s):** `utils/model_router.py:83` vs `.env.example:7` (`gemini-2.0-flash-lite`) vs README ("Gemini 3.1 Flash Lite")
- **What's wrong:** Not a real model id; the Gemini path will 404 on first call and then be swallowed by P1-2 → all-NA rows. Hardcoded, not env-overridable.
- **Fix:** Use `gemini-2.0-flash-lite` (or read from env) and make README/`.env.example`/code agree.

### P1-6: Stale checkpoint row from an older scorer → non-reproducible output; README claims contradicted
- **Consensus:** 1/5 — **Flagged by:** analyst
- **File(s):** `outputs/final_access_results.json` (row `377585-4984547.pdf`/STELARA, score 70); `README.md:142-171`
- **What's wrong:** That row's `score_breakdown` is a flat prose list (old schema); the other 78 use the current `{deductions, bonuses}` schema. Its 70 is impossible under the current model (brand_steps=2, reauth → ~25). The checkpoint logic doesn't re-score on scorer changes, so the dataset mixes two scorer versions. README's "range 7–50… no policy above 50" is contradicted by the actual max of 70.
- **Fix:** Delete that entry and re-run; add a scorer-version stamp to auto-invalidate stale rows; regenerate README stats from the final CSV.

### P1-7: Notebook deliverable absent; Access Score methodology undocumented
- **Consensus:** 2/5 — **Flagged by:** requirements-analyst, analyst
- **File(s):** repo root (no `.ipynb`); `access_quality_scorer.py` (weights only in inline comments)
- **What's wrong:** Deliverables ask for "Notebook(s)… all intermediate and final outputs visible." None exists. Scoring weights (−10/brand step, −5/generic, −8 specialist…) have no cited derivation or sensitivity analysis.
- **Fix:** Add a notebook (or documented driver) showing ingestion → per-extractor outputs → scoring → result.csv; document and justify the weights.

### P1-8: "FDA labelled age" fallback never fires; scorer mishandles it
- **Consensus:** 2/5 — **Flagged by:** requirements-analyst, chief-programmer
- **File(s):** `extractors/age_extractor.py` (prompt maps "adult" → `>=18`); `access_quality_scorer.py:281-324`
- **What's wrong:** The rule wants `"FDA labelled age"` when a policy indicates the drug without a numeric threshold, but the prompt forces adult-only wording to `>=18` (0/79 rows ever output "FDA labelled age"). And `_parse_min_age("FDA labelled age")` → `None`, which isn't in the scorer's exclusion set → can apply a wrong `-5` penalty.
- **Fix:** Reserve `>=18` for explicit numeric wording; emit "FDA labelled age" for indication-only adult wording; add "FDA labelled age" to the scorer's neutral-exclusion set.

### P1-9: TB "No" vs "NA" and Initial-Auth "Unspecified" conventions not honored
- **Consensus:** 1/5 — **Flagged by:** requirements-analyst
- **File(s):** `extractors/clinical_access_extractor.py` (TB), `extractors/authorization_extractor.py` (initial auth)
- **What's wrong:** TB outputs Yes/NA with no "No" — when criteria are found but no TB test is mentioned, the answer should be "No", not "NA". Initial Auth: when PA-for-PsO applies, the rule requires a duration or "Unspecified", not "NA" (16 NA rows; no PA-for-PsO field exists to gate it).
- **Fix:** Distinguish "criteria found, not required" (No) from "no context" (NA); coerce NA→"Unspecified" when a PsO authorization section exists.

### P1-10: Flask UI leaks temp files and `SESSIONS` entries; thread-unsafe shared dict
- **Consensus:** 2/5 — **Flagged by:** architect, chief-architect
- **File(s):** `app.py:29, 70-93, 107-161, 196`
- **What's wrong:** `/upload` persists a temp PDF + `SESSIONS` entry; cleanup only happens in the `/stream` `finally`. A client that uploads but never opens the stream leaks both forever. `SESSIONS` is a plain dict mutated across threads (`threaded=True`) with no lock/TTL.
- **Fix:** TTL-expire sessions + sweep orphaned temp files; guard `SESSIONS` with a lock.

---

## P2 — RECOMMENDED (13 issues)

- **P2-1: Retrieval logic duplicated across 4 extractors + redundant per-page scanning.** *(3/5: chief-architect, architect, chief-programmer)* `_collect_strict`/`_collect_proximity`/union-dedup are copy-pasted (with subtly different regexes `===== PAGE (\d+)` vs `PAGE (\d+)`); each PDF is lowercased+scanned ~10× per row and `brand_indices` rebuilt repeatedly. Extract one `KeywordRetriever`; pre-compute `page["lower"]` and `brand_indices` once. `extractors/*.py`, `utils/extractor_utils.py`.
- **P2-2: Two entry points re-implement orchestration** with different result-dict key names. *(1/5: chief-architect)* Make `pipeline_runner.run_pipeline` the single orchestrator that `run_full_pipeline` consumes. `pipeline_runner.py:26-101`, `run_full_pipeline.py:133-256`.
- **P2-3: Hardcoded relative paths assume CWD = repo root.** *(1/5: chief-architect)* Scorer/extractor CSV reads at import time throw `FileNotFoundError` from any other directory. Anchor to `Path(__file__).parent` / a `config.py`. `access_quality_scorer.py:14`, `step_therapy_extractor.py:17`, et al.
- **P2-4: `select_model()` is dead code and logs a fake "[MODEL SELECTED] qwen2.5:7b"** on Groq/Gemini runs. *(3/5: chief-architect, architect, chief-programmer)* Both branches return the same value; only meaningful for Ollama. Collapse it; stop calling/logging it outside the Ollama path. `utils/model_router.py:204-215`.
- **P2-5: No concurrency + O(n²) checkpoint rewrite** (scalability). *(1/5: architect)* The whole `all_results` list is re-dumped after every row (non-atomic crash window). After P1-1, run the 5 extractors per row via a thread pool; write JSONL or temp-file+`os.replace()`. `run_full_pipeline.py:243-247`.
- **P2-6: Docs materially out of sync with code.** *(2/5: chief-architect, architect)* ADR-004/PIPELINE_FLOW tell users to set `MODEL_PROVIDER` (read nowhere) and say PDF parsing uses `pdfplumber` (it's PyMuPDF/`fitz`); `tenacity` in `requirements.txt` is unused. Fix docs; honor a real `MODEL_PROVIDER` or remove the claim; drop `tenacity`.
- **P2-7: `clean_json_output` greedy `\{.*\}` regex** can over-capture trailing prose/braces → `json.loads` failure → silent NA. Use a balanced-brace scanner or `JSONDecoder().raw_decode`. *(1/5: chief-programmer)* `utils/extractor_utils.py:77-84`.
- **P2-8: `_parse_min_age` conflates `>` with `>=` and chokes on extra text** (`">18"`→18; `"6 years"`→None). Regex-extract the first integer; handle `>` explicitly. *(1/5: chief-programmer)* `access_quality_scorer.py:52-65`.
- **P2-9: Substring brand matching → false positives;** the `"ql"` retrieval keyword matches inside ordinary words. Use word-boundary regex for short tokens; drop/lengthen `"ql"`. *(1/5: chief-programmer)* `utils/extractor_utils.py`, `utilization_management_extractor.py:31`.
- **P2-10: Missing-FDA-baseline path silently biases scores downward** (specialist→"No" still penalizes, TB upside lost, age penalty fires). Harmless for the current 15 brands but the market basket has 35. Emit an "unreliable score" flag; extend `fda_baselines.csv`. *(1/5: analyst)* `access_quality_scorer.py:101-104`.
- **P2-11: `fitz.open()` is never closed** — native handle/memory leak across the 79-PDF batch. Use `with fitz.open(...) as doc:`. *(1/5: architect)* `utils/document_processor.py:71-96`.
- **P2-12: Inconsistent context truncation** — Age uses `[:12000]`, the other four `[:20000]` (ADR-010 claims 20K everywhere). Hoist one `MAX_CONTEXT_CHARS`. *(1/5: architect)* `age_extractor.py:196`.
- **P2-13: Reference CSVs reloaded on every instantiation;** `AccessQualityScorer` built 2–3× per process. Load once into module-level immutables. *(1/5: architect)* `access_quality_scorer.py:14`, `step_therapy_extractor.py:17`.

---

## P3 — MINOR (7 issues)

- **P3-1: Leftover debug prints** in the hot path (`step_therapy_extractor.py:282, 402, 596` — "main extraction was used", etc.). Remove or use `logging.debug`. *(3/5)*
- **P3-2: `print()` before a triple-quoted string** makes it a no-op expression, not a docstring (`step_therapy_extractor.py:282-293`). *(2/5)*
- **P3-3: Stale `__main__` harnesses call `extract(pdf_path=...)`** but the signature is `(pages, brand, pdf_name)` — every one except step_therapy's `TypeError`s immediately. *(2/5)* `age_extractor.py:442`, etc.
- **P3-4: `result_formatter.py` does file I/O + prints at import time** (`:57-122`) rather than under `if __name__ == "__main__"`. *(1/5)*
- **P3-5: Dev/data artifacts committed:** `.DS_Store`, `INSTALL_REQUIREMENTS.exe` (actually a one-line shell command), `PA_Business_Rules.xlsx`, the `.docx`, `outputs/*`, `debug/*`. Add to `.gitignore`. *(1/5)*
- **P3-6: `fda_alignment` vs `access_category`** use two overlapping classification schemes for the same score and can disagree (`access_quality_scorer.py:357-377`). Derive both from one source. *(1/5)*
- **P3-7: Dead regex in `clean_text`** — the `\n{3,}→\n\n` pass is unreachable after the earlier `\n\s*\n+→\n` already collapsed blank-line runs (`document_processor.py:24-58`). *(1/5)*

---

## Positive Observations

- **Step-therapy extraction is excellent and spec-faithful** — union (AND) of universal + indication criteria, moderate-to-severe only, least-restrictive OR path, "≥N of list" = 1 slot, intolerance cascade = 1 slot, phototherapy excluded from counts. Counting is deterministic via `len(slots)`, not the LLM. *(requirements-analyst, all)*
- **Quantity Limits rule correctly enforced** — captures only text explicitly labelled "quantity limit", excludes "dosing limit". *(requirements-analyst)*
- **Row coverage is exact** — 79/79 (Filename, Brand) pairs, multi-brand rows included; FDA baselines cover 15/15 batch brands; score arithmetic internally consistent for 78/79 rows. *(analyst)*
- **Sound architectural seams** — provider abstraction at `generate()`, page-level retrieval (no vector store) matching the brand-in-formulary problem, per-extractor debug dumps, checkpoint/resume by (filename, brand). *(chief-architect, architect)*
- **Rolling-window throttler design is the right model** conceptually — it just needs to be shared + locked. *(architect)*

---

*Engineering linchpin:* fix P1-1 (shared, locked router) first — it's both a current correctness risk and the precondition for the concurrency the "process many PDFs efficiently" goal needs. *Deliverable linchpins:* P0-1/P0-2/P0-3 (output contract) and P0-5/P1-3 (scoring + validation) are what a grader actually scores.
