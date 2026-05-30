# Tasks — Fix Access-Score Review Findings (v2.0 → v2.1)

One task per finding (+ a capstone re-score and a docs task). Implemented one at a time; update
`../../handoff-memory.md` after each. Re-score/regenerate use the stored JSON only (no LLM).

---

### task-1.1 — P0-1 + P1-1(a): remove absence-credits; keep only better-than-FDA credits
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Delete the v2.0 absence-credit branches (no-step +10, no-photo +3, no-specialist +5,
  no-reauth +5, no-QL +3). Keep all deductions and the existing age-less (+5) / TB-waived (+3)
  credits. Bump `SCORER_VERSION = "2.1"`. Net: `"NA"`/missing → no branch fires → no score change;
  a parity policy → 50.
- **Outcome:** `"NA"` is neutral (Req 1); 50 = faithful parity (Req 2); ceiling ~58. Resolves the
  86%-inflation and the "empty extraction = Preferred" defect.
- **Context:** Req 1.1–1.3, 2.1–2.4. `score_breakdown` stays `{deductions, credits}`.

### task-1.2 — P1-2: rewrite calibration fixtures
- **BlockedBy:** task-1.1, task-1.3, task-1.4
- **Agent:** general-purpose
- **File:** `test_scoring.py`
- **Change:** Replace fixtures with: true-parity (payer == FDA: no extras, TB required, age=FDA) →
  50±5; max-restrictive → ≤10; most-permissive (age-broader + TB-waived) → ≥50 and <75; all-`"NA"`
  → 50±5.
- **Outcome:** fixtures test the real anchors; the all-`"NA"` case guards against regression of P0-1.
- **Context:** Req 3.1–3.4. (Blocked by the parsing fixes so fixture expectations are stable.)

### task-1.3 — P2-2: age upper-bound (`<`) handling
- **BlockedBy:** task-1.1
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Detect a leading `<` (or "under"/"up to") in the payer age value; treat as an upper
  bound, not a minimum — skip the min-age more/less comparison (no deduction, no credit, no
  contradictory rationale).
- **Outcome:** the 3 `<18` rows no longer get a spurious −5 with a self-contradicting message.
- **Context:** Req 4.1.

### task-1.4 — P2-1: reauth comparison normalization
- **BlockedBy:** task-1.1
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Compare `reauthorization_required` case-insensitively (`...strip().lower() == "yes"`)
  for the deduction trigger.
- **Outcome:** no sign flip on casing drift.
- **Context:** Req 4.2.

### task-1.5 — P2-3: `rescore.py` reports input versions
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `rescore.py`
- **Change:** Before overwriting, collect and print the distinct input `scorer_version` counts
  (e.g. `input versions: {'2.0': 79} → rewriting as 2.1`).
- **Outcome:** version drift is visible, not silent.
- **Context:** Req 5.2.

### task-1.6 — P2-4: document regenerate-vs-rerun boundary
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `rescore.py` (docstring), `docs/ADR.md`
- **Change:** State that re-scoring reflects scoring-logic changes only; extractor fixes need a full
  pipeline re-run.
- **Outcome:** the "why didn't my extractor fix take effect" trap is documented.
- **Context:** Req 6.1.

### task-1.7 — P3-3 (optional): declarative weights table
- **BlockedBy:** task-1.2
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Express per-dimension detect/deduction/credit/reason in one table driving a single
  scoring loop; derive `score_breakdown` strings (and ideally the README table) from it.
- **Outcome:** one source of truth for weights; either/or invariant structural.
- **Context:** Req 8.1. Do only after behavior fixes are green; skip if time-constrained.

### task-2.1 — capstone: re-score + regenerate + verify
- **BlockedBy:** task-1.1, task-1.3, task-1.4
- **Agent:** general-purpose
- **File:** `rescore.py` (run), `result_formatter.py` (run), `outputs/final_access_results.{json,csv,xlsx}`
- **Change:** Run `python rescore.py` then `python result_formatter.py`. Verify: all rows
  `scorer_version=="2.1"`; 0 rows carry a removed absence-credit string; the two all-`"NA"` rows
  (`287728-4459856.pdf/STELARA`, `361202-4967201.pdf/TREMFYA`) drop from 76 to ~50; 0 rows ≥75;
  range ~7–58; CSV 79 rows, exact header, 0 blanks; `rescore.py` idempotent.
- **Outcome:** shipped outputs reflect v2.1; inflation gone.
- **Context:** Req 5.3.

### task-2.2 — docs: README + ADR-016 + PIPELINE_FLOW + reanchor-spec note
- **BlockedBy:** task-2.1
- **Agent:** general-purpose
- **File:** `README.md`, `docs/ADR.md`, `docs/PIPELINE_FLOW.md`, `specs/access-score-reanchor/design.md`
- **Change:** README scoring section → credit table = age/TB only + regenerated stats + half-open
  category notation (P3-2). ADR-016 → option-(a) corrected model + ~58 ceiling (supersede the
  credit-for-absence text; keep ADR-006 supersession). PIPELINE_FLOW.md → regenerated v2.1 stats
  (P3-1). access-score-reanchor spec → header note "superseded by specs/fix-access-score-review/"
  (P1-3).
- **Outcome:** docs match the corrected model and data.
- **Context:** Req 7.1–7.4.

---

## Dependency diagram

```
task-1.1 ──┬──► task-1.3 ──┐
           ├──► task-1.4 ──┤
           │               ├──► task-2.1 ──► task-2.2
           └──► task-1.2 ◄─┘   (re-score)     (docs)
                (fixtures; also ← 1.3,1.4)

task-1.5 (rescore versions)   [independent]
task-1.6 (boundary doc)        [independent]
task-1.7 (weights table, opt) ← task-1.2
```

Edges: 1.3←1.1; 1.4←1.1; 1.2←1.1,1.3,1.4; 2.1←1.1,1.3,1.4; 2.2←2.1; 1.7←1.2. Roots: task-1.1,
task-1.5, task-1.6.

## Execution summary
- **Active tasks: 9** (task-1.7 optional).
- **Stage 1:** task-1.1, task-1.5, task-1.6
- **Stage 2:** task-1.3, task-1.4 (← 1.1)
- **Stage 3:** task-1.2 (← 1.1,1.3,1.4), task-2.1 (← 1.1,1.3,1.4)
- **Stage 4:** task-2.2 (← 2.1)  [task-1.7 optional, ← 1.2]
- **Critical path:** task-1.1 → task-1.3/1.4 → task-2.1 → task-2.2 (4 stages)
- **Total stages:** 4
- No LLM calls in any task → no eval-model rate-limit impact.
