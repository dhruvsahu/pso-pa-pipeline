# Pipeline Flow
## PsO Prior Authorization Access Quality Pipeline

---

## Overview

```
BATCH PATH                                    UI PATH
──────────                                    ───────
sample_batch.csv                              app.py (Flask, localhost:5000)
      │                                            │
      ▼                                            ▼
run_full_pipeline.py                          pipeline_runner.py (SSE)
      │                                            │
      ├── checkpoint ── outputs/                   │
      │                 final_access_results.json   │
      │                                            │
      ▼                                            ▼
DocumentProcessor  (PDF → Pages, PyMuPDF)     DocumentProcessor
      │                                            │
      ▼                                            ▼
  5 Extractors  ◄── get_router() ──►  ModelRouter (singleton)
  ┌─────────────────────────────────┐    (Gemini / Groq / Ollama)
  │ AgeExtractor                    │    Thread-safe throttlers
  │ StepTherapyExtractor            │
  │ AuthorizationExtractor          │
  │ UtilizationManagementExtractor  │
  │ ClinicalAccessExtractor         │
  └─────────────────────────────────┘
      │                                            │
      ▼                                            ▼
  AccessQualityScorer (v2.2)                  append to outputs/results.csv
      │                                       (Download Results button)
      ▼
  result_formatter.py ── final_access_results.csv / .xlsx
  rescore.py ── re-score from stored JSON (no LLM)
```

---

## Step 1 — Input: `assets/sample_batch.csv`

The pipeline is driven by a CSV file with two columns:

```
filename,brand
378692-5003182.pdf,STELARA
66156-4274314.pdf,CIMZIA
...
```

- **79 rows** sourced from PA_Business_Rules.xlsx (Submissions sheet)
- Each row = one PDF + one target brand to extract
- Some PDFs appear multiple times with different brands (dual-brand policies e.g. STELARA + TREMFYA in the same document)

---

## Step 2 — Orchestrator: `run_full_pipeline.py`

Entry point for the full batch run (`python run_full_pipeline.py`).

**On startup:**
1. Reads `sample_batch.csv`
2. Loads `outputs/final_access_results.json` if it exists
3. Builds `completed_keys = {(filename, brand)}` from existing results
4. Skips already-completed rows — only processes the remainder

**For each remaining `(pdf, brand)` pair:**
1. Verifies the PDF file exists in `Sample_PsO_ADS_Track/`
2. Runs `DocumentProcessor` → pages
3. Runs all 5 extractors sequentially
4. Runs `AccessQualityScorer` (stamps `scorer_version` per row)
5. Combines all results into one dict
6. Checks for `extraction_error` in any sub-result — if found, **skips checkpointing** (row retries on next run)
7. Otherwise **appends to JSON and saves to disk immediately** (checkpoint after every drug)

This means a crash or rate-limit error loses at most one drug's worth of work, and extractor failures auto-retry.

---

## Step 3 — PDF Parsing: `DocumentProcessor`

```python
pages = processor.process_pdf(pdf_path)
# Returns: [{"page_number": 1, "text": "..."}, ...]
```

- Reads the PDF using PyMuPDF (`fitz`) with a context manager to prevent file handle leaks
- Returns one dict per page with `page_number` and extracted `text`
- Page-level granularity is essential — all extractor retrieval logic operates on individual pages

---

## Step 4 — Five Extractors

Each extractor receives the full `pages` list and the `brand` string. They all follow the same internal pattern:

### Internal Pattern (all 5 extractors)

```
pages + brand
     │
     ├── Pass 1: STRICT
     │   Pages where brand name AND keyword both appear
     │
     ├── Pass 2: PROXIMITY
     │   Pages with keywords within ±N pages of any brand-mention page
     │
     ├── UNION + DEDUP by page number
     │
     ├── sort_by_relevance()
     │   Rank by tight signal keyword hits → keep top 15 pages
     │
     ├── Truncate to 20,000 chars
     │
     └── LLM call → JSON response
```

**Proximity windows:**
- Age, Step Therapy, Utilization, Clinical Access: ±2 pages
- Authorization: ±4 pages (wider — renewal sections often appear several pages after initial criteria)

**Authorization also has a third pass:**
- After strict + proximity union, checks if any page has **both** the brand name AND a renewal keyword
- If not, runs a ±8 renewal sweep — prevents collecting renewal pages from adjacent drugs in large formularies

### `AgeExtractor`
- **Finds:** Minimum patient age for the target brand
- **Keywords:** `"minimum age"`, `"years of age"`, `"pediatric"`, `"adult"`, etc.
- **Output:** `{"value": ">=6", "source_statement": "...", "confidence": 0.9}`
- **Normalization:** `"adult patients"` → `">=18"`, `"6 years of age or older"` → `">=6"`

