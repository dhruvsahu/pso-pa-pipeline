# Output Parameters

## PsO Prior Authorization Access Quality Pipeline

This document explains every column in the pipeline's output CSV (`outputs/final_access_results.csv` for batch, `outputs/results.csv` for the UI). Column names and order match the `PA_Business_Rules.xlsx` Submissions tab exactly.

---

## Column Reference

### 1. Filename

| Attribute | Value |
|-----------|-------|
| **Type** | String |
| **Source** | Input (`sample_batch.csv` for batch; uploaded file for UI) |
| **Example** | `148593-4960549.pdf` |

The PDF filename being analysed. In batch mode this comes from `sample_batch.csv`; in the UI it is the original name of the uploaded file.

---

### 2. Brand

| Attribute | Value |
|-----------|-------|
| **Type** | String (uppercase) |
| **Source** | Input (`sample_batch.csv` for batch; dropdown selection for UI) |
| **Example** | `STELARA`, `TREMFYA`, `SKYRIZI` |

The target drug brand being evaluated against the policy. Some PDFs contain criteria for multiple brands, producing one row per brand.

---

### 3. Age

| Attribute | Value |
|-----------|-------|
| **Type** | String |
| **Extractor** | `AgeExtractor` |
| **Valid values** | `>=N` (e.g. `>=6`, `>=18`), `NA` |
| **Example** | `>=12` |

The minimum patient age required by the payer's policy for this brand in the plaque psoriasis (PsO) indication. The extractor normalises natural language to a `>=N` format (e.g. "6 years of age or older" becomes `>=6`, "adult patients" becomes `>=18`).

- `>=6` means patients must be 6 years or older
- `NA` means no age criterion was found in the retrieved policy pages

The scorer compares this against the FDA label's minimum age for the brand. A more restrictive age (higher threshold than FDA) deducts -5; a less restrictive age (lower threshold) earns +5.

---

### 4. Step Therapy Requirements Documented in Policy

| Attribute | Value |
|-----------|-------|
| **Type** | Free text (semicolon-separated) |
| **Extractor** | `StepTherapyExtractor` |
| **Valid values** | Descriptive text, `NA` |
| **Example** | `Member must have tried methotrexate for 3 months; Member must have failed one biologic DMARD` |

A human-readable summary of all step therapy (prior treatment) requirements the payer mandates before approving the target drug. Multiple requirements are joined with `; `. This is the qualitative description; the quantitative counts are in the next three columns.

- `NA` means no step therapy requirements were found

---

### 5. Number of Steps through Brands

| Attribute | Value |
|-----------|-------|
| **Type** | Integer or `NA` |
| **Extractor** | `StepTherapyExtractor` |
| **Valid values** | `0`, `1`, `2`, `3`, `NA` |
| **Example** | `1` |

The number of distinct branded drug trials ("brand steps") the payer requires before the target drug can be approved. Computed deterministically as `len(brand_step_slots)` from the LLM's structured output.

- `0` means no branded drug steps are required (confirmed)
- `1` means one branded drug trial must be attempted and failed
- `NA` means the extractor could not determine the count

The slot model ensures OR-alternatives count as one step (e.g. "fail Ilumya OR Stelara" = 1 step, not 2), and intolerance cascades count as one step with alternatives.

Each brand step deducts -10 from the access score (capped at -30).

---

### 6. Number of Steps through Generic

| Attribute | Value |
|-----------|-------|
| **Type** | Integer or `NA` |
| **Extractor** | `StepTherapyExtractor` |
| **Valid values** | `0`, `1`, `2`, `3`, `NA` |
| **Example** | `1` |

The number of distinct generic/conventional therapy trials the payer requires. Includes non-biologic systemics (methotrexate, cyclosporine, acitretin) and non-branded treatments.

- `0` means no generic steps are required (confirmed)
- `NA` means the extractor could not determine the count

Each generic step deducts -5 from the access score (capped at -15).

---

### 7. Step through-Phototherapy

| Attribute | Value |
|-----------|-------|
| **Type** | String |
| **Extractor** | `StepTherapyExtractor` |
| **Valid values** | `Yes`, `No`, `NA` |
| **Example** | `No` |

Whether the payer requires a trial of phototherapy (UVB, PUVA, etc.) as a mandatory standalone step before approving the target drug.

- `Yes` means phototherapy is required as a step (deducts -5)
- `No` means phototherapy is not required as a step (confirmed; earns +2 credit)
- `NA` means the extractor could not determine the requirement

