# Tasks — Review Cleanup (all P3 + P2-7, P2-8, P2-11)

One task per finding. Implemented one at a time; update `../../handoff-memory.md` after each.
(P3-4 is already resolved — `result_formatter.py` is guarded under `main()` — so it has no task.)

---

### task-1.1 — P3-1: remove leftover debug prints
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `extractors/step_therapy_extractor.py`
- **Change:** Delete the three `print("... was used")` statements (≈ lines 283, 403, 604); convert to
  `logging.debug` only if a line is genuinely useful.
- **Outcome:** No ad-hoc debug output on the hot path.
- **Context:** Req 1.1. Verify: grep finds no "was used" prints.

### task-1.2 — P3-2: restore `extract_approval_section` docstring
- **BlockedBy:** task-1.1
- **Agent:** general-purpose
- **File:** `extractors/step_therapy_extractor.py`
- **Change:** With the preceding `print` removed (task-1.1), ensure the triple-quoted block is the
  method's first statement so it is a real docstring.
- **Outcome:** `extract_approval_section.__doc__` is non-empty.
- **Context:** Req 1.2. Same file/region as task-1.1 (hence sequenced).

### task-1.3 — P3-3: verify/repair extractor `__main__` self-tests
- **BlockedBy:** task-1.2
- **Agent:** general-purpose
- **File:** `extractors/{age,step_therapy,authorization,utilization_management,clinical_access}_extractor.py`
- **Change:** Confirm each `__main__` block calls `extract(pages=..., brand=..., pdf_name=...)`
  (current signature); fix or remove any stale block. Likely a no-op verify (the `pdf_path=` form is
  already gone).
- **Outcome:** No broken self-tests.
- **Context:** Req 2.1, 2.2.

### task-1.4 — P3-5: untrack artifacts + extend `.gitignore`
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `.gitignore`, git index (no source edits)
- **Change:** `git rm --cached` (keep working copies) for `INSTALL_REQUIREMENTS.exe`,
  `PA_Business_Rules.xlsx`, `debug/*.txt`, `outputs/*`; append `.venv/`, `.DS_Store`, `*.exe`,
  `*.docx` to `.gitignore`.
- **Outcome:** `git ls-files` no longer lists those artifacts; `.venv`/`.DS_Store`/`*.exe`/`*.docx`
  ignored. Working tree unchanged.
- **Context:** Req 3.1–3.3. Takes effect on the next (user-initiated) commit.

### task-1.5 — P3-6: single-source category / fda_alignment
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Derive `fda_alignment` from the same score bands as `access_category` (drop the
  independent step-count branch) so they cannot disagree.
- **Outcome:** Category and alignment are consistent at all boundary scores.
- **Context:** Req 4.1, 4.2. **Coordination:** if `specs/access-score-reanchor/` task-1.1 is being
  implemented, satisfy this there (under the new cutoffs) and mark this done-by-reference.

### task-1.6 — P3-7: remove dead regex in `clean_text`
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/document_processor.py`
- **Change:** Remove the unreachable `\n{3,} → \n\n` substitution (the earlier `\n\s*\n+ → \n` already
  collapsed all 3+ newline runs).
- **Outcome:** No dead substitution; `clean_text` output unchanged on representative inputs.
- **Context:** Req 5.1, 5.2.

### task-2.1 — P2-7: balanced JSON extraction in `clean_json_output`
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/extractor_utils.py`
- **Change:** Replace greedy `re.search(r"\{.*\}", ...)` with a balanced-brace scan or
  `json.JSONDecoder().raw_decode` from the first `{`; keep fence stripping; on failure return text
  that fails `json.loads` cleanly.
- **Outcome:** Trailing prose/braces no longer break parsing; existing error handling still fires.
- **Context:** Req 6.1–6.3.

### task-2.2 — P2-8: robust `_parse_min_age`
- **BlockedBy:** task-1.5
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Early-return `None` for non-numeric tokens (`NA`/``/`FDA labelled age`/`No Age
  Restriction`); else `re.search(r"\d+", s)` → `int`; document `>`-vs-`>=` convention.
- **Outcome:** `">=6"/"6 years"/">18"/"NA"/"FDA labelled age"` → `6/6/18/None/None`.
- **Context:** Req 7.1–7.3. Same file as task-1.5 (hence sequenced).

### task-2.3 — P2-11: close fitz document
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/document_processor.py`
- **Change:** Use `with fitz.open(pdf_path) as doc:` (or `try/finally: doc.close()`) in
  `process_pdf`; return the same `[{page_number, text}]` structure.
- **Outcome:** No leaked native handles across the batch.
- **Context:** Req 8.1, 8.2. Same file as task-1.6 — sequence after it during implementation.

---

## Dependency diagram

```
task-1.1 (P3-1) ──► task-1.2 (P3-2) ──► task-1.3 (P3-3)        [step_therapy_extractor.py]

task-1.5 (P3-6) ──► task-2.2 (P2-8)                            [access_quality_scorer.py]

task-1.6 (P3-7) ──► task-2.3 (P2-11)   (file-order, same doc)  [document_processor.py]

task-1.4 (P3-5)   [independent]        task-2.1 (P2-7)  [independent, extractor_utils.py]
```

Edges: 1.2←1.1, 1.3←1.2, 2.2←1.5, 2.3←1.6 (same-file ordering). Roots (BlockedBy none):
task-1.1, task-1.4, task-1.5, task-1.6, task-2.1.

## Execution summary
- **Active tasks: 9** (P3-4 already resolved → no task).
- **Stage 1 (parallel-safe):** task-1.1, task-1.4, task-1.5, task-1.6, task-2.1
- **Stage 2:** task-1.2 (←1.1), task-2.2 (←1.5), task-2.3 (←1.6)
- **Stage 3:** task-1.3 (←1.2)
- **Critical path:** task-1.1 → task-1.2 → task-1.3 (3 stages)
- **Total stages:** 3
- No LLM calls in any task → no impact on rate limits.
