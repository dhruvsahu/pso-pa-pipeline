# Requirements — Fix Access-Score Review Findings (v2.0 → v2.1)

> **Update (v2.2, 2026-05-30):** a second review of the v2.1 result found that removing *all*
> absence-credits made a verified-open policy indistinguishable from an unextracted one. Per user
> decision, v2.2 adds a **small +2 "confirmed-open" credit** per axis that fires only on positive
> evidence of absence (explicit "No" / empty list / confirmed 0), never on `"NA"` — a tri-state per
> axis. `"NA"` stays neutral (the P0-1 fix holds). 50 becomes the neutral baseline; ceiling ~68;
> Preferred (≥75) still unreachable. See `docs/ADR.md` ADR-016 (v2.2 refinement) and `REVIEW.md`.

## Introduction

The 5-perspective `/review` of the v2.0 re-anchor (`REVIEW.md`, 2026-05-30) found that the new
credit-for-absence track (a) scored missing data (`"NA"`) as confirmed "no restriction" — inflating
86% of rows and making the two empty extractions score "Preferred" — and (b) credited the absence
of restrictions the FDA baseline also lacks, pushing true FDA-parity policies to ~76 and breaking
the objective's "50 = parity" anchor. This spec corrects the scorer and the surrounding artifacts.

**Decision recorded:** for finding **P1-1 we adopt option (a)** — credit ONLY strictly
better-than-FDA terms. The absence-credits (no step therapy / no phototherapy / no specialist /
no reauthorization / no quantity limit) are **removed**; only age-less-restrictive (+5) and
TB-waived (+3) remain as credits (both already require positive evidence, so they are safe).

### Consequence to acknowledge up front

Option (a) makes **50 = FDA parity faithful** and removes the `"NA"`-inflation, but it also means the
practical ceiling returns to **~58** (50 + age 5 + TB 3) for these PsO PA policies. The objective's
**75 / 100 anchors become unreachable from the extracted parameters** — reachable only by
hypothetically super-permissive / competitively-preferred policies that do not appear in this
dataset. This is the **honest** reading (consistent with the original ADR-006 observation and the
earlier Devil's Advocate analysis: a prior-authorization policy only *adds* restrictions versus the
FDA label, so it sits at or below parity). **This requirement set therefore supersedes
`specs/access-score-reanchor/` Requirement 1.4 ("no restrictions → ≥75")** — full-range
reachability is intentionally traded for anchor-faithfulness and correctness.

### In scope
P0-1, P1-1 (option a), P1-2, P1-3, P2-1, P2-2, P2-3, P2-4, P3-1, P3-2, P3-3 from `REVIEW.md`.

### Out of scope
A gold-validated calibration (no gold Access Score exists; P1-3 validation harness from the original
review remains deferred); modeling competitive/formulary positioning (the "against all competitors"
sense of 100); any extractor re-run.

---

## Requirement 1: `"NA"` (unknown) never moves the score

**User story:** As a grader, I want a missing/unextracted parameter to leave the score at parity for
that dimension, so the score reflects what was found — not what was missed.

**Acceptance criteria:**

1. WHEN an extractor value for a dimension is the `"NA"` sentinel (or `None`/empty-string) THE SYSTEM SHALL apply neither a deduction nor a credit for that dimension.
2. THE SYSTEM SHALL distinguish three states per restriction dimension — *present* (deduct), *confirmed absent* (credit only if better-than-FDA per Requirement 2), and *unknown* (no effect).
3. WHEN scoring a policy whose every parameter is `"NA"` THE SYSTEM SHALL return a score at the FDA-parity baseline (~50), not in the Preferred band.

## Requirement 2: Credits only for strictly better-than-FDA terms (P1-1 option a)

**User story:** As a grader, I want a policy that merely matches the FDA label to score 50, so the
"50 = parity" anchor means what the objective says.

**Acceptance criteria:**

