import json
import re
import pandas as pd


# Version of the scoring model. Stamped onto every access_quality result so
# rows produced by an older scorer (e.g. the legacy flat-list breakdown that
# scored a STELARA row at 70) are identifiable and can be re-scored. Bump this
# whenever the scoring logic or weights change.
# 2.0 = two-sided "credit-for-absence" model (WITHDRAWN — it scored missing
#       data as "no restriction" and inflated parity policies; see ADR-016).
# 2.1 = Option A: deductions for restrictions beyond FDA; credits ONLY for
#       strictly better-than-FDA terms (age-younger +5, TB-waived +3).
# 2.2 = adds a SMALL confirmed-only credit (+2) per axis that the policy
#       VERIFIES is unrestricted (explicit "No" / empty list / confirmed 0) —
#       never on "NA". Distinguishes a verified-open policy from an unextracted
#       one while keeping missing data neutral (50). Tri-state per axis:
#       present → deduct, confirmed-absent → +2, unknown("NA") → neutral.
#       Ceiling ~68 (still < 75 → "Preferred" remains unreachable).
SCORER_VERSION = "2.2"


class AccessQualityScorer:

    def __init__(self):

        # =================================================
        # FDA BASELINE PROFILES
        # Source: FDA prescribing information, PsO indication
        # =================================================

        baseline_df = pd.read_csv(
            "assets/fda_baselines.csv"
        )

        self.fda_baselines = {}

        for _, row in baseline_df.iterrows():

            brand = row["brand"]

            self.fda_baselines[brand] = {

                "minimum_age":
                    row["minimum_age"],

                "tb_test_expected":
                    row["tb_test_expected"],

                "specialist_required":
                    row["specialist_required"],

                "quantity_limit_expected":
                    row["quantity_limit_expected"],

                "step_therapy_expected":
                    row["step_therapy_expected"],

                "reauthorization_expected":
                    row["reauthorization_expected"],

                "preferred_indication":
                    row["preferred_indication"]
            }

    # =====================================================
    # HELPERS
    # =====================================================

    def _parse_min_age(self, age_str):
        """
        Parse a minimum-age string into an integer threshold.

        Handles values with extra text ('6 years', '>=6 years') by
        extracting the first integer. Returns None for non-numeric
        tokens ('NA', '', 'FDA labelled age', 'No Age Restriction').

        Note: '>' and '>=' both map to the same integer threshold; the
        more/less-restrictive comparison treats them identically.
        """
        if age_str is None:
            return None

        s = str(age_str).strip()

        if s.upper() in ("NA", "") or s in (
            "FDA labelled age",
            "No Age Restriction",
        ):
            return None

        m = re.search(r"\d+", s)
        return int(m.group()) if m else None

    # =====================================================
    # ACCESS SCORING
    # =====================================================

    def calculate_score(

        self,

        brand,

        step_therapy_result,

        authorization_result,

        utilization_result,

        clinical_access_result,

        age_result
    ):

        # -------------------------------------------------
        # START AT 50 — FDA PARITY BASELINE
        # -------------------------------------------------

        score = 50

        deductions = []
        credits = []

        # -------------------------------------------------
        # LOAD FDA BASELINE
        # -------------------------------------------------

        baseline = self.fda_baselines.get(
            brand.upper(),
            {}
        )

        # =================================================
        # STEP THERAPY PENALTIES
        # -10 per brand step (cap -30)
        # -5  per generic step (cap -15)
        # -5  if phototherapy required
        # FDA baseline: step_therapy_expected = "No"
        # (no payer step therapy is FDA-aligned)
        # =================================================

        _brand_steps = step_therapy_result.get("brand_steps", 0)
        brand_steps = (
            int(_brand_steps)
            if str(_brand_steps).lstrip("-").isdigit()
            else 0
        )

        _generic_steps = step_therapy_result.get("generic_steps", 0)
        generic_steps = (
            int(_generic_steps)
            if str(_generic_steps).lstrip("-").isdigit()
            else 0
        )

        # extractor returns phototherapy_required
        # ("Yes" / "No" / "NA"), not a count
        _photo = step_therapy_result.get("phototherapy_required")
        phototherapy_required = (_photo == "Yes")

        brand_step_penalty = min(brand_steps * 10, 30)
        generic_step_penalty = min(generic_steps * 5, 15)
        photo_penalty = 5 if phototherapy_required else 0

        total_step_penalty = (
            brand_step_penalty
            + generic_step_penalty
            + photo_penalty
        )

        if brand_step_penalty > 0:
            score -= brand_step_penalty
            deductions.append(
                f"Brand step therapy: "
                f"{brand_steps} step(s) "
                f"(-{brand_step_penalty})"
            )

        if generic_step_penalty > 0:
            score -= generic_step_penalty
            deductions.append(
                f"Generic step therapy: "
                f"{generic_steps} step(s) "
                f"(-{generic_step_penalty})"
            )

        if photo_penalty > 0:
            score -= photo_penalty
            deductions.append(
                f"Phototherapy required "
                f"(-{photo_penalty})"
            )

        # ----- CONFIRMED-OPEN CREDITS (v2.2) -----
        # +2 when the policy VERIFIES no restriction on an axis (confirmed 0 /
        # explicit "No" / empty list) — NEVER on "NA". Keeps missing data
        # neutral (50) while distinguishing a verified-open policy from an
        # unextracted one. Strictly-better-than-FDA terms (age/TB) are scored
        # separately below at +5/+3.

        # Confirmed no step therapy: BOTH counts present and numeric and 0.
        _brand_confirmed = str(_brand_steps).lstrip("-").isdigit()
        _generic_confirmed = str(_generic_steps).lstrip("-").isdigit()
        if (
            _brand_confirmed and _generic_confirmed
            and brand_steps == 0 and generic_steps == 0
        ):
            score += 2
            credits.append("No step therapy (confirmed) (+2)")

        # Confirmed no phototherapy step (explicit "No", not "NA").
        if str(_photo).strip().lower() == "no":
            score += 2
            credits.append("No phototherapy step (confirmed) (+2)")

        # =================================================
        # SPECIALIST RESTRICTIONS
        # FDA baseline: specialist_required = "No"
        # Penalty: -8 if payer requires specialist
        # No bonus — FDA baseline already = No
        # =================================================

        specialists = (
            clinical_access_result.get(
                "specialist_types",
                []
            )
        )

        fda_specialist = str(
            baseline.get("specialist_required", "No")
        ).strip()

        payer_has_specialist = (
            isinstance(specialists, list)
            and len(specialists) > 0
        )

        if payer_has_specialist and fda_specialist == "No":
            score -= 8
            deductions.append(
                "Specialist restriction "
                "not in FDA label (-8)"
            )
        elif isinstance(specialists, list) and len(specialists) == 0:
            # Confirmed empty list = verified no specialist restriction.
            score += 2
            credits.append(
                "No specialist restriction (confirmed) (+2)"
            )

        # =================================================
        # REAUTHORIZATION
        # FDA baseline: reauthorization_expected = "No"
        # Penalty: -5 if payer requires reauth
        # =================================================

        reauth = authorization_result.get(
            "reauthorization_required"
        )

        # Normalize so a casing drift ("yes"/"Yes") can't flip the sign.
        reauth_norm = str(reauth).strip().lower()
        reauth_required = (reauth_norm == "yes")

        fda_reauth = str(
            baseline.get("reauthorization_expected", "No")
        ).strip()

        if reauth_required and fda_reauth == "No":
            score -= 5
            deductions.append(
                "Reauthorization not in FDA label (-5)"
            )
        elif reauth_norm == "no":
            # Confirmed no reauthorization required (explicit "No", not "NA").
            score += 2
            credits.append(
                "No reauthorization required (confirmed) (+2)"
            )

        # =================================================
        # QUANTITY LIMITS
        # FDA baseline: quantity_limit_expected = "No"
        # Penalty: -5 if payer imposes QL
        # =================================================

        quantity_limits = (
            utilization_result.get(
                "quantity_limits",
                []
            )
        )

        fda_ql = str(
            baseline.get("quantity_limit_expected", "No")
        ).strip()

        payer_has_ql = (
            isinstance(quantity_limits, list)
            and len(quantity_limits) > 0
        )

        if payer_has_ql and fda_ql == "No":
            score -= 5
            deductions.append(
                "Quantity limits not in FDA label (-5)"
            )
        elif isinstance(quantity_limits, list) and len(quantity_limits) == 0:
            # Confirmed empty list = verified no quantity limit.
            score += 2
            credits.append(
                "No quantity limit (confirmed) (+2)"
            )

        # =================================================
        # TB TEST
        # FDA baseline: tb_test_expected ("Yes" / "No")
        # If FDA says No and payer requires TB → -3
        # If FDA says Yes and payer does NOT require → +3
        # =================================================

        # Normalize casing on both sides (consistency with the reauth fix).
        tb_norm = str(
            clinical_access_result.get("tb_test_required")
        ).strip().lower()

        fda_tb = str(
            baseline.get("tb_test_expected", "NA")
        ).strip()
        fda_tb_norm = fda_tb.lower()

        if fda_tb_norm == "no" and tb_norm == "yes":
            score -= 3
            deductions.append(
                "TB test required; not expected per "
                "FDA label (-3)"
            )
        elif fda_tb_norm == "yes" and tb_norm == "no":
            score += 3
            credits.append(
                "TB test waived vs FDA label (+3)"
            )

        # =================================================
        # AGE RESTRICTIONS
        # FDA baseline: minimum_age (e.g. ">=6")
        # Compare payer restriction vs FDA threshold.
        # If payer is MORE restrictive than FDA → -5
        # If payer is LESS restrictive than FDA → +5
        # =================================================

        age_value = age_result.get("value")

        fda_age_str = baseline.get("minimum_age", "")
        fda_min_age = self._parse_min_age(fda_age_str)

        # A "<N" / "under N" / "up to N" value is an UPPER bound (e.g. a
        # pediatric/max-age clause), not a minimum-age threshold. Comparing it
        # as a minimum is meaningless (and produced a contradictory
        # "payer <18 vs FDA >=4 (-5)" message), so skip the age comparison.
        _age_str = str(age_value).strip().lower() if age_value is not None else ""
        age_is_upper_bound = (
            _age_str.startswith("<")
            or _age_str.startswith("under")
            or _age_str.startswith("up to")
        )

        payer_min_age = (
            None if age_is_upper_bound
            else self._parse_min_age(age_value)
        )

        if fda_min_age is not None and payer_min_age is not None:

            if payer_min_age > fda_min_age:
                score -= 5
                deductions.append(
                    f"Age restriction more restrictive "
                    f"than FDA label "
                    f"(payer {age_value} vs FDA "
                    f"{fda_age_str}) (-5)"
                )

            elif payer_min_age < fda_min_age:
                score += 5
                credits.append(
                    f"Age restriction less restrictive "
                    f"than FDA label "
                    f"(payer {age_value} vs FDA "
                    f"{fda_age_str}) (+5)"
                )

        elif (
            age_value
            and str(age_value).strip() not in (
                "ALL",
                "NA",
                "No Age Restriction",
                ""
            )
            and fda_min_age is None
        ):
            # Payer restricts age but FDA has no known
            # minimum for this brand — minor penalty
            score -= 5
            deductions.append(
                f"Age restriction applied; no FDA "
                f"baseline available (-5)"
            )

        # =================================================
        # SCORE FLOOR / CEILING
        # =================================================

        score = max(0, min(score, 100))

        # =================================================
        # ACCESS CATEGORY
        # Anchors aligned to problem statement:
        #   0  – 25  → Highly Restricted
        #   25 – 50  → Restricted Access
        #   50 – 75  → FDA Parity
        #   75 – 100 → Preferred Access
        # =================================================

        if score < 25:
            category = "Highly Restricted"

        elif score < 50:
            category = "Restricted Access"

        elif score < 75:
            category = "FDA Parity"

        else:
            category = "Preferred Access"

        # =================================================
        # FDA ALIGNMENT
        # Derived from the SAME score bands as `category`
        # (single source of truth) so the two can never
        # disagree:
        #   < 50      → More restrictive than FDA label
        #   50 – 75   → Near FDA parity
        #   >= 75     → Favorable relative to FDA label
        # =================================================

        if score < 50:
            fda_alignment = (
                "More restrictive than FDA label"
            )

        elif score < 75:
            fda_alignment = "Near FDA parity"

        else:
            fda_alignment = (
                "Favorable relative to FDA label"
            )

        # =================================================
        # FINAL OUTPUT
        # =================================================

        return {

            "brand": brand,

            "access_quality_score": score,

            "access_category": category,

            "fda_alignment": fda_alignment,

            "scorer_version": SCORER_VERSION,

            "score_breakdown": {
                "deductions": deductions,
                "credits": credits
            }
        }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    scorer = AccessQualityScorer()

    # -------------------------------------------
    # Heavily restricted plan (STELARA)
    # -------------------------------------------
    step_therapy_result = {
        "brand_steps": 2,
        "generic_steps": 1,
        "phototherapy_required": "Yes"
    }

    authorization_result = {
        "reauthorization_required": "Yes"
    }

    utilization_result = {
        "quantity_limits": [
            "1 vial every 8 weeks"
        ]
    }

    clinical_access_result = {
        "specialist_types": ["dermatologist"],
        "precertification_required": "Yes",
        "tb_test_required": "Yes"
    }

    age_result = {
        "value": ">=18"
    }

    result = scorer.calculate_score(

        brand="STELARA",

        step_therapy_result=(
            step_therapy_result
        ),

        authorization_result=(
            authorization_result
        ),

        utilization_result=(
            utilization_result
        ),

        clinical_access_result=(
            clinical_access_result
        ),

        age_result=(
            age_result
        )
    )

    print("--- Heavily Restricted Plan ---")
    print(
        json.dumps(
            result,
            indent=2
        )
    )

    # -------------------------------------------
    # Clean / preferred access plan (STELARA)
    # -------------------------------------------
    result2 = scorer.calculate_score(

        brand="STELARA",

        step_therapy_result={
            "brand_steps": 0,
            "generic_steps": 0,
            "phototherapy_required": "No"
        },

        authorization_result={
            "reauthorization_required": "No"
        },

        utilization_result={
            "quantity_limits": []
        },

        clinical_access_result={
            "specialist_types": [],
            "precertification_required": "No",
            "tb_test_required": "Yes"
        },

        age_result={
            "value": ">=6"
        }
    )

    print("\n--- Preferred Access Plan ---")
    print(
        json.dumps(
            result2,
            indent=2
        )
    )