### `StepTherapyExtractor`
- **Finds:** Prior therapy requirements before the brand can be approved
- **Keywords:** `"step therapy"`, `"failure of"`, `"inadequate response"`, `"tried and failed"`, etc.
- **Output:** `{"brand_step_slots": [...], "generic_step_slots": [...], "phototherapy_required": "Yes/No/NA"}`
- **Step count** is computed deterministically from slot count (`len(slots)`) — not by the LLM
- Uses the **slot model**: OR alternatives go inside one slot's `alternatives` list; AND steps each get their own slot. Intolerance cascades (`"if intolerant to A → try B"`) are ONE slot with A and B as alternatives, not two steps.

### `AuthorizationExtractor`
- **Finds:** How long the initial authorization lasts, whether reauthorization is required, and its criteria
- **Keywords:** `"prior authorization"`, `"renewal"`, `"reauthorization"`, `"continued therapy"`, etc.
- **Output:** `{"initial_authorization_months": 12, "reauthorization_required": "Yes", "reauthorization_duration_months": 12, "reauthorization_requirements": [...]}`
- **Semantics:** When an authorization section exists but no month count is stated, `initial_authorization_months` is coerced to `"Unspecified"` (not `"NA"` — that is reserved for "no authorization section found")

### `UtilizationManagementExtractor`
- **Finds:** Quantity limits on the target brand
- **Keywords:** `"quantity limit"`, `"QL"`, `"max units"`, `"days supply"`, etc.
- **Output:** `{"quantity_limits": ["1 vial per 8 weeks"] or "No" or "NA"}`

### `ClinicalAccessExtractor`
- **Finds:** TB test requirements, specialist restrictions, precertification requirements
- **Keywords:** `"tuberculosis"`, `"latent tb"`, `"dermatologist"`, `"prescriber specialties"`, etc.
- **Output:** `{"tb_test_required": "Yes/No/NA", "specialist_types": ["dermatologist"] or "NA", "precertification_required": "Yes/No/NA"}`
- **TB semantics:** When criteria are found but TB is not mentioned, the answer is `"No"` (not required), not `"NA"`. `"NA"` is returned only when no clinical access context is found at all.

**Error handling:** All five extractors catch exceptions and return a fallback dict with `"extraction_error": True`. The batch runner checks for this flag and **skips checkpointing** errored rows so they are retried on the next run.

---

## Step 5 — Model Router: `ModelRouter`

All extractors obtain the shared router via `get_router()` (process-wide singleton, double-checked lock) and call `model_router.generate(prompt, context)` — they are unaware of which LLM is active.

```
get_router()  →  shared ModelRouter instance (singleton)
     │
     model_router.generate(prompt, context)
          │
          ├── [if Groq]   _groq_throttle(estimated_tokens)
          │     Rolling 60s deque of (timestamp, tokens, uid).
          │     Sleep if adding tokens would exceed 90% of 12K TPM.
          │     Returns uid → _groq_record_actual(uid, actual) after call.
          │
          ├── [if Gemini]  _gemini_throttle()
          │     Rolling 60s deque of request timestamps.
          │     Sleep only if ≥12 requests in last 60s (80% of 15 RPM).
          │
          └── generate() → raw LLM text response
```

All throttle read-modify-write is guarded by `self._throttle_lock`; the lock is released before sleeping so other threads can make progress.

**Backend auto-selection** via `.env` (priority order):
- `GROQ_API_KEY` present → Groq (llama-3.3-70b, presentation)
- `GEMINI_API_KEY` present → Gemini (gemini-3.1-flash-lite, development)
- Neither → Ollama (local / offline fallback)

**Token budget per call (approximate):**
- Prompt template: ~7K chars (~1.75K tokens)
- Context: up to 20K chars (~5K tokens)
- Total per call: ~6.75K tokens
- 5 calls per PDF: ~34K tokens/PDF
- Groq limit: 12K TPM → throttler spaces calls to stay within budget

---

## Step 6 — Relevance Sorting: `sort_by_relevance()`

Called inside every extractor after the strict + proximity union:

```python
def sort_by_relevance(collected_pages, signal_keywords, max_pages=15):
    # Score each page by number of tight signal keyword hits
    # Sort descending → keep top 15 → discard rest
```

Each extractor has its own tight `*_sort_signals` list — terms that appear specifically on criteria pages (e.g. `"initial authorization"`, `"approval criteria"`, `"plaque psoriasis"`) rather than background/clinical-trial pages.

Without this, large multi-drug formularies (60–87 pages retrieved) would bury the relevant criteria page outside the 20K truncation window.

