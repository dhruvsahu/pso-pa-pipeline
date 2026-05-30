# Tasks — Fix Review Findings (P3 subset, excluding P3-4)

Six P3 issues selected for implementation. P3-4 (`result_formatter.py` import-time I/O) was
already fixed as part of task-1.1.

---

### task-7.1 — P3-1: Remove leftover debug prints from step_therapy_extractor

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `extractors/step_therapy_extractor.py`
- **What's wrong:** Three `print()` calls in the hot path emit debug noise on every extraction:
  - Line 283: `print("extracting approval section was used")`
  - Line 403: `print("main extraction was used")`
  - Line 604: `print("extracting step therapy requirements with llm was used")`
  These were development breadcrumbs that were never removed.
- **Fix:** Delete all three `print()` lines. Do NOT replace with `logging.debug` — these are
  function-entry traces with no diagnostic value beyond confirming the function was called, which
  is already obvious from the `[LLM]` and `[GROQ TOKENS]` prints in the model router.
- **Outcome:** No spurious console output from step therapy extraction.
- **Verification:** `grep -n "was used" extractors/step_therapy_extractor.py` returns no matches.
  `py_compile` OK.

---

### task-7.2 — P3-2: Fix misplaced `print()` before docstring

- **BlockedBy:** task-7.1 (same file region — avoid merge conflicts)
- **Agent:** general-purpose
- **File:** `extractors/step_therapy_extractor.py`
- **What's wrong:** `extract_approval_section` has a `print(...)` statement BEFORE the
  triple-quoted string that was intended to be the docstring:
  ```python
  def extract_approval_section(self, pages):
      print("extracting approval section was used")   # <-- this makes the next line a no-op
      """                                              # <-- dead string expression, not a docstring
      Extract ONLY the approval criteria section ...
      """
  ```
  Because the `print()` comes first, the triple-quoted string is just a dead expression (not
  bound to `__doc__`). Since task-7.1 removes the `print()`, the docstring naturally becomes
  the real docstring.
- **Fix:** After task-7.1 removes the `print()`, verify that the triple-quoted string is now the
  first statement in the method body (making it the docstring). No additional code change needed
  if task-7.1 simply deletes the `print()` line.
- **Outcome:** `extract_approval_section.__doc__` is populated correctly.
- **Verification:** `python -c "from extractors.step_therapy_extractor import StepTherapyExtractor; print(StepTherapyExtractor.extract_approval_section.__doc__[:50])"` prints the docstring.

---

### task-7.3 — P3-3: Fix stale `__main__` harnesses to use correct `extract()` signature

- **BlockedBy:** none
- **Agent:** general-purpose
- **Files:** `extractors/age_extractor.py`, `extractors/authorization_extractor.py`,
  `extractors/clinical_access_extractor.py`, `extractors/utilization_management_extractor.py`
- **What's wrong:** Four extractors' `__main__` blocks call `extract(pdf_path=..., brand=...)`
  but the actual signature is `extract(pages, brand, pdf_name="")`. Running any of these files
  directly raises `TypeError` immediately. (`step_therapy_extractor.py` is correct — it already
  calls `extract(pages=pages, brand=brand)`.)
- **Fix:** For each of the four extractors, update the `__main__` block to:
  1. Import `DocumentProcessor` from `utils.document_processor`
  2. Call `document_processor.process_pdf(pdf_path)` to get pages
  3. Call `extractor.extract(pages=pages, brand=brand, pdf_name=pdf_path)`
  Follow the pattern already used by `step_therapy_extractor.py`'s working `__main__`.
- **Outcome:** All 5 extractors can be run standalone for debugging (`python -m extractors.age_extractor`).
- **Verification:** `python -c "import ast; ast.parse(open(f).read())"` for each file (syntax OK).
  Optionally run one extractor end-to-end on a sample PDF if API keys are available.

---

### task-7.4 — P3-5: Add dev/data artifacts to `.gitignore`

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `.gitignore`
- **What's wrong:** Several dev and data artifacts are tracked by git:
  - `INSTALL_REQUIREMENTS.exe` — a misleadingly-named shell command wrapper
  - `debug/*.txt` — extractor debug context dumps (16 files tracked)
  - `outputs/*` — generated results (6 files tracked: JSON, CSV, XLSX)
  Note: `.gitignore` already has entries for `outputs/`, `outputs/*.json`, `debug/*.txt`,
  and `PA_Business_Rules*.xlsx`, but the files were force-committed before these rules existed,
  so git still tracks them. The `.gitignore` rules are correct; the issue is the tracked files.
