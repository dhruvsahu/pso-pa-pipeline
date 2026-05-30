# Design — Fix Access-Score Review Findings (v2.0 → v2.1)

## Overview

Correct the v2.0 scorer per `REVIEW.md`. The core move (P1-1 option a + P0-1) is to **remove the
absence-credit track** and keep only strictly-better-than-FDA credits, which simultaneously (a)
makes `"NA"` neutral again — the deduction side never fired on `"NA"`, and the only credits left
(age/TB) require positive evidence — and (b) restores 50 = faithful FDA parity. Then small parsing
fixes, a version-visibility tweak in `rescore.py`, a re-score + regenerate, and doc reconciliation.

`SCORER_VERSION` → **"2.1"** (corrected model). `score_breakdown` stays `{deductions, credits}`,
where `credits` now only ever contains age-less / TB-waived entries.

## The corrected model (v2.1)

Start at **50**. Apply deductions (unchanged from v1.0/v2.0) and only the two better-than-FDA
credits. Clamp `[0, 100]`. Category cutoffs unchanged (`<25 / <50 / <75 / ≥75`); `fda_alignment`
stays single-sourced from the same bands.

| Dimension | Deduction (present, beyond FDA) | Credit |
|---|---|---|
| Brand step therapy | −10/step (cap −30) | — (FDA baseline already none) |
| Generic step therapy | −5/step (cap −15) | — |
| Phototherapy step | −5 | — |
| Specialist restriction | −8 | — |
| Reauthorization | −5 | — |
| Quantity limit | −5 | — |
| TB test | −3 (FDA says No, payer Yes) | **+3** (FDA says Yes, payer No) |
| Age | −5 (payer > FDA) | **+5** (payer < FDA) |

Reachable range: **0 → 58** (50 + age 5 + TB 3). 50 = a policy matching FDA exactly; <50 = more
restrictive; 50–58 = the few dimensions where a payer can beat the FDA label. The 75/100 anchors are
not reachable from extracted parameters (documented; see Requirement 1.4 supersession).

### What changes in `access_quality_scorer.py`
Delete the v2.0 absence-credit branches:
- the `if brand_steps == 0 and generic_steps == 0: +10` block,
- the `if not phototherapy_required: +3` block,
- the `elif not payer_has_specialist: +5` branch,
- the `elif reauth != "Yes": +5` branch,
- the `elif not payer_has_ql: +3` branch.

Keep the deduction branches and the existing TB-waived (+3) / age-less (+5) credits (already in the
`credits` list). Result: `"NA"`/missing values hit no branch → no score change (Req 1.1–1.3). Bump
`SCORER_VERSION = "2.1"`.

> Tri-state is achieved implicitly: deductions require positive presence (`isinstance(list) and len>0`,
> `=="Yes"`, integer steps > 0); credits require positive better-than-FDA evidence. Nothing fires on
> `"NA"`. If the optional weights-table refactor (Req 8) is done, encode the three states explicitly.

## Parsing fixes

### Age `<` upper bound (Req 4.1 / P2-2) — `_parse_min_age` + age block
`_parse_min_age` currently regex-extracts the first integer, so `"<18"` → 18 and is compared as a
minimum (wrong; 3 rows get a −5 with a contradictory "payer <18 vs FDA >=4" message). Fix: detect a
leading `<` (or "under"/"up to") and treat the value as an **upper bound, not a minimum** — return a
signal the age block uses to skip the min-age more/less-restrictive comparison (no deduction, no
credit) rather than mis-deducting.

### Reauth normalization (Req 4.2 / P2-1) — reauth deduction
Compare case-insensitively: `str(reauth).strip().lower() == "yes"` for the deduction trigger. (No
reauth *credit* exists in v2.1, so the only risk is the deduction; normalize it for robustness.)

## `rescore.py` version visibility (Req 5.2 / P2-3) + boundary doc (Req 6 / P2-4)
Before overwriting, collect and print the distinct input `scorer_version` values, e.g.
`"[rescore] input versions: {'2.0': 79} → rewriting all as 2.1"`. Add to the module docstring (and
ADR) that re-scoring reflects **scoring-logic changes only** — extractor fixes (TB/Auth/age
semantics) stay frozen in the stored JSON and need a full pipeline re-run.

## Re-score + regenerate (capstone)
Run `python rescore.py` then `python result_formatter.py`. Expected: scores fall back to roughly the
v1.0 range (~7–58), the Preferred band empties (0 rows ≥75), the two all-`"NA"` rows drop from 76 to
~50, and no row carries an absence-credit. Verify CSV conformance (79 rows, exact header, 0 blanks).

## Documentation (Req 7)
- **README** scoring section → credit table = age/TB only; regenerated stats; half-open category
  notation `[0,25)/[25,50)/[50,75)/[75,100]`.
- **ADR-016** → amend Decision/Consequences to the option-(a) corrected model and the ~58 ceiling;
  note it supersedes the v2.0 credit-for-absence description (keep the ADR-006 supersession).
- **PIPELINE_FLOW.md** → replace stale v1.0 "7–50" stats with regenerated v2.1 figures.
- **`specs/access-score-reanchor/`** → add a header note that it is superseded by
  `specs/fix-access-score-review/` (don't silently leave contradictory weights). [P1-3]

## Optional refactor (Req 8 / P3-3)
A declarative `DIMENSIONS` table `{name: {detect, deduction, credit, reason}}` driving one scoring
loop, so weights live in one place and the either/or invariant is structural. Lower priority; do
only if time permits, after the behavior fixes land and tests are green.

## Testing strategy
- `test_scoring.py` rewritten (Req 3): true-parity → 50±5; max-restrictive → ≤10; most-permissive
  (age-broader + TB-waived) → ≥50 and <75 (≈58); all-`"NA"` → 50±5.
- Re-score idempotent (run twice → identical JSON); all rows `scorer_version=="2.1"`.
- Data check: 0 rows contain any of the removed absence-credit strings; the previously-76 all-`"NA"`
  rows now ~50; 0 rows ≥75.
- CSV conformance unchanged; `py_compile` on touched files.
