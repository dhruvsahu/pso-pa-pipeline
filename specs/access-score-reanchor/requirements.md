# Requirements — Access Score Re-Anchor (deterministic, full 0–100)

> **⚠️ SUPERSEDED (2026-05-30) by `specs/fix-access-score-review/`.** The v2.0 credit-for-absence
> model specified below was found flawed by review (`REVIEW.md`): it scored missing data as "no
> restriction" and inflated FDA-parity policies above 50. Per **Option A**, the absence-credits are
> removed (credits only for strictly better-than-FDA terms), so the practical ceiling is ~58 and the
> 75/100 anchors are accepted as unreachable for this dataset. The weights, the "+50 cap / reaches
> 100" language, and the "≥75" fixtures in this document are **obsolete** — see the fix spec and
> ADR-016. Retained for history only.

## Introduction

The hackathon objective defines the Access Quality score as a 0–100 scale with explicit anchors:

> "a score of 0 – 100 (0 indicate No access, 25 is restricted access against FDA guidelines,
> 50 is Parity with FDA label, 75 is preferred than FDA label, 100 is the best possible access
> against all competitors / no restrictions applied). You can create this framework based on the
> parameter values you have extracted and come up with a logic / GenAI process for the same."

The current scorer (`access_quality_scorer.py`, `SCORER_VERSION = "1.0"`) starts at 50 and can add
at most +8 (TB +3, age +5), so its reachable ceiling is ~58 — it **cannot represent the 75 or 100
anchors at all**. This spec re-anchors the scorer, using a **deterministic** (non-LLM) framework,
so the score spans the full 0–100 with the anchor semantics above. This supersedes the deferral of
finding **P0-5** recorded in `specs/fix-review-findings/`.

### Why deterministic (not GenAI / hybrid)

An LLM-based scorer would add ~79 calls / ~120K tokens per run. The intended **evaluation** models
have small per-day budgets — `llama-3.3-70b-versatile` = 100K tokens/day, `llama-3.1-8b-instant` =
500K tokens/day / 6K TPM — which the extraction workload already strains. A deterministic scorer
adds **zero** API/token cost, is reproducible (critical for grading), and is explainable. (Making
*extraction* itself graceful under those daily caps is a separate, out-of-scope effort.)

### In scope
- Re-anchor `calculate_score` so the score can reach the full 0–100 with anchors 0/25/50/75/100.
- Keep the computation deterministic (no LLM, no network).
- Preserve a per-row explainable breakdown.
- Bump `SCORER_VERSION`, re-score the stored results, regenerate `outputs/`, refresh docs.

### Out of scope
- Any LLM/GenAI scoring path.
- Validating against a gold Access Score (none is provided; calibration is via synthetic anchor
  fixtures — see Requirement 2).
- Extraction-side rate-limit handling (per-model TPM config, RPD/TPD throttling). Separate spec.
- Modeling competitive/formulary positioning (the "against all competitors" clause) — not extracted
  by the pipeline; the 100 anchor is approximated as "no restrictions applied".

---

## Requirement 1: Score spans the full 0–100 with the objective's anchors

**User story:** As a grader comparing against the gold Access Score, I want scores that use the full
0–100 range with the stated anchor meanings, so that preferred / unrestricted policies are not
structurally capped at ~58.

**Acceptance criteria:**

1. THE SYSTEM SHALL anchor the scale as: 0 = no access, 25 = restricted vs FDA, 50 = parity with FDA label, 75 = preferred vs FDA label, 100 = best possible / no restrictions applied.
2. THE SYSTEM SHALL keep every score within the closed range `[0, 100]`.
3. WHEN a policy imposes restrictions beyond the FDA label THE SYSTEM SHALL reduce the score below 50 toward 0 in proportion to the restriction burden.
4. WHEN a policy imposes no restrictions beyond the FDA label THE SYSTEM SHALL be able to score it at or above 75.
5. THE SYSTEM SHALL assign an access category whose cutoffs align with the anchors: `[0,25)` Highly Restricted, `[25,50)` Restricted Access, `[50,75)` FDA Parity, `[75,100]` Preferred Access.
6. THE SYSTEM SHALL compute the score deterministically from the extracted parameter values, with no LLM call and no network access.

## Requirement 2: Calibrated anchor behavior (testable)

**User story:** As a maintainer, I want the re-anchored model verified against known-shape policies,
so that the anchor semantics are demonstrably correct without a gold dataset.

**Acceptance criteria:**

1. WHEN scoring a synthetic policy with no step therapy, no phototherapy, no specialist restriction, no reauthorization, no quantity limit, age at-or-broader-than FDA, and TB not required THE SYSTEM SHALL return a score `>= 75`.
2. WHEN scoring a synthetic maximally restrictive policy (3+ brand steps, generic steps, phototherapy, specialist, reauthorization, quantity limit, age more restrictive than FDA) THE SYSTEM SHALL return a score `<= 10`.
3. WHEN scoring a synthetic policy that matches the FDA label's expected friction (no extra step therapy, but TB required as FDA expects, with utilization-management typical of a parity PA) THE SYSTEM SHALL return a score within `50 ± 10`.
4. THE SYSTEM SHALL keep these calibration checks in the repository as runnable fixtures.

## Requirement 3: Reproducible re-score and regeneration

**User story:** As a maintainer, I want the stored results and shipped outputs regenerated under the
new model, so the dataset and docs are reproducible and self-consistent.

**Acceptance criteria:**

1. THE SYSTEM SHALL stamp each `access_quality` result with the new `SCORER_VERSION`.
2. WHEN the re-score routine runs THE SYSTEM SHALL recompute every stored row's `access_quality` from its stored extraction values, with no LLM call.
3. THE SYSTEM SHALL regenerate `outputs/final_access_results.{json,csv,xlsx}` from the re-scored data.
4. THE SYSTEM SHALL preserve a per-row `score_breakdown` listing the deductions and credits applied.

## Requirement 4: Documentation reflects the new model

**User story:** As a reviewer, I want the README and ADR to describe the re-anchored model and its
numbers, so the methodology is traceable and matches the shipped data.

**Acceptance criteria:**

1. THE SYSTEM SHALL update the README scoring section with the new weight table, category cutoffs, and the regenerated score-distribution statistics.
2. THE SYSTEM SHALL record the re-anchor decision in an ADR (update ADR-006 or add a successor), including the deferred-then-revisited history and the deterministic rationale.