- **Fix:** The `.gitignore` patterns are already in place. The only missing pattern is
  `INSTALL_REQUIREMENTS.exe`. Add it. The tracked files themselves should be removed from
  tracking via `git rm --cached` (keeps the local files, removes from git index) — but this
  is a git operation, not a code change, and should be done as a separate deliberate commit
  to avoid accidentally breaking anything for teammates who have these files.
- **Scope note:** Only add the missing `.gitignore` entry. Do NOT `git rm --cached` the tracked
  files — that's a repo-hygiene commit the user should decide to make separately.
- **Outcome:** Future `INSTALL_REQUIREMENTS.exe` changes won't show in `git status`.
- **Verification:** `grep INSTALL .gitignore` returns the new entry.

---

### task-7.5 — P3-6: Derive `fda_alignment` from `access_category` to eliminate disagreement

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **What's wrong:** Two classification schemes exist for the same score:
  - `access_category`: score-based buckets (< 25 Highly Restricted, < 50 Restricted, < 75 FDA
    Parity, >= 75 Preferred)
  - `fda_alignment`: uses a mix of `total_steps >= 3 or score < 40` and `score > 55` thresholds
    plus a "no deductions" check
  These can disagree: a score of 42 with 3 step-therapy steps gets `access_category = "Restricted
  Access"` but `fda_alignment = "More restrictive than FDA label"`, while a score of 42 with 1
  step gets `fda_alignment = "Near FDA parity"`. The step-count check in `fda_alignment` adds a
  confounding dimension that `access_category` doesn't use.
- **Fix:** Derive `fda_alignment` directly from `access_category`:
  - "Highly Restricted" / "Restricted Access" -> "More restrictive than FDA label"
  - "FDA Parity" -> "Near FDA parity"
  - "Preferred Access" -> "Favorable relative to FDA label"
  This eliminates the step-count side-channel and guarantees the two fields always agree.
- **Outcome:** No disagreement between the two classification fields; simpler, auditable logic.
- **Verification:** Run the scorer's `__main__` test cases and confirm both fields are consistent.
  `py_compile` OK.

---

### task-7.6 — P3-7: Remove dead regex in `clean_text`

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/document_processor.py`
- **What's wrong:** The `clean_text` method has two newline-collapsing passes:
  1. `re.sub(r'\n\s*\n+', '\n', text)` — collapses any run of blank lines (including
     lines with only whitespace) into a single `\n`
  2. `re.sub(r'\n{3,}', '\n\n', text)` — collapses 3+ consecutive newlines into 2
  Pass 1 already eliminates all runs of 2+ newlines (they become `\n`), so pass 2's
  `\n{3,}` pattern can never match — it's dead code.
- **Fix:** Delete the pass-2 block (the `# LIMIT NEWLINES` comment and the `re.sub` call).
- **Outcome:** Cleaner code; no functional change (dead code removed).
- **Verification:** `py_compile` OK. Process a sample PDF and confirm output is identical
  (since the regex could never match, output is guaranteed unchanged).

---

## Dependency diagram

```
task-7.1 (P3-1) ──► task-7.2 (P3-2)    [same file region]

task-7.3 (P3-3)   [independent]
task-7.4 (P3-5)   [independent]
task-7.5 (P3-6)   [independent]
task-7.6 (P3-7)   [independent]
```

## Execution summary

- **Active tasks: 6**
- **Stage 1 (parallel-safe):** task-7.1, task-7.3, task-7.4, task-7.5, task-7.6
- **Stage 2:** task-7.2 (depends on task-7.1 — same file region)
- **Total stages:** 2
- **Critical path:** task-7.1 -> task-7.2 (2 stages)

> Numbering continues from the P2 task file (last was task-6.3) to avoid ID collisions.
> P3-4 is excluded — already fixed as part of task-1.1 (import-time I/O guarded under
> `if __name__ == "__main__"`).