Phototherapy offered as one choice within an OR-alternative (e.g. "methotrexate OR phototherapy") does not count as a mandatory standalone step.

---

### 8. TB Test required

| Attribute | Value |
|-----------|-------|
| **Type** | String |
| **Extractor** | `ClinicalAccessExtractor` |
| **Valid values** | `Yes`, `No`, `NA` |
| **Example** | `No` |

Whether the payer requires tuberculosis (TB) testing or screening before approving the target drug.

- `Yes` means TB testing is explicitly required
- `No` means criteria were found but TB testing is not mentioned or not required
- `NA` means no clinical access criteria were found at all

The distinction between `No` and `NA` matters for scoring: if the FDA label expects a TB test (e.g. for biologics like STELARA) and the payer waives it (`No`), the policy earns a +3 "TB test waived" credit. If the payer requires it where the FDA does not, it deducts -3.

---

### 9. Quantity Limits

| Attribute | Value |
|-----------|-------|
| **Type** | Free text (semicolon-separated) or `NA` |
| **Extractor** | `UtilizationManagementExtractor` |
| **Valid values** | Descriptive text, `NA` |
| **Example** | `1 syringe per 28 days` |

Quantity limits imposed by the payer on the target drug. Only captures restrictions explicitly labelled as "quantity limit" in the policy; "dosing limit" sections are excluded per the business rules.

- Specific limit text means a quantity restriction is in place (deducts -5)
- An empty result (no QL found) is reported as `NA`

A confirmed empty list (no quantity limits found despite criteria being present) earns a +2 confirmed-open credit.

---

### 10. Specialist Types

| Attribute | Value |
|-----------|-------|
| **Type** | Free text (comma-separated) or `NA` |
| **Extractor** | `ClinicalAccessExtractor` |
| **Valid values** | List of specialties, `NA` |
| **Example** | `dermatologist`, `dermatologist, rheumatologist` |

The medical specialties the payer requires for prescribing or managing treatment with the target drug. Only explicit specialist restrictions are captured; inferred specialties are not included.

- One or more specialties listed means a specialist restriction exists (deducts -8)
- A confirmed empty list (criteria found, no specialist restriction) earns a +2 credit
- `NA` means no usable specialist evidence was found

---

### 11. Initial Authorization Duration(in-months)

| Attribute | Value |
|-----------|-------|
| **Type** | Integer, `Unspecified`, or `NA` |
| **Extractor** | `AuthorizationExtractor` |
| **Valid values** | Numeric months (e.g. `3`, `6`, `12`), `Unspecified`, `NA` |
| **Example** | `6` |

How long the initial prior authorization approval lasts before requiring renewal.

- A numeric value (e.g. `6`) means the policy specifies a 6-month initial authorization
- `Unspecified` means the policy has a prior authorization section but does not state a specific duration
- `NA` means no authorization section was found in the policy

The distinction between `Unspecified` and `NA` is intentional: when a PA section exists, the business rules require a duration or "Unspecified", not "NA".

---

### 12. Reauthorization Duration(in-months)

| Attribute | Value |
|-----------|-------|
| **Type** | Integer, `Unspecified`, or `NA` |
| **Extractor** | `AuthorizationExtractor` |
| **Valid values** | Numeric months (e.g. `6`, `12`), `Unspecified`, `NA` |
| **Example** | `12` |

How long each reauthorization approval lasts once the initial authorization expires.

- A numeric value (e.g. `12`) means each reauthorization covers 12 months
- `Unspecified` means reauthorization exists but the duration is not stated
- `NA` means no reauthorization information was found

---

### 13. Reauthorization Required

| Attribute | Value |
|-----------|-------|
| **Type** | String |
| **Source** | Derived deterministically from columns 12 and 14 |
| **Valid values** | `Yes`, `No` |
| **Example** | `Yes` |

Whether the payer requires reauthorization for continued therapy. This is a **derived** column, not directly extracted by the LLM. The business rule is:

> If either Reauthorization Duration or Reauthorization Requirements is non-NA, then this column is "Yes"; otherwise "No".

This ensures the column is always `Yes` or `No` (never `NA`), even when the individual authorization fields may be `NA`.

- `Yes` deducts -5 from the access score (restriction beyond FDA)
- `No` earns a +2 confirmed-open credit

---

### 14. Reauthorization Requirements Documented in Policy

