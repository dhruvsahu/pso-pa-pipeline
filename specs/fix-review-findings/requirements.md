# Requirements — Fix Review Findings (P0/P1 subset)

## Introduction

This spec addresses a selected subset of the findings in `REVIEW.md` (the 5-perspective
review of the PsO PA Pipeline against the H1'26 Hackathon Problem Statement). The goal is to
make the shipped deliverable (`outputs/final_access_results.csv`) conform to the grading
template, produce valid parameter values, make the Access Score span the full mandated
0–100 scale, and harden the pipeline engine — without regressing the parts of the pipeline
that already work well (step-therapy counting, retrieval, row coverage).

### Scope

In scope (9 findings, one task each):

- **P0-1** Empty-list free-text params emit blank cells instead of `NA`.
- **P0-2** Output CSV column header and order do not match the grading template.
- **P0-4** Internal sentinel (`NO BRAND MATCH FOUND`) leaked into a graded Age cell → map to `NA`; update the ADR.
- **P1-1** `ModelRouter` is not a shared singleton and its throttler is not thread-safe.
- **P1-2** Extractor `except Exception` blocks swallow errors and emit `NA`, checkpointed as success.
- **P1-5** Gemini model name is inconsistent across docs — documentation-only alignment (the model is valid; **not** a code bug).
- **P1-6** Stale checkpoint row from an older scorer → non-reproducible output and contradicted README stats.
- **P1-9** `TB Test required` and `Initial Authorization Duration` do not honor the `No`-vs-`NA` / `Unspecified` conventions.
- **P1-10** Flask UI leaks temp files and `SESSIONS` entries; the shared dict is thread-unsafe.

Explicitly **out of scope** (deferred by product decision): P0-3 (Reauthorization Required
derivation), P1-3 (validation harness), P1-4 (brand discovery), P1-7 (notebook deliverable),
P1-8 (FDA-labelled-age fallback), and all P2/P3 items.

**P0-5 (Access Score 0–100 anchors) — DEFERRED / downgraded to P2** after a focused Devil's
Advocate review (see "P0-5 decision" below). The finding's mechanical claim (ceiling ~58) is
true, but whether it is a *defect* depends on the gold-standard access-score distribution, which
is empty in `Submissions` and absent from every provided artifact. The proposed credits-track fix
is asymmetrically risky: if the gold genuinely sits ≤50 (the intended "PA only adds restrictions
vs FDA" reading), adding +50 of credits would push clean policies to 75–100 and *increase* error
against gold — and the validation harness that would detect this (P1-3) is itself deferred.
Decision: keep the current scorer; do not re-anchor. Revisit only if a gold access-score sample
or P1-3 becomes available, and then only with a smaller, symmetric (mirror-the-deductions) model.

### Environment constraint (load-bearing)

This working environment has **no LLM API key and no network access**, so the LLM extraction
pipeline cannot be re-run here. Findings therefore divide into:

- **Regenerable now** from the stored `outputs/final_access_results.json` (re-flatten and/or
  re-score, no LLM call): P0-1, P0-2, P0-4 (the leaked cell), P1-6 (re-score with the **current**
  scorer — no re-anchoring, since P0-5 is deferred).
- **Forward-fixing** code changes that take effect on the next full pipeline run and cannot be
  reflected in the shipped CSV except where derivable from stored data: P1-1, P1-2, P1-9,
  P0-4 (the source fix), P1-10.

---

## Requirement 1: Output CSV conforms to the grading template

**User story:** As a hackathon grader, I want the submission CSV to match the Submissions-tab
format exactly, so that automated per-parameter scoring aligns every column and row.

**Acceptance criteria:**

1. THE SYSTEM SHALL emit the column header `Step through-Phototherapy` (hyphenated) exactly as defined in the Submissions tab.
2. THE SYSTEM SHALL order columns so that `Quantity Limits` precedes `Specialist Types`, matching the Submissions-tab order.
3. WHEN a free-text parameter value is an empty list THE SYSTEM SHALL emit `NA` rather than an empty string.
4. THE SYSTEM SHALL keep all 79 `(Filename, Brand)` rows populated for all 15 columns after regeneration (no blank cells).
5. THE SYSTEM SHALL define the column schema in a single source of truth shared by the batch formatter and the web UI.

## Requirement 2: All emitted parameter values are valid

**User story:** As a grader, I want every cell to contain a spec-valid value, so that no internal
sentinel or wrong missing-value token costs points.

**Acceptance criteria:**

1. IF an extractor produces an internal sentinel (e.g. `NO BRAND MATCH FOUND`) THEN THE SYSTEM SHALL emit `NA` for that cell instead of the sentinel.
2. THE SYSTEM SHALL map known internal sentinels to `NA` defensively at flatten time, so regenerating the CSV corrects the shipped output.
3. WHEN a brand's PsO criteria are found but no TB test is mentioned THE SYSTEM SHALL emit `No` for `TB Test required`; WHEN no relevant context is found THE SYSTEM SHALL emit `NA`.
4. WHEN a PsO authorization/approval section exists for the brand but no explicit initial-authorization duration is stated THE SYSTEM SHALL emit `Unspecified` for `Initial Authorization Duration(in-months)` rather than `NA`.

## Requirement 3: Access Score spans the full 0–100 anchor scale — DEFERRED (P0-5)

> **DEFERRED** per the P0-5 decision above. Retained for traceability; no task implements it in
> this iteration. Revisit only with a gold access-score sample or the P1-3 validation harness, and
> then with a smaller, symmetric credits model rather than the +50 track originally proposed.

**User story:** As a grader comparing against the gold Access Score, I want scores that can reach
the full 0–100 range defined by the problem statement, so that genuinely preferred policies are
not structurally capped.

**Acceptance criteria (deferred):**

1. THE SYSTEM SHALL anchor 50 as FDA parity, 25 as restricted-vs-FDA, 0 as no access, 75 as preferred-vs-FDA, and 100 as best-possible/no-restrictions.
2. WHEN a policy applies no restrictions beyond the FDA label THE SYSTEM SHALL be able to score it at or above 75.
3. WHEN a policy is maximally restrictive THE SYSTEM SHALL be able to score it at or near 0.
4. THE SYSTEM SHALL keep scores within `[0, 100]` and assign access categories whose cutoffs align with the anchors in criterion 1.
5. THE SYSTEM SHALL preserve a per-row score breakdown for explainability.

> **Current behavior retained:** the scorer keeps 50 = FDA parity with deduction-only logic
> (reachable range ≈0–58). Requirement 4 (reproducibility) still applies and re-scores rows with
> this current scorer.

## Requirement 4: Scoring and outputs are reproducible

**User story:** As a maintainer, I want every output row to be reproducible from current code and
stored extraction results, so that the dataset is internally consistent and the README reflects
reality.

**Acceptance criteria:**

1. THE SYSTEM SHALL stamp each `access_quality` result with the scorer version that produced it.
2. WHEN the stored results are re-scored THE SYSTEM SHALL recompute every row from its stored extraction values using the current scorer, with no LLM call.
3. THE SYSTEM SHALL produce a result set in which every `access_quality` entry uses one consistent schema (no mixed legacy schemas).
4. THE SYSTEM SHALL refresh the README score-distribution statistics from the regenerated CSV so documentation matches the data.

## Requirement 5: LLM routing and rate limiting are correct under load

**User story:** As an operator running the 79-PDF batch (and the threaded web UI), I want the
rate limiter to enforce the real provider ceilings, so that the batch does not trip 429s and
corrupt its throttle accounting.

**Acceptance criteria:**

1. THE SYSTEM SHALL share a single `ModelRouter` instance across all extractors in a process.
2. WHILE multiple threads issue requests THE SYSTEM SHALL serialize throttle-window read-modify-write so the enforced rate does not exceed the configured target.
3. WHEN replacing a Groq token estimate with the actual usage THE SYSTEM SHALL update the entry created by that same call, never another call's entry.

## Requirement 6: Extraction failures are observable, not silent

**User story:** As an operator, I want a failed extraction to be distinguishable from a genuinely
empty policy, so that failed rows are retried rather than silently checkpointed as complete.

**Acceptance criteria:**

1. WHEN an extractor catches an exception THE SYSTEM SHALL mark the result with an explicit error indicator and log a warning.
2. IF any extractor for a row reports an error THEN THE SYSTEM SHALL NOT record that row as completed in the checkpoint.
3. WHEN the batch is re-run THE SYSTEM SHALL re-process rows that previously errored.

## Requirement 7: The web UI is resource-safe

**User story:** As an operator hosting the demo UI, I want uploads to never leak temp files or
session entries, so that the process is stable under repeated and abandoned uploads.

**Acceptance criteria:**

1. WHEN a client uploads a PDF but never opens the result stream THE SYSTEM SHALL eventually remove the temp file and the session entry.
2. THE SYSTEM SHALL guard all access to the shared session store with a lock.
3. THE SYSTEM SHALL bound session lifetime with a TTL and sweep expired sessions.

## Requirement 8: Documentation is accurate

**User story:** As a reviewer following the README, I want documented model names and decisions
to match the code, so that the provider paths work and decisions are traceable.

**Acceptance criteria:**

1. THE SYSTEM SHALL document the Gemini model name consistently across `README.md` and `.env.example` to match the name used in `utils/model_router.py`.
2. THE SYSTEM SHALL record an ADR entry stating that internal sentinels are mapped to `NA` in the output (supports Requirement 2).
