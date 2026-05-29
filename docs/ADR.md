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

**Status:** Accepted

### Context
The pipeline needs to support multiple LLM backends: Gemini (cloud, fast, rate-limited), Groq/llama-3.3-70b (cloud, for final presentation), and Ollama (local, unlimited, slower). No single model is optimal for all situations.

### Decision
`ModelRouter` in `utils/model_router.py` selects the active backend at runtime via environment variables. All extractors call `model_router.generate(prompt, context)` — they are completely unaware of which model is in use.

Switching backends requires only changing the `.env` file:
```
MODEL_PROVIDER=gemini   # or groq, ollama
```

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

## ADR-005 — Gemini RPM Throttler {#adr-005}

**Status:** Accepted

### Context
Gemini Flash Lite free tier: 15 RPM, 500 RPD. At 79 PDFs × 5 LLM calls = ~395 calls total. Hardcoded `time.sleep(20)` between calls was used initially but wasted time when requests were well under the rate limit.

### Decision
Replace all hardcoded sleeps with a rolling-window RPM throttler in `ModelRouter._gemini_throttle()`. A `deque` tracks timestamps of the last N requests. Before each Gemini call:
1. Evict timestamps older than 60 seconds
2. If `len(window) < 12` (80% of 15 RPM limit) → proceed immediately
3. Otherwise sleep until the oldest timestamp expires + 0.5s buffer

### Rationale
- 80% of 15 RPM = 12 RPM target avoids hitting the hard limit
- Rolling window is more accurate than a fixed-interval sleep
- No sleep wasted when requests naturally stay under the limit

### Consequences
- **Positive:** Maximum throughput within rate limits; no unnecessary sleeping
- **Positive:** Self-correcting — burst of fast extractions auto-throttles; slow extractions don't sleep at all
- **Negative:** Shared state across extractor calls means the throttler is only meaningful when `ModelRouter` is a singleton (it is — one instance per pipeline run)

---

## ADR-006 — FDA Parity Baseline Scoring {#adr-006}

**Status:** Accepted

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

## Summary Table

| ADR | Decision | Key Trade-off |
|-----|----------|---------------|
| 001 | Page-level PDF extraction | Granular retrieval vs page-boundary splits |
| 002 | Strict + proximity union | Maximum recall vs slight extra noise |
| 003 | Tight sort signals + 15-page cap | Relevant pages first vs very long criteria sections |
| 004 | Abstracted model router | Zero-change backend swap vs lowest-common-denominator prompts |
| 005 | Rolling RPM throttler | Max throughput vs shared throttler state |
| 006 | FDA parity baseline (score=50) | Objective baseline vs no partial credit for alternatives |
| 007 | Incremental checkpoint saves | Crash resilience vs manual stale-entry cleanup |
| 008 | Slot model for step counting | Correct counts vs LLM cascade boundary errors |
| 009 | Brand-aware renewal sweep | Correct renewal retrieval vs wider ±8 window noise |
| 010 | 20K char context limit | Groq TPM safety vs very dense criteria sections |
| 011 | Sentinels mapped to "NA" in output | Valid graded cells vs losing non-result detail in CSV |
