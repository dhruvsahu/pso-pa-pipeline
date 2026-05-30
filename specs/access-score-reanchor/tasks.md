# Tasks — Access Score Re-Anchor (deterministic, full 0–100)

> **⚠️ SUPERSEDED (2026-05-30) by `specs/fix-access-score-review/`.** These tasks built the v2.0
> credit-for-absence model, which review found flawed; it is being corrected under Option A. History
> only — follow the fix spec.

Implemented one at a time; update `../../handoff-memory.md` after each. Re-score/regenerate use the
stored JSON only (no LLM).

---

### task-1.1 — Re-anchor the scorer to full 0–100 (deterministic)
- **BlockedBy:** none
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py`
- **Change:** Keep 50 = parity and all existing deductions. Add the credit track (no-step +15,
  no-phototherapy +5, no-reauth +10, no-QL +5, no-specialist +5, age ≤FDA +5, TB-waived +5; cap
  +50) with an either/or guard so each dimension contributes a deduction OR a credit, never both.
  Clamp `[0,100]`. Update category cutoffs to `[0,25)/[25,50)/[50,75)/[75,100]`. Rename/extend
  `score_breakdown` to `{deductions, credits}`. Bump `SCORER_VERSION = "2.0"`.
- **Outcome:** `calculate_score` can return the full 0–100 with anchored categories; input contract
  unchanged (callers/`rescore.py` untouched).
- **Context:** Req 1.1–1.6. Exact weights finalized in task-1.2.

### task-1.2 — Calibration fixtures + weight tuning
- **BlockedBy:** task-1.1
- **Agent:** general-purpose
- **File:** `access_quality_scorer.py` (`__main__` self-test) or new `test_scoring.py`
- **Change:** Add runnable assertions for the three anchors: unrestricted policy → `>=75`,
  maximally restrictive → `<=10`, FDA-parity-with-PA → `50±10`. Tune the credit weights (esp. the
  absence-credits that represent FDA-baseline behavior) until all three pass.
- **Outcome:** Anchor semantics demonstrably correct without a gold dataset; fixtures committed.
- **Context:** Req 2.1–2.4. If parity overshoots, trim no-reauth/no-QL credits first (see design).

### task-1.3 — Re-score stored results + regenerate outputs
- **BlockedBy:** task-1.2
- **Agent:** general-purpose
- **File:** `rescore.py` (existing), `outputs/final_access_results.{json,csv,xlsx}`
- **Change:** Run `python rescore.py` then `python result_formatter.py`. Verify range `[0,100]`,
  category consistency, the stale `377585-4984547.pdf`/STELARA row re-scores under v2.0, and CSV
  conformance (79 rows, exact header, no blanks/sentinels) holds.
- **Outcome:** Shipped outputs reflect scorer v2.0; dataset reproducible (`rescore.py` twice =
  identical JSON).
- **Context:** Req 3.1–3.4.

### task-1.4 — Update docs (README + ADR)
- **BlockedBy:** task-1.3
- **Agent:** general-purpose
- **File:** `README.md`, `docs/ADR.md`
- **Change:** README scoring section → new weight table, cutoffs, regenerated distribution stats
  (min/max/mean/median + category counts from the new CSV). ADR → update ADR-006 or add ADR-012
  superseding it, recording the P0-5 deferral → Devil's Advocate review → objective text that
  reopened it → deterministic re-anchor decision.
- **Outcome:** Docs match the v2.0 model and the regenerated data.
- **Context:** Req 4.1–4.2.

---

## Dependency diagram

```
task-1.1 ──► task-1.2 ──► task-1.3 ──► task-1.4
(re-anchor)  (calibrate)  (re-score)   (docs)
```

Edges: task-1.2 ← task-1.1; task-1.3 ← task-1.2; task-1.4 ← task-1.3. task-1.1 is the only root.

## Execution summary
- **Active tasks: 4**, fully sequential (each depends on the prior).
- **Stage 1:** task-1.1 · **Stage 2:** task-1.2 · **Stage 3:** task-1.3 · **Stage 4:** task-1.4
- **Critical path:** task-1.1 → task-1.2 → task-1.3 → task-1.4 (4 stages)
- **Total stages:** 4
- No LLM calls in any task → no impact on eval-model rate limits.
