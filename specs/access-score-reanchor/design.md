# Design — Access Score Re-Anchor (deterministic, full 0–100)

> **⚠️ SUPERSEDED (2026-05-30) by `specs/fix-access-score-review/`.** The credit-for-absence weights
> (+15/+10/+5… with a +50 cap "reaching 100") below are obsolete. Per **Option A**, absence-credits
> were removed; only strictly better-than-FDA credits (age-younger +5, TB-waived +3) remain →
> ceiling ~58, 75/100 not reachable for this dataset. See the fix spec and ADR-016. History only.

## Overview

Re-anchor `AccessQualityScorer.calculate_score` from a deduction-only model (pivot 50, ceiling ~58)
to a **two-sided deterministic model**: pivot 50 = FDA parity, **deductions** push toward 0 for
restrictions beyond the FDA label, **credits** push toward 100 for the absence of restrictions /
terms at-or-better-than the FDA label. Exact weights are tuned to satisfy the Requirement 2 anchor
fixtures. No LLM, no network — the score is a pure function of the five extracted parameter dicts.

This touches one module (`access_quality_scorer.py`), reuses the existing `rescore.py` +
`result_formatter.py` for regeneration, and updates README + ADR.

## The anchoring problem (and the design decision)

For the PsO brands in `assets/fda_baselines.csv`, the FDA baseline already has
`step_therapy_expected = No`, `specialist_required = No`, `quantity_limit_expected = No`,
`reauthorization_expected = No` (TB mostly `Yes`). So a policy *matching* FDA imposes none of those
— which is hard to distinguish from "no restrictions applied" (the 100 anchor). The objective's
anchors are therefore not perfectly separable from extracted parameters alone, and there is **no
gold score** to calibrate against.

**Design decision:** calibrate the model so it satisfies three *synthetic* anchor fixtures
(Requirement 2): unrestricted → `>=75`, maximally restricted → `<=10`, FDA-parity-with-PA → `50±10`.
Exact weights are chosen to pass these fixtures rather than asserted up front. This keeps the model
honest about the calibration uncertainty while making the behavior testable and reproducible.

## Scoring model

Start at **50**. Apply deductions and credits, then clamp to `[0,100]`.

### Deductions (restrictions beyond FDA — push toward 0) — unchanged from v1.0
| Restriction | Penalty |
|---|---|
| Brand/biologic step | −10 each (cap −30) |
| Generic step | −5 each (cap −15) |
| Phototherapy required as a step | −5 |
| Specialist restriction (FDA = none) | −8 |
| Reauthorization required (FDA = none) | −5 |
| Quantity limit (FDA = none) | −5 |
| TB required when FDA does not expect it | −3 |
| Age more restrictive than FDA | −5 |

### Credits (absence of restriction / better-than-FDA — push toward 100) — NEW
Starting values (to be tuned against the Requirement 2 fixtures):

| Condition | Credit |
|---|---|
| No step therapy at all (0 brand + 0 generic steps) | +15 |
| No phototherapy step | +5 |
| No reauthorization required | +10 |
| No quantity limit | +5 |
| No specialist restriction | +5 |
| Age at-or-broader-than FDA | +5 |
| TB waived where FDA expects it | +5 |

- Total credit caps at **+50** so an utterly unrestricted policy reaches 100; maximally restrictive
  bottoms near 0.
- **Symmetry / no double-count guard:** each dimension contributes *either* a deduction *or* a
  credit, never both — a dimension's credit fires only when its corresponding deduction did not.
- The **FDA-parity calibration** (fixture 3) is what pins the midpoint: weights are tuned so a
  policy with FDA-typical friction (TB required like FDA, no extra steps, but a parity PA with
  reauth/QL) lands ~50 rather than ~95. If the starting values overshoot parity, reduce the
  absence-credits (e.g. drop "no reauth"/"no QL" credits, which represent FDA-baseline behavior
  rather than better-than-FDA) until fixture 3 passes. Implementation tunes against the fixtures.

### Category cutoffs (Req 1.5)
`[0,25)` Highly Restricted · `[25,50)` Restricted Access · `[50,75)` FDA Parity · `[75,100]` Preferred Access.

### Breakdown
`score_breakdown = {"deductions": [...], "credits": [...]}` (rename/extend the current
`{deductions, bonuses}`); each entry is a human-readable reason with its signed magnitude.

## Components

1. **`access_quality_scorer.py`**
   - Bump `SCORER_VERSION = "2.0"`.
   - Add the credit logic alongside the existing deductions in `calculate_score`; apply the
     either/or guard per dimension; clamp `[0,100]`; update category cutoffs; emit `credits` in the
     breakdown and keep `scorer_version` in the result.
   - Keep the input contract identical (same five extractor dicts), so `rescore.py` and
     `pipeline_runner.py`/`run_full_pipeline.py` need no change.

2. **Calibration fixtures** — a runnable check (extend the module's `__main__` self-test or add a
   small `test_scoring.py`) asserting the three Requirement 2 anchors. Used to tune the weights.

3. **Regeneration** — run `python rescore.py` (recomputes `access_quality` for all 79 stored rows
   from stored extraction values, no LLM) then `python result_formatter.py` (rebuilds CSV/XLSX).

4. **Docs** — README scoring section (weights, cutoffs, regenerated distribution) and ADR
   (update ADR-006 "FDA Parity Baseline Scoring" or add ADR-012 superseding it; reference the P0-5
   deferral + Devil's Advocate review + the objective text that reopened it).

## Determinism / rate-limit note
`calculate_score` and `rescore.py` make no API calls, so re-scoring all 79 rows is instant and free
— it consumes none of the eval models' RPM/TPM/RPD/TPD budgets. (Extraction-side rate-limit
gracefulness is explicitly out of scope.)

## Testing strategy
- Requirement 2 fixtures (unrestricted ≥75, max-restricted ≤10, parity 50±10) — must pass; weights
  tuned until they do.
- Re-score determinism: running `rescore.py` twice yields byte-identical JSON.
- Range invariant: all 79 regenerated scores in `[0,100]`; categories consistent with cutoffs.
- Regression on the known stale row (`377585-4984547.pdf`/STELARA): re-scores deterministically
  under v2.0 (no legacy flat-list breakdown).
- CSV conformance unchanged (still 79 rows, exact header, no blanks/sentinels) after regeneration.
