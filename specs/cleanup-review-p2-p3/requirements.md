# Requirements — Review Cleanup (all P3 + P2-7, P2-8, P2-11)

## Introduction

This spec collects the lower-severity hygiene and robustness findings from `REVIEW.md` that the
team has chosen to action now: **all P3 items** plus **P2-7, P2-8, P2-11**. These are small,
mostly-independent fixes — no behavior-critical pipeline changes — so they are grouped into one
spec with one task each.

State was verified against the current (post-merge) tree before writing:

- **P3-4 (result_formatter side effects at import)** is **already resolved** — `result_formatter.py`
  now guards its I/O under `main()` / `if __name__ == "__main__"` (done by the P0-1 work). No task.
- **P3-3** is **mostly resolved** — no `extract(pdf_path=...)` calls remain; the five `__main__`
  harnesses still exist, so this is reduced to a verify-only task.
- **P3-6** overlaps the `specs/access-score-reanchor/` spec (both touch category cutoffs and
  `fda_alignment`). If that spec is being implemented, fold P3-6 into its task-1.1; otherwise do it
  standalone here.

### In scope
P3-1, P3-2, P3-3 (verify), P3-5, P3-6, P3-7, P2-7, P2-8, P2-11.

### Out of scope
P2-1..P2-6, P2-9, P2-10, P2-12, P2-13; all P0/P1 (separate specs); the access-score re-anchor
(`specs/access-score-reanchor/`); extraction-side rate-limit handling.

---

## Requirement 1: No leftover debug output; docstrings are real docstrings

**User story:** As a maintainer, I want production code paths free of ad-hoc debug prints and with
correct docstrings, so logs are clean and introspection works.

**Acceptance criteria:**

1. THE SYSTEM SHALL NOT emit the ad-hoc debug `print()` statements in `step_therapy_extractor.py` ("extracting approval section was used", "main extraction was used", "extracting step therapy requirements with llm was used"). [P3-1]
2. WHEN `extract_approval_section.__doc__` is accessed THE SYSTEM SHALL return the method's documentation string (i.e., the triple-quoted block is the first statement, not preceded by a `print`). [P3-2]

## Requirement 2: Module self-tests use the current extract() signature

**User story:** As a maintainer, I want each extractor's `__main__` self-test to run against the
current API, so the harnesses are not stale.

**Acceptance criteria:**

1. THE SYSTEM SHALL ensure every extractor `__main__` block invokes `extract(...)` with the current `(pages, brand, pdf_name)` signature (not the removed `pdf_path=` form). [P3-3]
2. IF a self-test cannot be made to run meaningfully THEN THE SYSTEM SHALL remove it rather than leave it broken.

## Requirement 3: Build/data artifacts are not version-controlled

**User story:** As a maintainer, I want generated and bulky data files untracked, so the repo holds
source, not artifacts.

**Acceptance criteria:**

1. THE SYSTEM SHALL untrack files that match `.gitignore` but were committed earlier: `INSTALL_REQUIREMENTS.exe`, `PA_Business_Rules.xlsx`, `debug/*.txt`, and `outputs/*`. [P3-5]
2. THE SYSTEM SHALL add ignore rules for `.venv/`, `.DS_Store`, `*.exe`, and `*.docx`.
3. THE SYSTEM SHALL keep the working-tree copies of those files (untrack only, not delete) so local runs still work.

## Requirement 4: One consistent access classification

**User story:** As a consumer of the score, I want `access_category` and `fda_alignment` to be
mutually consistent, so a row cannot be labelled in two contradictory ways.

**Acceptance criteria:**

1. THE SYSTEM SHALL derive `fda_alignment` and `access_category` from a single source (the score / one threshold scheme) so they cannot disagree. [P3-6]
2. IF the `specs/access-score-reanchor/` spec is implemented THEN this requirement SHALL be satisfied within that spec's scorer rework instead of duplicated here.

## Requirement 5: No dead code in text cleaning

**User story:** As a maintainer, I want `clean_text` free of unreachable substitutions, so the
function is honest about what it does.

**Acceptance criteria:**

1. THE SYSTEM SHALL remove (or reorder) the `\n{3,}` collapse in `document_processor.clean_text`, which is unreachable because an earlier `\n\s*\n+ → \n` substitution already removed all runs of 3+ newlines. [P3-7]
2. THE SYSTEM SHALL preserve the observable cleaning behavior (output unchanged for representative inputs).

## Requirement 6: Robust JSON extraction from LLM output

**User story:** As a maintainer, I want `clean_json_output` to reliably extract the intended JSON
object, so an LLM response with trailing prose or braces does not corrupt parsing.

**Acceptance criteria:**

1. WHEN the LLM output contains a JSON object followed by prose THE SYSTEM SHALL extract the first complete, balanced JSON object rather than greedily spanning to the last `}`. [P2-7]
2. THE SYSTEM SHALL continue to strip ```` ```json ```` / ```` ``` ```` fences.
3. WHEN extraction fails THE SYSTEM SHALL return a value that fails JSON parsing cleanly (so the caller's existing error handling fires), not a partially-captured string.

## Requirement 7: Robust minimum-age parsing

**User story:** As a maintainer, I want `_parse_min_age` to handle real-world age strings, so age
scoring is correct and does not silently drop values.

**Acceptance criteria:**

1. WHEN given a string with extra text (e.g., "6 years", ">=6 years") THE SYSTEM SHALL extract the numeric threshold rather than returning `None`. [P2-8]
2. THE SYSTEM SHALL distinguish `>` from `>=` when comparing payer vs FDA age (no off-by-one conflation), or document the chosen convention.
3. WHEN no numeric age is present (e.g., "NA", "FDA labelled age", "No Age Restriction") THE SYSTEM SHALL return `None` (no scoring effect).

## Requirement 8: PDF file handles are released

**User story:** As an operator running the 79-PDF batch, I want PyMuPDF documents closed, so native
file handles / memory are not leaked across the run.

**Acceptance criteria:**

1. WHEN `process_pdf` finishes (normally or via exception) THE SYSTEM SHALL close the `fitz` document. [P2-11]
2. THE SYSTEM SHALL preserve the returned `[{page_number, text}]` structure unchanged.