---

## Step 7 — Scoring: `AccessQualityScorer`

Compares all extractor outputs against `assets/fda_baselines.csv` (FDA prescribing label per brand).

**Baseline: 50 = FDA parity**

| Factor | Deduction | Bonus |
|--------|-----------|-------|
| Brand step therapy | −10/step (cap −30) | — |
| Generic step therapy | −5/step (cap −15) | — |
| Phototherapy mandatory standalone step | −5 | — |
| Specialist restriction (not in FDA label) | −8 | — |
| Reauthorization required | −5 | — |
| Quantity limits imposed | −5 | — |
| TB test required (FDA says not needed) | −3 | +3 if waived |
| Age more restrictive than FDA label | −5 | +5 if less restrictive |

Score is clamped to [0, 100].

**Access categories:**
- `[75,100]`: Preferred Access *(not reachable for this dataset — ceiling ~68; see ADR-016)*
- `[50,75)`: FDA Parity
- `[25,50)`: Restricted Access
- `[0,25)`: Highly Restricted

A small **+2 confirmed-open credit** is added per axis the policy *verifies* is unrestricted
(explicit "No" / empty list / confirmed 0) — never on "NA" — so 50 is the neutral/unknown baseline
and a verified-open policy sits slightly above it.

**Observed range across 79 policies (scorer v2.2): 9–50, average 29.7, median 29** — consistent with real-world PA policies universally adding restrictions beyond FDA label. No policy scores above 50; the 75/100 anchors are not reachable from the extracted parameters (Option A — see ADR-016). Reproducible via `python rescore.py` + `python result_formatter.py`.

---

## Step 8 — Output: `outputs/final_access_results.json`

After each drug is processed, the full combined result is saved:

```json
{
  "brand": "STELARA",
  "filename": "378692-5003182.pdf",
  "age": { "value": ">=6", ... },
  "step_therapy": { "brand_steps": 1, "generic_steps": 1, ... },
  "authorization": { "initial_authorization_months": 12, ... },
  "utilization_management": { "quantity_limits": ["..."], ... },
  "clinical_access": { "tb_test_required": "Yes", ... },
  "access_quality": { "access_quality_score": 22, "access_category": "Restricted Access", ... }
}
```

---

## Step 9 — Formatter: `result_formatter.py`

Run manually after the pipeline completes:

```bash
python result_formatter.py
```

Flattens the nested JSON into a flat table. Saves two files:
- `outputs/final_access_results.csv`
- `outputs/final_access_results.xlsx`

**Output columns** (single source of truth: `SUBMISSION_COLUMNS` in `result_formatter.py`):
```
Filename | Brand | Age | Step Therapy Requirements Documented in Policy
Number of Steps through Brands | Number of Steps through Generic
Step through-Phototherapy | TB Test required | Quantity Limits | Specialist Types
Initial Authorization Duration(in-months) | Reauthorization Duration(in-months)
Reauthorization Required | Reauthorization Requirements Documented in Policy
Access Score
```

Note: `Quantity Limits` appears before `Specialist Types` (matches the grading template). The column schema is defined once in `result_formatter.py` and imported by `app.py` so UI and batch output cannot drift apart.

---

## Debug Files

Every extractor writes a debug context file before the LLM call:

```
debug/debug_{extractor}_{brand}_{pdf_stem}.txt
e.g. debug/debug_step_therapy_STELARA_378692-5003182.txt
```

These show exactly which pages were retrieved and in what order — essential for diagnosing retrieval failures.

---

## Interactive UI Path

The Flask UI (`python app.py` → http://localhost:5000) provides a single-PDF analysis mode:

```
Upload PDF + select brand
     │
     ▼
pipeline_runner.py (SSE generator)
     │  streams results step-by-step
     ▼
app.py appends row to outputs/results.csv
     │
     ▼
Download Results button → serves outputs/results.csv
```

- Each analysis appends one row to `outputs/results.csv` using the same `SUBMISSION_COLUMNS` schema as the batch output
- Sessions are stored as `(path, created_at, original_name)` tuples guarded by `threading.Lock` with a 600s TTL
- Temp PDF files are cleaned up after streaming completes or when the session expires
- The original PDF filename is preserved in the CSV (not "uploaded_pdf")

---

## Running the Pipeline

```bash
# Interactive UI (single PDF at a time)
python app.py
# Then open http://localhost:5000 — results accumulate in outputs/results.csv

# Full batch run (resumes from checkpoint automatically)
python run_full_pipeline.py

# Format batch results to CSV/Excel after pipeline completes
python result_formatter.py

# Re-score all rows with the current scorer (no LLM calls)
python rescore.py
```