| Attribute | Value |
|-----------|-------|
| **Type** | Free text (semicolon-separated) or `NA` |
| **Extractor** | `AuthorizationExtractor` |
| **Valid values** | Descriptive text, `NA` |
| **Example** | `The member has had a positive response to therapy; Documentation of clinical justification to continue therapy` |

The specific criteria the payer requires for reauthorization approval. Multiple requirements are joined with `; `.

- `NA` means no reauthorization requirements were found in the policy

---

### 15. Access Score

| Attribute | Value |
|-----------|-------|
| **Type** | Integer (0-100) |
| **Source** | `AccessQualityScorer` (v2.2) |
| **Valid values** | `0` to `100` |
| **Example** | `32` |

A composite score measuring the payer policy's access burden relative to the FDA prescribing label. The score starts at **50 (FDA parity baseline)** and is adjusted by deductions and credits based on the extracted parameters above.

**How it works (scorer v2.2):**

Each axis is **tri-state**:
- **Restriction present** (beyond FDA) -> deduction (score moves toward 0)
- **Confirmed absent** (explicit "No" / empty list / confirmed 0) -> small +2 credit
- **Unknown** (`NA` / missing) -> neutral (no change)

Two terms that are strictly more permissive than the FDA label earn larger credits: age less restrictive than FDA (+5) and TB test waived where FDA expects it (+3).

**Access categories:**

| Score Range | Category | Meaning |
|-------------|----------|---------|
| 75-100 | Preferred Access | More permissive than FDA (not reachable for this dataset) |
| 50-74 | FDA Parity | At or near FDA label terms |
| 25-49 | Restricted Access | Moderately more restrictive than FDA |
| 0-24 | Highly Restricted | Significantly more restrictive than FDA |

**Observed distribution (79 policies, scorer v2.2):** range 12-52, average 31.8, median 32. Category split: 23 Highly Restricted, 52 Restricted Access, 4 FDA Parity, 0 Preferred Access.

---

## Output Value Conventions

| Value | Meaning |
|-------|---------|
| `NA` | No data could be extracted for this parameter (unknown) |
| `No` | The restriction was looked for and confirmed absent |
| `Unspecified` | The relevant policy section exists but does not state a specific value |
| `Yes` | The restriction or requirement is explicitly present |

These distinctions are important for scoring:
- `NA` (unknown) is **neutral** and does not affect the score
- `No` (confirmed absent) may earn a small +2 confirmed-open credit
- `Yes` (present) typically triggers a deduction

---

## Worked Examples

### Highly Restricted (Score 12)

**247339-4770410.pdf / OTULFI**

| Parameter | Value | Score Impact |
|-----------|-------|-------------|
| Age | >=6 | (matches FDA — neutral) |
| Brand Steps | 3 | -30 (3 steps, capped) |
| Generic Steps | NA | neutral |
| Phototherapy | No | +2 (confirmed absent) |
| TB Test | No | +3 (waived; FDA expects it) |
| Specialist | dermatologist, rheumatologist | -8 |
| Quantity Limits | NA | neutral |
| Reauthorization | Yes | -5 |
| **Total** | | **50 - 30 - 8 - 5 + 2 + 3 = 12** |

### Restricted Access (Score 32)

**315085-4653251.pdf / OTEZLA**

| Parameter | Value | Score Impact |
|-----------|-------|-------------|
| Age | NA | neutral |
| Brand Steps | 1 | -10 |
| Generic Steps | 1 | -5 |
| Phototherapy | No | +2 (confirmed absent) |
| TB Test | No | (FDA does not expect TB for OTEZLA — neutral) |
| Specialist | NA | neutral |
| Quantity Limits | NA | neutral |
| Reauthorization | Yes | -5 |
| **Total** | | **50 - 10 - 5 - 5 + 2 = 32** |

### FDA Parity (Score 52)

**195158-4643510.pdf / SKYRIZI**

| Parameter | Value | Score Impact |
|-----------|-------|-------------|
| Age | NA | neutral |
| Brand Steps | NA | neutral |
| Generic Steps | 1 | -5 |
| Phototherapy | No | +2 (confirmed absent) |
| TB Test | No | +3 (waived; FDA expects it) |
| Specialist | NA | neutral |
| Quantity Limits | NA | neutral |
| Reauthorization | No | +2 (confirmed absent) |
| **Total** | | **50 - 5 + 2 + 3 + 2 = 52** |
