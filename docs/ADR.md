# Architecture Decision Record
## PsO Prior Authorization Access Quality Pipeline

**Project:** PsO ADS Track — Hackathon  
**Date:** 2026-05-29  
**Status:** Accepted  
**Authors:** Dhruv

---

## Table of Contents

1. [ADR-001 — PDF-to-Page Extraction Strategy](#adr-001)
2. [ADR-002 — Two-Pass Keyword Retrieval with Union](#adr-002)
3. [ADR-003 — Relevance Sorting with Page Cap](#adr-003)
4. [ADR-004 — LLM Model Routing](#adr-004)
5. [ADR-005 — Gemini RPM Throttler](#adr-005)
6. [ADR-006 — FDA Parity Baseline Scoring](#adr-006)
7. [ADR-007 — Checkpoint-Based Pipeline Execution](#adr-007)
8. [ADR-008 — Step Therapy Slot Model](#adr-008)
9. [ADR-009 — Brand-Aware Renewal Sweep](#adr-009)
10. [ADR-010 — Context Window Limit (20K chars)](#adr-010)
11. [ADR-011 — Internal Sentinels Mapped to "NA" in Output](#adr-011)
12. [ADR-012 — Extraction Error Flag and Checkpoint Skip](#adr-012)
13. [ADR-013 — Scorer Version Stamp](#adr-013)
14. [ADR-014 — TB "No" vs "NA" and Auth "Unspecified" Semantics](#adr-014)
15. [ADR-015 — Session TTL and Thread-Safe UI State](#adr-015)
16. [ADR-016 — Access Score Re-Anchor (Option A, v2.2; supersedes ADR-006)](#adr-016)

---

## ADR-001 — PDF-to-Page Extraction Strategy {#adr-001}

**Status:** Accepted

### Context
Prior authorization policy documents are PDFs ranging from 2 to 380+ pages. Some are single-drug dedicated policies; others are large multi-drug formularies. Content relevant to a specific brand can appear on any page with no consistent structure across payers.

### Decision
Use `DocumentProcessor` to extract each PDF as a list of `{page_number, text}` dicts — one entry per page — rather than treating the entire document as a single string.

### Rationale
- Page-level granularity enables targeted keyword retrieval (strict + proximity passes) without loading the entire document into the LLM context
- Page numbers are preserved, enabling proximity windowing (e.g. ±2 pages from a brand mention)
- Debug context files show exactly which pages were retrieved, making failures traceable

### Consequences
- **Positive:** Retrieval is fast and deterministic; no semantic embeddings or vector stores needed
- **Positive:** Works on any PDF structure (dedicated single-drug or 380-page formulary)
- **Negative:** Pages that split a sentence mid-way may cause keyword misses at page boundaries (rare in practice)

---

## ADR-002 — Two-Pass Keyword Retrieval with Union {#adr-002}

**Status:** Accepted

### Context
Early pipeline versions used only a "strict" pass: collect pages where **both** the brand name AND a relevant keyword appear. This reliably found pages that explicitly mentioned the brand alongside criteria, but missed criteria pages in single-drug policy documents where the brand name only appears in the header (page 1) and the criteria text spans pages 2–4 with no repeated brand mention.

### Decision
All five extractors run **both** passes on every document and take their **union**:
1. **Strict pass** — pages where brand name AND keyword co-occur
2. **Proximity pass** — pages with relevant keywords within ±N pages of any brand-mention page

Pages are deduplicated by page number (extracted via regex from the `===== PAGE N =====` header). The proximity window varies by extractor: ±2 for most, ±4 for Authorization.

### Rationale
- Strict pass alone missed criteria pages 2–3 in dedicated single-drug docs
- Proximity pass alone would pull too many unrelated pages in large formularies
- Union of both gives maximum recall without significant noise — tight sort signals handle ranking

### Consequences
- **Positive:** Criteria pages in both single-drug docs and large formularies are captured
- **Positive:** No false negative from brand-only appearing on a title page
- **Negative:** Slightly more pages retrieved per run; mitigated by the 15-page sort cap (ADR-003)

---

## ADR-003 — Relevance Sorting with Page Cap {#adr-003}

**Status:** Accepted

### Context
Large multi-drug formularies (e.g. Centene 87-page, OHP 380-page) caused context explosion: the union of strict + proximity pages could reach 60–65 pages (~165K chars), far exceeding any LLM's context window. Broad sort keywords like "biologic" or "inadequate response" appear throughout background sections, so naive sorting by these terms did not surface the actual criteria pages.

### Decision
`sort_by_relevance()` in `extractor_utils.py` accepts **tight signal keywords** specific to each extractor's content type. Pages are ranked by number of signal keyword hits (descending). The top **15 pages** are kept; the rest are discarded before joining.

Each extractor maintains its own `*_sort_signals` list of tight terms (e.g. `"initial authorization"`, `"approval criteria"`, `"plaque psoriasis"`) that appear specifically on criteria pages, not on background or clinical trial pages.

### Rationale
- 15 pages × ~2,500 chars/page ≈ 37K chars; after the 20K LLM truncation, ~8 most-relevant pages reach the model
- Tight signals outrank background pages reliably — confirmed on OTULFI (Centene 87-page policy) where "must use Stelara" page floated into the top 8

### Consequences
- **Positive:** Context stays manageable for all document sizes
- **Positive:** Most-relevant criteria pages always enter the LLM window first
- **Negative:** Very long policies where criteria appear on page 16+ may still be missed if signal density on those pages is low — known limitation

---

## ADR-004 — LLM Model Routing {#adr-004}

**Status:** Accepted (updated 2026-05-30)

### Context
The pipeline needs to support multiple LLM backends: Gemini (cloud, fast, rate-limited), Groq/llama-3.3-70b (cloud, for final presentation), and Ollama (local, unlimited, slower). No single model is optimal for all situations.

### Decision
`ModelRouter` in `utils/model_router.py` auto-selects the active backend at startup by checking which API key is present in the environment. All extractors call `model_router.generate(prompt, context)` — they are completely unaware of which model is in use.

Provider priority: `GROQ_API_KEY` present → Groq; else `GEMINI_API_KEY` present → Gemini; else → Ollama (local fallback). Switching backends requires only changing which key is set in `.env`.

### Rationale
- Development uses Gemini (fast iteration, free tier)
- Presentation uses Groq/llama-3.3-70b (zero code changes needed)
- Local fallback via Ollama ensures the pipeline works without internet access
- Single interface prevents extractor-level changes when swapping models

### Consequences
- **Positive:** Zero code changes to switch from Gemini to Groq for presentation
- **Positive:** Local Ollama fallback for offline development
- **Negative:** Model capability differences (context window, instruction following) mean prompts must target the lowest common denominator

---

## ADR-005 — Rolling-Window Rate Throttlers {#adr-005}

**Status:** Accepted (updated 2026-05-30 — singleton enforcement, Groq token throttle)

### Context
Gemini Flash Lite free tier: 15 RPM, 500 RPD. Groq llama-3.3-70b: 12K TPM. At 79 PDFs × 5 LLM calls = ~395 calls total. Hardcoded `time.sleep(20)` between calls was used initially but wasted time when requests were well under the rate limit.

### Decision
Replace all hardcoded sleeps with rolling-window throttlers in `ModelRouter`:

**Gemini** — `_gemini_throttle()`: a `deque` of request timestamps over the last 60s. Before each call: evict entries older than 60s; if `len(window) < 12` (80% of 15 RPM) proceed; otherwise sleep until the oldest entry ages out + 0.5s.

**Groq** — `_groq_throttle(estimated_tokens)`: a `deque` of `(timestamp, tokens, uid)` tuples over the last 60s. Before each call: evict old entries, sum tokens in window, check headroom against 90% of 12K TPM. Returns a unique `uid`; after the call, `_groq_record_actual(uid, actual_tokens)` replaces the estimate by uid so the window stays accurate under concurrency.

**Singleton enforcement:** `get_router()` (module-level, double-checked lock) guarantees one `ModelRouter` per process. All extractors call `get_router()` instead of constructing their own — previously 5 independent windows gave an effective rate ~5× the target. All throttle read-modify-write runs under `self._throttle_lock`; the lock is released before sleeping so other threads can make progress.

### Rationale
- 80% / 90% targets avoid hitting hard limits while maximizing throughput
- Rolling window is more accurate than fixed-interval sleeps
- Singleton + lock eliminates the 5× overshoot and data races under Flask `threaded=True`
- Groq uid-based replacement prevents concurrent calls from corrupting each other's accounting

### Consequences
- **Positive:** Maximum throughput within rate limits; no unnecessary sleeping
- **Positive:** Self-correcting — bursts auto-throttle; slow extractions don't sleep
- **Positive:** Thread-safe under concurrent Flask requests
- **Negative:** Single lock serializes throttle checks (sub-millisecond; not a bottleneck)

---

## ADR-006 — FDA Parity Baseline Scoring {#adr-006}

**Status:** Superseded by [ADR-016](#adr-016) — the 50-baseline anchor is retained, but the scoring
was reworked (v2.2): deductions for restrictions beyond FDA, a small +2 confirmed-open credit per
axis, and strictly-better-than-FDA credits (age +5, TB +3). `"NA"` is neutral. Practical ceiling
~68; the 75/100 "Preferred" anchors are not reachable from the extracted parameters for this dataset
(Option A).

### Context
The problem statement requires measuring "access quality" for a given payer's PA policy. Access quality is inherently relative — restrictive compared to what? Two reference points were considered: (a) average payer policy, (b) FDA prescribing label.

### Decision
Use the **FDA prescribing label** as the baseline (score = 50). The FDA label represents the minimum clinical evidence-based standard for drug approval. Any payer restriction beyond the FDA label is a deduction; any payer leniency relative to the FDA label is a bonus.

```
Score = 50 (FDA parity)
      - brand step penalties    (−10/step, cap −30)
      - generic step penalties  (−5/step, cap −15)
      - phototherapy mandate    (−5)
      - specialist restriction  (−8)
      - reauthorization         (−5)
      - quantity limits         (−5)
      - TB test beyond FDA      (−3)
      - age more restrictive    (−5)
      + TB test waived vs FDA   (+3)
      + age less restrictive    (+5)
```

Scores are clamped to [0, 100]. Categories:
- 75–100: Preferred Access
- 50–75: FDA Parity
- 25–50: Restricted Access
- 0–25: Highly Restricted

### Rationale
- FDA label is objective, published, and drug-specific
- Scoring above 50 requires a payer to be MORE permissive than FDA — rare in practice (only TB waiver +3 or age leniency +5 can push above 50)
- All 79 results scored 7–50 (average 28), consistent with real-world PA policies universally adding restrictions beyond FDA label

### Consequences
- **Positive:** Objective, reproducible baseline per drug
- **Positive:** Score distribution (7–50) correctly reflects real-world payer behaviour
- **Negative:** Phototherapy-as-alternative (patient can choose MTX instead) scores the same as no phototherapy — partial credit not modelled
- **Negative:** Two source data errors (wrong PDFs) produce misleading score of 50 (default) — flagged separately

---

## ADR-007 — Checkpoint-Based Pipeline Execution {#adr-007}

**Status:** Accepted

### Context
Running 79 PDFs × 5 LLM calls ≈ 395 API calls takes ~45–90 minutes. A crash, network timeout, or rate limit error mid-run would lose all progress without a persistence strategy.

### Decision
`run_full_pipeline.py` saves results incrementally:
1. On startup: load `outputs/final_access_results.json` if it exists; build a `completed_keys = {(filename, brand)}` set
2. Skip any row already in `completed_keys`
3. After each drug completes: append result and write the full JSON to disk immediately

Re-running the pipeline after any failure resumes from the last saved position with no duplicates.

### Consequences
- **Positive:** Zero work lost on crash or interruption
- **Positive:** Supports partial runs (e.g. Batch A of 10 for debugging, then full 79)
- **Negative:** Stale/incorrect results must be manually deleted from the JSON before rerunning (as done for OTULFI, BIMZELX, TREMFYA during debugging)

---

## ADR-008 — Step Therapy Slot Model {#adr-008}

**Status:** Accepted

### Context
Payer policies express step therapy requirements in several structural patterns that naively map to different step counts:
- **Sequential AND:** "Must fail A, then must fail B" → 2 steps
- **OR alternatives:** "Must fail A or B" → 1 step with 2 alternatives
- **At-least-N-of list:** "Must fail at least 2 of [A, B, C, D]" → 1 step (not 2)
- **Intolerance cascade:** "Must fail A; if intolerant → fail B; if intolerant → fail C" → 1 step with A/B/C as alternatives

Early extraction treated each item as a separate step, inflating generic_steps (e.g. YESINTEK returned 3 generic steps instead of 1).

### Decision
The LLM is instructed to output **slots** rather than counts. Each slot = one required trial. Alternatives within a slot are `"alternatives": [...]`. Step count is computed deterministically as `len(slots)` — not by the LLM.

The prompt includes explicit worked examples for all four patterns, with a CRITICAL RULE specifically for intolerance cascades using signal phrases: `"if intolerant to"`, `"if contraindicated to"`, `"if unable to take"`.

### Consequences
- **Positive:** YESINTEK: 3 generic steps → 1 (correct)
- **Positive:** "At least 2 of 6 options" → 1 slot, not 2 or 6
- **Positive:** Step count is deterministic (Python `len()`), not LLM-hallucinated
- **Negative:** LLM must correctly identify cascade boundaries; ambiguous policy language can still cause misclassification

---

## ADR-009 — Brand-Aware Renewal Sweep {#adr-009}

**Status:** Accepted

### Context
For large multi-drug formularies (e.g. OHP 380-page), the strict and proximity passes collected renewal/reauthorization pages from adjacent drugs rather than the target brand. This caused renewal content for unrelated drugs to pollute the Authorization extractor's context.

A simpler fix — checking if any collected page contained a renewal keyword — failed because pages from adjacent drug sections naturally contained "renewal" without mentioning the target brand.

### Decision
After strict + proximity union, the Authorization extractor checks whether any collected page contains **both** the brand name AND a renewal keyword (`"renewal"`, `"reauthorization"`, `"continuation"`, etc.). If not, a third **renewal sweep** pass runs: ±8 pages around brand-mention pages, renewal keywords only.

### Rationale
- Brand-aware check prevents false positives from adjacent-drug renewal sections
- ±8 window is wider than the standard ±4 to catch renewal sections that appear several pages after the initial criteria section (common in large formularies)
- Only triggered when normal collection lacks brand-specific renewal content

### Consequences
- **Positive:** CIMZIA (OHP 380-page): renewal pages correctly retrieved
- **Positive:** No noise from adjacent drug renewal sections
- **Negative:** ±8 sweep may still pull unrelated renewal pages in extremely dense multi-drug PDFs — mitigated by sort_by_relevance ranking

---

## ADR-010 — Context Window Limit (20K chars) {#adr-010}

**Status:** Accepted

### Context
After retrieval and sorting, each extractor truncates the joined context to a fixed character limit before sending to the LLM. The original limit was 20K chars. During debugging a 165K-char context explosion (OTULFI, Centene 87-page), raising the limit to 40K was considered.

### Decision
Keep the limit at **20K chars** for all extractors. The 40K proposal was rejected.

### Rationale
- Primary LLM for final presentation: Groq llama-3.3-70b with **12K TPM** (tokens per minute). At ~4 chars/token, 20K chars ≈ 5K tokens. A 40K-char context ≈ 10K tokens — nearly the entire minute's quota in a single call.
- The root cause of context explosion (OTULFI) was solved by the `sort_by_relevance()` 15-page cap (ADR-003), not by increasing the limit
- At 20K chars with tight sorting, the 8 most-relevant pages always reach the model; raising the limit adds noise, not signal

### Consequences
- **Positive:** Safe for Groq llama-3.3-70b presentation run (5K tokens/call vs 12K TPM quota)
- **Positive:** Forces reliance on relevance sorting rather than brute-force context inclusion
- **Negative:** Very long criteria sections (e.g. a 3,000-char single page) reduce the number of pages that fit in the window from ~8 to ~6

---

## ADR-011 — Internal Sentinels Mapped to "NA" in Output {#adr-011}

**Status:** Accepted

### Context
Extractors use internal sentinel strings to signal a non-result — e.g. the Age extractor returns `value = "NO BRAND MATCH FOUND"` when the target brand is not found in any retrieved page. One such sentinel leaked into the shipped `result.csv` (row `287728-4459856.pdf` / STELARA, Age column), which is not a valid value for a graded parameter. The deliverable requires every parameter cell to hold a spec-valid value, and the convention for "no value" is `NA`.

### Decision
Internal sentinels never appear in output. This is enforced in two layers:
1. **At source:** the Age extractor's no-match path returns `value = "NA"` (the brand-not-found detail is preserved in the `reasoning` field for debugging), rather than `"NO BRAND MATCH FOUND"`.
2. **Defensively at flatten time:** `result_formatter.flatten_result` runs every emitted cell through `clean_cell`, which maps a small set of known sentinels/blanks (`"NO BRAND MATCH FOUND"`, `""`, `None`) to `"NA"`. This corrects the already-shipped CSV on the next regeneration without re-running the LLM pipeline.

### Rationale
- The source fix prevents recurrence on future runs; the flatten-time guard fixes the stored data and protects against any other extractor emitting a sentinel.
- Two layers keep the output contract robust even if an extractor's internal conventions change.

### Consequences
- **Positive:** No internal sentinel can reach a graded cell; the leaked Age cell becomes `NA` on regeneration.
- **Positive:** `clean_cell` reinforces the "no blank cells" guarantee from the empty-list→`NA` fix.
- **Negative:** A genuinely informative non-result is flattened to `NA`; the distinction is retained only in the JSON `reasoning` field, not the CSV.

---

## ADR-012 — Extraction Error Flag and Checkpoint Skip {#adr-012}

**Status:** Accepted

### Context
All five extractors wrapped their `extract()` method in `except Exception`, returning an all-NA fallback dict. The batch runner could not distinguish a genuine "no data in policy" NA result from a crash (JSON parse failure, network error, KeyError). Crashed rows were checkpointed as completed and never retried.

### Decision
Each extractor's `except` block now adds `"extraction_error": True` to the fallback dict and logs at `WARNING` level. The batch runner (`run_full_pipeline.py`) checks all five sub-results for this flag; if any is set, the row is **not** checkpointed — leaving it in the retry pool for the next run.

### Rationale
- Real failures are now visible in logs and distinguishable from legitimate no-data
- Skipping checkpoint ensures re-runs retry failed rows automatically
- NA values are still emitted so scoring can proceed (score on partial data is better than no score)

### Consequences
- **Positive:** Transient errors (rate limits, network timeouts) auto-recover on re-run
- **Positive:** Logs identify exactly which extractor failed and why
- **Negative:** A persistently failing extractor (e.g. bad prompt for one brand) will retry indefinitely until the JSON entry is manually added

---

## ADR-013 — Scorer Version Stamp {#adr-013}

**Status:** Accepted

### Context
A stale checkpoint row (`377585-4984547.pdf / STELARA`) used an older scoring schema (flat prose list, score 70) that was impossible under the current model (brand_steps=2 should score ~25). The checkpoint logic did not detect or invalidate rows from a previous scorer version.

### Decision
`access_quality_scorer.py` defines `SCORER_VERSION = "1.0"` and stamps it onto every `access_quality` result. A companion `rescore.py` script recomputes all scores from stored extraction dicts using the current scorer — no LLM calls, no PDF parsing.

### Rationale
- Version stamp makes mixed-schema datasets immediately detectable
- Deterministic re-score from stored data is fast and safe (< 1 second for 79 rows)
- Decouples scorer iteration from expensive LLM re-extraction

### Consequences
- **Positive:** Stale row 70 corrected to 25; all 79 rows now use consistent schema
- **Positive:** Scorer changes can be applied retroactively without re-running the pipeline
- **Negative:** `rescore.py` must be run manually after scorer changes; no auto-invalidation

---

## ADR-014 — TB "No" vs "NA" and Auth "Unspecified" Semantics {#adr-014}

**Status:** Accepted

### Context
The TB test field emitted only "Yes" or "NA", conflating "criteria found, TB not required" with "no criteria found at all". The initial authorization duration field emitted "NA" when the authorization section existed but stated no specific month count — but the business rules require "Unspecified" in this case, reserving "NA" for when no authorization section is found.

### Decision
- **TB:** When clinical access criteria are retrieved (past the empty-context guard), the LLM is instructed to return only "Yes" or "No". The default fallback is "No" (criteria found, TB not mentioned = not required). "NA" is returned only from the empty-context guard or the error path.
- **Initial Auth:** When the authorization section is found (past the empty-context guard), a post-parse coercion maps `None` / `""` / `"NA"` to `"Unspecified"`. "NA" is returned only when no authorization context is found at all.

### Rationale
- Distinguishes "not required" from "unknown" — important for scoring accuracy
- "Unspecified" aligns with the business rules' intent: PA applies, so a duration exists even if not stated
- Forward-fixing: takes effect on the next pipeline run; stored data unchanged

### Consequences
- **Positive:** TB output now has three meaningful states: Yes / No / NA
- **Positive:** Auth duration distinguishes Unspecified (PA exists, no months stated) from NA (no PA section)
- **Negative:** Stored results from prior runs still carry the old semantics until re-extracted

---

## ADR-015 — Session TTL and Thread-Safe UI State {#adr-015}

**Status:** Accepted

### Context
The Flask UI (`app.py`, `threaded=True`) stored uploaded PDF temp paths in a plain `dict`. A client that uploaded but never opened the `/stream` endpoint leaked the temp file and dict entry forever. The dict was mutated across threads with no synchronization.

### Decision
Sessions are stored as `(path, created_at, original_name)` tuples in a `dict` guarded by `threading.Lock`. A 600-second TTL is enforced: `_sweep_sessions()` runs on each `/upload` and reaps expired entries (deletes temp file + pops dict entry). Lock-guarded helpers (`_register_session`, `_get_session`, `_discard_session`) encapsulate all access.

### Rationale
- TTL prevents temp file and memory leaks from abandoned uploads
- Lock eliminates data races under `threaded=True`
- Sweep-on-upload is opportunistic and avoids a background timer thread
- Original filename is preserved in the session tuple for accurate CSV output

### Consequences
- **Positive:** No leaked temp files or dict entries; thread-safe access
- **Positive:** Original PDF filename appears in `results.csv` (not "uploaded_pdf")
- **Negative:** A session that expires mid-stream (after 600s) will fail — unlikely in practice since extractions complete in under 60s

---

## ADR-016 — Access Score Re-Anchor (Option A, v2.2) {#adr-016}

> This ADR records the full journey: an initial v2.0 "two-sided / full 0–100" attempt (documented
> below), found flawed by review, then **corrected to Option A** (v2.1 → v2.2). Read the
> **Correction** and **Alternatives Considered** sections at the end for the live model.

**Status:** Accepted **with correction** (supersedes [ADR-006](#adr-006)). The initial **v2.0**
credit-for-absence model documented below was found flawed by a 5-perspective review (`REVIEW.md`,
2026-05-30) and **corrected to Option A** (v2.1) — see "Correction" and "Alternatives Considered"
at the end of this ADR. Implementation tracked in `specs/fix-access-score-review/`.

### Context
The hackathon objective defines Access Quality on a 0–100 scale with explicit anchors: 0 = no
access, 25 = restricted vs FDA, 50 = parity with FDA, **75 = preferred vs FDA**, **100 = best
possible / no restrictions applied**. The original scorer (ADR-006, `SCORER_VERSION = "1.0"`)
started at 50 and could add at most +8 (TB +3, age +5), so its ceiling was ~58 — it could not
represent the 75 or 100 anchors at all (review finding **P0-5**).

P0-5 was first **deferred** after a focused Devil's Advocate review, which correctly noted that
(a) there is **no gold Access Score** in the provided data to calibrate against (the `Submissions`
tab column is empty), and (b) a naïve +50 "credits" block risked diverging from a gold that might
cluster ≤50. The objective text was then re-read: it *explicitly* requires the scale to be capable
of the full 0–100 with 75/100 above parity. The decision was reopened with the constraint to build
it **deterministically** (no LLM — the eval models `llama-3.1-8b-instant` / `llama-3.3-70b` have
tight per-day token budgets that an LLM scorer would strain) and to calibrate against synthetic
anchor fixtures rather than asserting weights.

### Decision
Keep **50 = FDA parity** as the pivot. Add a **credit track** mirroring the deductions, with an
either/or guard so each dimension contributes a deduction *or* a credit, never both:

```
Score = 50
  − restrictions beyond FDA  (brand −10/step cap −30, generic −5/step cap −15,
                              phototherapy −5, specialist −8, reauth −5, QL −5,
                              TB-beyond-FDA −3, age-more −5)        → toward 0
  + absence / better-than-FDA (no steps +10, no phototherapy +3,
                              no specialist +5, no reauth +5, no QL +3,
                              age-less +5, TB-waived +3)            → toward 100
clamped to [0, 100]
```

Calibration is pinned by `test_scoring.py`: an unrestricted policy scores **≥75**, a maximally
restrictive one **≤10**, and a moderately-managed "parity" policy **≈50**. `SCORER_VERSION` is
bumped to `"2.0"` and `score_breakdown` now carries `{deductions, credits}`.

### Rationale
- Satisfies the literal objective (full 0–100, anchored 0/25/50/75/100) while keeping typical
  step-therapy policies below parity.
- Deterministic → reproducible (re-run `rescore.py`), free, and adds nothing to the eval models'
  rate-limit budgets (unlike a GenAI/hybrid scorer).
- For these PsO brands the FDA baseline already lacks step therapy / QL / specialist / reauth, so
  "FDA parity" and "no restrictions" are close; the model is therefore an *absolute
  restriction-burden* scale anchored at the objective's labels. The competitive sense of 100 ("best
  access against all competitors") is **not** modelled — that signal is not extracted.

### Consequences (of the WITHDRAWN v2.0 model — see Correction below for the live v2.1 result)
- ~~**Positive:** Re-scored distribution spans **10–76** (was 7–50), mean 36.7, median 33; 2 policies
  reach the Preferred band (≥75). The 75/100 region is now reachable.~~ *(This "reachability" was an
  artifact of crediting missing data — withdrawn in v2.1; live distribution is 7–50, 0 Preferred.)*
- **Positive:** Single-source `category`/`fda_alignment` (ADR-style P3-6 fix) carried forward under
  the new cutoffs.
- **Negative:** Without a gold Access Score, the credit weights are calibrated to synthetic anchors,
  not validated against ground truth — accuracy on the score dimension remains unmeasured (the
  validation harness, review finding P1-3, was deferred).
- **Negative:** Scores cannot reach a true 100 (max observed credit path ≈ +34 → ~84), since the
  competitive-positioning axis is not extracted.

### Correction (2026-05-30) — Option A

A 5-perspective review (`REVIEW.md`) found the v2.0 credit-for-absence model defective:
- **P0-1:** it scored missing data (`"NA"`) as "restriction confirmed absent," awarding credit on
  86% of rows; the two policies that reached the Preferred band (76) were the **two rows where
  extraction found nothing** (incl. the `NO BRAND MATCH FOUND` row). The "v2.0 reaches Preferred"
  result was an artifact of extraction failure.
- **P1-1:** crediting the absence of step/QL/specialist/reauth — which the FDA baseline *also* lacks
  — pushed genuine FDA-parity policies to ~76, breaking the "50 = parity" anchor.

**Decision: Option A.** Remove the absence-credits; keep only **strictly better-than-FDA** credits
(age-younger +5, TB-waived +3). This makes 50 = faithful FDA parity, treats `"NA"` as *unknown*
(neither credit nor penalty), and accepts a practical **ceiling of ~58** — for these PsO PA
policies the **75/100 anchors are unreachable**, because a prior-authorization policy only *adds*
restrictions versus the FDA label. `SCORER_VERSION → "2.1"`. (This realigns with the original
ADR-006 observation; the v2.0 attempt to force the full range is abandoned as not honestly
supportable from the extracted data.)

**Refinement (v2.2) — confirmed-only credit.** A follow-up review of v2.1 noted that removing *all*
absence-credits collapsed a real distinction: a policy that *verified* it is open scored identically
to one where nothing was extracted (both ~50). v2.2 adds a **small +2 "confirmed-open" credit** per
axis that fires ONLY on positive evidence of absence (explicit `"No"` / empty list / confirmed 0) —
**never on `"NA"`**. This makes each axis tri-state (present → deduct, confirmed-absent → +2,
unknown → neutral), restoring the verified-open-vs-unextracted distinction while keeping the P0-1
fix intact (missing data still moves nothing). Trade-off recorded: 50 now reads as the
*neutral/unknown* baseline and a fully-confirmed-open policy sits slightly above it (~60), so the
"50 = FDA parity" anchor is interpreted as "at-or-just-above parity," not an exact point. New
ceiling ~68 (confirmed-open +10, age +5, TB +3) — still < 75, so "Preferred" remains unreachable.
`SCORER_VERSION → "2.2"`.

**Re-scored result (v2.2):** range **9–50**, mean 29.7, median 29, **0 rows ≥75**; the two former
all-`"NA"` "Preferred" rows are **50** (unchanged — `"NA"` stays neutral). Category split: 34 Highly
Restricted / 43 Restricted / 2 FDA Parity / 0 Preferred. Credit footprint: 73 confirmed-no-photo
(+2), 2 confirmed-no-reauth (+2), 2 age-younger (+5); 0 credits derived from `"NA"`. Calibration
pinned by `test_scoring.py` (all-`"NA"`≈50, confirmed-open≈60, max≤10, most-permissive≈68, plus
upper-bound-age and reauth-casing guards).

**Re-score scope (regenerate vs re-run):** `rescore.py` recomputes `access_quality` from the
**stored** extraction values only — no LLM, no PDF re-parse — so it reflects scoring-logic changes
but **not** extractor fixes (TB/Auth/age semantics), which stay frozen in the JSON until a full
pipeline re-run. `rescore.py` reports the input `scorer_version` counts before overwriting, so
version drift is visible.

### Alternatives Considered (reaching the upper 75/100 range)

The upper anchors cannot be reached on a "restrictions vs FDA" axis; doing so requires changing what
the upper half measures. Options weighed (2026-05-30):

| Option | Reaches 0–100? | Deterministic? | LLM re-run? | 50 = FDA parity? |
|--------|----------------|----------------|-------------|------------------|
| **A — vs-FDA, better-than-FDA credits only (CHOSEN)** | No (~0–58) | Yes | No | Yes (faithful) |
| B — cohort-relative normalization | Yes (by construction) | Yes | No | No (50 = median) |
| C — generosity signals (auth duration / age / TB) | Partial (~0–75) | Yes | No | ~ mostly |
| D — competitive/formulary positioning extraction | Yes (faithful, true 100) | Yes (scoring) | **Yes** (new extractor) | Yes |
| E — GenAI holistic scoring | Yes | No | Yes (per-row) | n/a |

**Why A:** there is **no gold Access Score** to validate against, so any upper-range approach is a
bet; if the gold scored vs-FDA (PA policies ≤50), reaching 75/100 would *increase* error. A is the
faithful, deterministic, lowest-risk choice. B/C/D/E are recorded here as future work should a gold
sample or competitive-positioning signal become available.

---

## Summary Table

| ADR | Decision | Key Trade-off |
|-----|----------|---------------|
| 001 | Page-level PDF extraction | Granular retrieval vs page-boundary splits |
| 002 | Strict + proximity union | Maximum recall vs slight extra noise |
| 003 | Tight sort signals + 15-page cap | Relevant pages first vs very long criteria sections |
| 004 | Abstracted model router (auto-detect from env) | Zero-change backend swap vs lowest-common-denominator prompts |
| 005 | Rolling-window throttlers (singleton + locked) | Max throughput + thread safety vs single serialization point |
| 006 | FDA parity baseline (score=50) | Objective baseline vs no partial credit for alternatives |
| 007 | Incremental checkpoint saves | Crash resilience vs manual stale-entry cleanup |
| 008 | Slot model for step counting | Correct counts vs LLM cascade boundary errors |
| 009 | Brand-aware renewal sweep | Correct renewal retrieval vs wider ±8 window noise |
| 010 | 20K char context limit | Groq TPM safety vs very dense criteria sections |
| 011 | Sentinels mapped to "NA" in output | Valid graded cells vs losing non-result detail in CSV |
| 012 | Extraction error flag + checkpoint skip | Auto-retry on re-run vs infinite retry on persistent failures |
| 013 | Scorer version stamp | Retroactive re-score vs manual rescore.py invocation |
| 014 | TB No/NA and Auth Unspecified semantics | Precise output states vs stored data unchanged until re-extract |
| 015 | Session TTL + thread-safe UI state | No leaked resources vs expired mid-stream edge case |
| 016 | vs-FDA score, ceiling ~68 (Option A; supersedes 006) | Faithful 50-anchor + confirmed-open signal vs 75/100 unreachable for this dataset |