1. THE SYSTEM SHALL award credits ONLY for terms that are strictly more permissive than the FDA label: age threshold lower than FDA (+5) and TB test not required where FDA expects it (+3).
2. THE SYSTEM SHALL NOT award credit for the absence of step therapy, phototherapy, specialist, reauthorization, or quantity limit (these are FDA-baseline behaviors, not better-than-FDA).
3. WHEN a policy mirrors the FDA label exactly (no restrictions beyond FDA, TB as FDA expects, age at FDA threshold) THE SYSTEM SHALL score it within 50 ± 5.
4. THE SYSTEM SHALL retain all existing deductions for restrictions beyond the FDA label, and keep the score clamped to `[0, 100]`.

## Requirement 3: Calibration fixtures reflect true anchor semantics

**User story:** As a maintainer, I want fixtures that actually test the anchors, so the calibration
cannot pass while the model is wrong.

**Acceptance criteria:**

1. THE SYSTEM SHALL include a fixture for a true FDA-parity policy asserting a score within 50 ± 5.
2. THE SYSTEM SHALL include a fixture for a maximally restrictive policy asserting a score ≤ 10.
3. THE SYSTEM SHALL include a fixture for the most-permissive extractable policy (age-broader + TB-waived) asserting a score at the achievable ceiling (≥ 50 and < 75).
4. THE SYSTEM SHALL include a fixture for an all-`"NA"` policy asserting a score within 50 ± 5 (unknown ⇒ parity, never Preferred).

## Requirement 4: Robust parameter parsing

**User story:** As a maintainer, I want the age and reauthorization comparisons to be robust, so
malformed or upper-bound values don't produce wrong or contradictory scores.

**Acceptance criteria:**

1. WHEN a payer age value is an upper bound (e.g. "<18") THE SYSTEM SHALL NOT treat it as a minimum-age threshold and SHALL NOT emit a "more restrictive than FDA" deduction with a contradictory rationale. [P2-2]
2. THE SYSTEM SHALL compare `reauthorization_required` case-insensitively and treat only an explicit affirmative as "required" (no sign flip on casing). [P2-1]

## Requirement 5: Reproducible re-score with version visibility

**User story:** As a maintainer, I want re-scoring to report what versions it found, so stale-version
drift is visible rather than silent.

**Acceptance criteria:**

1. THE SYSTEM SHALL bump `SCORER_VERSION` to mark the corrected model and stamp it on every row.
2. WHEN `rescore.py` runs THE SYSTEM SHALL report the distinct `scorer_version` values present in the input before overwriting them. [P2-3]
3. THE SYSTEM SHALL recompute every stored row deterministically with no LLM call and remain idempotent.

## Requirement 6: Documented regenerate-vs-rerun boundary

**User story:** As a maintainer, I want it explicit that re-scoring does not pick up extractor fixes,
so I am not surprised when an extractor change has no effect.

**Acceptance criteria:**

1. THE SYSTEM SHALL state in `rescore.py` and the ADR that re-scoring reflects scoring-logic changes only, and that extractor fixes require a full pipeline re-run. [P2-4]

## Requirement 7: Documentation is consistent and accurate

**User story:** As a reviewer, I want every doc to match the corrected model and the regenerated
numbers, so nothing misleads.

**Acceptance criteria:**

1. THE SYSTEM SHALL update the README scoring section (credit table = age/TB only, regenerated distribution stats) and use half-open category notation consistent with the code (`[0,25) / [25,50) / [50,75) / [75,100]`). [P3-2]
2. THE SYSTEM SHALL update `docs/ADR.md` (ADR-016) to record the option-(a) correction and the ~58 ceiling, superseding the credit-for-absence description. [P1-3 docs]
3. THE SYSTEM SHALL update `docs/PIPELINE_FLOW.md` stale v1.0 score stats to the regenerated figures. [P3-1]
4. THE SYSTEM SHALL reconcile `specs/access-score-reanchor/` (design.md/tasks.md) weights with the as-built corrected model, or mark that spec superseded by this one. [P1-3]

## Requirement 8 (optional): Data-driven weights

**User story:** As a maintainer retuning the model, I want the weights in one declarative place, so a
change touches one source, not three.

**Acceptance criteria:**

1. THE SYSTEM SHOULD express the per-dimension deduction/credit weights and reason templates in a single table from which the score math, the `score_breakdown` strings, and (ideally) the README table derive. [P3-3]
