# Tasks — Fix Review Findings (P2 subset)

Three P2 issues selected for implementation. These are independent of each other and independent
of the completed P0/P1 tasks (no blockers).

---

### task-6.1 — P2-7: `clean_json_output` greedy regex over-captures trailing braces

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/extractor_utils.py`
- **What's wrong:** `re.search(r"\{.*\}", text, flags=re.DOTALL)` is greedy — if the LLM
  appends prose containing a `}` after the JSON object (e.g. `{"tb": "No"} Note: see page 3}`),
  the regex captures from the first `{` to the **last** `}` in the entire string, pulling in
  garbage that makes `json.loads` fail. That exception is swallowed by extractors (P1-2 mitigated
  but not eliminated), producing a silent all-NA row.
- **Fix:** Replace the greedy regex with a balanced-brace scanner: walk character-by-character from
  the first `{`, track nesting depth, and return when depth returns to 0. This correctly extracts
  the first complete JSON object regardless of trailing text. Alternatively, use
  `json.JSONDecoder().raw_decode()` which does the same thing natively.
- **Outcome:** LLM responses with trailing prose/braces no longer cause JSON parse failures.
  The 5 extractors benefit automatically since they all call `clean_json_output`.
- **Verification:** Unit-test with inputs like:
  - `'{"key": "val"}  some trailing text }'` — should return `{"key": "val"}`
  - `'Here is the JSON: {"a": {"b": 1}} done.'` — should return `{"a": {"b": 1}}`
  - `'```json\n{"x": 1}\n```'` — should return `{"x": 1}` (existing backtick strip still works)

---

### task-6.2 — P2-8: `_parse_min_age` conflates `>` with `>=` and chokes on extra text

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **What's wrong:** The current implementation:
  ```python
  s = str(age_str).strip().replace(">=", "").replace(">", "").strip()
  return int(s)
  ```
  1. Treats `">18"` and `">=18"` identically (both yield 18), losing the `>` vs `>=` distinction.
  2. Chokes on strings with extra text like `"6 years"`, `">=6 years of age"`, or `"Adults (>=18)"`
     — `int("6 years")` raises `ValueError` → returns `None` → scorer may apply a wrong penalty
     or skip a valid comparison.
- **Fix:** Use a regex to extract the first integer from the string:
  `re.search(r'(\d+)', str(age_str))`. If matched, return `int(match.group(1))`. If no digits
  found, return `None`. This handles all observed formats:
  - `">=18"` → 18
  - `">18"` → 18
  - `">=6 years of age"` → 6
  - `"6 years"` → 6
  - `"Adults (>=18)"` → 18
  - `">=12"` → 12
  - `"NA"` → None (no digits)
- **Scope note:** The `>` vs `>=` distinction is a real semantic difference, but every age value in
  our 79-row dataset uses `>=` format. Treating `>18` as 18 (not 19) is acceptable for the
  hackathon scorer — a precise fix would need the scorer to carry the operator through, which is
  out of scope.
- **Outcome:** Age strings with trailing text no longer fail to parse; scorer comparisons work
  correctly for all observed formats.
- **Verification:** Test `_parse_min_age` with: `">=18"`, `">18"`, `"6 years"`,
  `">=6 years of age"`, `"Adults (>=18)"`, `"NA"`, `""`, `None` — all should return the expected
  integer or `None`.

---

### task-6.3 — P2-11: `fitz.open()` handle never closed — resource leak in batch

- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `utils/document_processor.py`
- **What's wrong:** `process_pdf` calls `doc = fitz.open(pdf_path)` but never closes the handle.
  PyMuPDF (`fitz`) holds a native C-level file descriptor and memory-mapped pages. Across a
  79-PDF batch run, this leaks 79 open file handles and their associated memory. On Windows this
  also holds file locks, preventing other processes from accessing the PDFs.
- **Fix:** Use a context manager: `with fitz.open(pdf_path) as doc:`. The rest of the method body
  is indented under the `with` block. `fitz.Document` supports `__enter__`/`__exit__` natively.
- **Outcome:** Each PDF handle is closed immediately after page extraction; no leaked file
  descriptors or memory across the batch run.
- **Verification:** Run the batch pipeline and confirm no `ResourceWarning` or file-lock errors.
  Optionally add a log line after the `with` block to confirm cleanup.

---

## Dependency diagram

All three tasks are independent roots — no dependencies on each other or on the P0/P1 tasks.

```
task-6.1 (P2-7)   [independent]
task-6.2 (P2-8)   [independent]
task-6.3 (P2-11)  [independent]
```

## Execution summary

- **Active tasks: 3**
- **Stage 1 (parallel-safe):** task-6.1, task-6.2, task-6.3
- **Total stages:** 1
- **Critical path:** any single task (1 stage)

> These can be implemented in any order. Numbering continues from the P0/P1 task file
> (last was task-5.1) to avoid ID collisions.
