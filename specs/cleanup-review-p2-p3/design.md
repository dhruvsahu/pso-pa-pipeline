# Design — Review Cleanup (all P3 + P2-7, P2-8, P2-11)

## Overview

Nine small, mostly-independent fixes across six files. Each is a localized change with no impact on
the extraction algorithm or the output contract. Verification is per-fix (unit-level or grep), plus
a final `py_compile` of touched files. Only P3-5 changes git tracking.

| Finding | File(s) | Nature |
|---|---|---|
| P3-1 | `extractors/step_therapy_extractor.py` | delete 3 debug prints |
| P3-2 | `extractors/step_therapy_extractor.py` | make the triple-quoted block a real docstring |
| P3-3 | `extractors/*.py` (`__main__`) | verify/repair self-test calls |
| P3-5 | `.gitignore`, git index | untrack artifacts + add ignores |
| P3-6 | `access_quality_scorer.py` | single-source category/alignment |
| P3-7 | `utils/document_processor.py` | remove dead regex |
| P2-7 | `utils/extractor_utils.py` | balanced JSON extraction |
| P2-8 | `access_quality_scorer.py` | robust age parse |
| P2-11 | `utils/document_processor.py` | close fitz doc |

## Fix details

### P3-1 / P3-2 — debug prints + docstring (`step_therapy_extractor.py`)
Remove the three `print("... was used")` lines (≈ lines 283, 403, 604). The one at ~283 sits *before*
the `extract_approval_section` triple-quoted string; once removed, that string becomes the function's
first statement and thus its real docstring (satisfies P3-2). If any of these are genuinely useful,
convert to `logging.debug(...)` instead of deleting — but default is delete.

### P3-3 — `__main__` self-tests (`extractors/*.py`)
All five extractors still have `__main__` blocks. The broken `extract(pdf_path=...)` form is already
gone (grep clean). Confirm each block calls `extract(pages=..., brand=..., pdf_name=...)` via the
`DocumentProcessor`; fix any that don't, or delete a block that no longer serves a purpose. Likely a
no-op verify.

### P3-5 — untrack artifacts (`.gitignore` + index)
`.gitignore` already lists `outputs/`, `PA_Business_Rules*.xlsx`, `debug/*.txt`, but these were
committed earlier so they remain tracked. Steps:
- `git rm --cached` (keep working copy) for: `INSTALL_REQUIREMENTS.exe`, `PA_Business_Rules.xlsx`,
  `debug/*.txt`, `outputs/*`.
- Append to `.gitignore`: `.venv/`, `.DS_Store`, `*.exe`, `*.docx`.
- Note: this only takes effect on the next commit; the working tree is unchanged. (Committing is a
  separate, user-initiated step.)

### P3-6 — single-source classification (`access_quality_scorer.py`)
Today `access_category` (score thresholds) and `fda_alignment` (a mix of step-count and score
thresholds) are computed independently and can disagree (e.g., score 52 → "FDA Parity" while
alignment says "Favorable"). Derive `fda_alignment` from the same score bands as `access_category`
(e.g., `<50` → "More restrictive than FDA label", `50–<75` → "Near FDA parity", `>=75` → "Favorable
relative to FDA label"), removing the independent step-count branch.
> **Coordination:** `specs/access-score-reanchor/` task-1.1 also rewrites the category cutoffs. If
> that spec is in flight, implement P3-6 there (single source under the new bands) and mark this
> task done-by-reference to avoid a merge conflict.

### P3-7 — dead regex (`document_processor.clean_text`)
`clean_text` runs `\n\s*\n+ → \n` first (collapses every run of blank lines to a single `\n`), so the
later `\n{3,} → \n\n` can never match. Remove the dead `\n{3,}` substitution. Verify output is
identical on representative inputs (multi-blank-line text).

### P2-7 — balanced JSON extraction (`extractor_utils.clean_json_output`)
Replace the greedy `re.search(r"\{.*\}", text, re.DOTALL)` (spans first `{` to **last** `}`) with a
balanced-brace scan or `json.JSONDecoder().raw_decode` from the first `{`:
- Strip code fences (unchanged).
- Find the first `{`, then either `raw_decode` from there, or walk the string tracking brace depth
  (respecting strings/escapes) to find the matching close, and return that substring.
- On no/again-invalid match, return the stripped text (so the caller's `json.loads` still raises and
  the existing extractor error handling fires).

### P2-8 — robust age parse (`access_quality_scorer._parse_min_age`)
Replace `str(age_str).replace(">=","").replace(">","")` + `int(...)` with:
- Early-return `None` for `NA`/`""`/`"FDA labelled age"`/`"No Age Restriction"` (non-numeric).
- `m = re.search(r"\d+", s)`; return `int(m.group())` if found else `None` — tolerates "6 years",
  ">=6 years", etc.
- Optionally return a `(value, inclusive)` signal for `>` vs `>=`; if kept simple, document that
  both map to the same integer threshold (current behavior) so the comparison stays consistent.

### P2-11 — close fitz doc (`document_processor.process_pdf`)
Wrap the document in a context manager: `with fitz.open(pdf_path) as doc:` (PyMuPDF supports it), or
add `try/finally: doc.close()`. Build and return the `pages` list inside/after, unchanged.

## Testing strategy
- **P3-1/P3-2:** grep shows no "was used" prints; `StepTherapyExtractor.extract_approval_section.__doc__` is non-empty.
- **P3-3:** each extractor module imports and its `__main__` path references the current signature (static check / dry import).
- **P3-5:** `git ls-files` no longer lists the artifacts; `git check-ignore .venv .DS_Store foo.exe foo.docx` all match.
- **P3-6:** unit cases across boundary scores (24/25/49/50/74/75) show category and alignment agree.
- **P3-7:** `clean_text` output identical before/after on blank-line-heavy input.
- **P2-7:** `clean_json_output('{"a":1} trailing }')` and `'```json\n{"a":{"b":2}}\n```'` both parse to the intended object; a no-JSON string returns something that fails `json.loads`.
- **P2-8:** `_parse_min_age` on `">=6"`, `"6 years"`, `">18"`, `"NA"`, `"FDA labelled age"` returns `6,6,18,None,None`.
- **P2-11:** `process_pdf` on a sample PDF returns pages and leaves no open handle (no fitz "document closed" needed by callers; smoke-run the batch path).
- Final `py_compile` of all touched files.
