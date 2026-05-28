import json
import pandas as pd


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
        Parse an age string like '>=6', '>=18', '>=4'
        into an integer.  Returns None if unparseable.
        """
        if not age_str or str(age_str).strip() in ("NA", ""):
            return None

        s = str(age_str).strip().replace(">=", "").replace(">", "").strip()

        try:
            return int(s)
        except ValueError:
            return None

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
        bonuses = []

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
        phototherapy_required = (
            step_therapy_result.get(
                "phototherapy_required"
            ) == "Yes"
        )

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

        if (
            isinstance(specialists, list)
            and len(specialists) > 0
            and fda_specialist == "No"
        ):
            score -= 8
            deductions.append(
                "Specialist restriction "
                "not in FDA label (-8)"
            )

        # =================================================
        # REAUTHORIZATION
        # FDA baseline: reauthorization_expected = "No"
        # Penalty: -5 if payer requires reauth
        # =================================================

        reauth = authorization_result.get(
            "reauthorization_required"
        )

        fda_reauth = str(
            baseline.get("reauthorization_expected", "No")
        ).strip()

        if reauth == "Yes" and fda_reauth == "No":
            score -= 5
            deductions.append(
                "Reauthorization not in FDA label (-5)"
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

        if (
            isinstance(quantity_limits, list)
            and len(quantity_limits) > 0
            and fda_ql == "No"
        ):
            score -= 5
            deductions.append(
                "Quantity limits not in FDA label (-5)"
            )

        # =================================================
        # TB TEST
        # FDA baseline: tb_test_expected ("Yes" / "No")
        # If FDA says No and payer requires TB → -3
        # If FDA says Yes and payer does NOT require → +3
        # =================================================

        tb_required = clinical_access_result.get(
            "tb_test_required"
        )

        fda_tb = str(
            baseline.get("tb_test_expected", "NA")
        ).strip()

        if fda_tb == "No" and tb_required == "Yes":
            score -= 3
            deductions.append(
                "TB test required; not expected per "
                "FDA label (-3)"
            )
        elif fda_tb == "Yes" and tb_required == "No":
            score += 3
            bonuses.append(
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

        payer_min_age = self._parse_min_age(age_value)

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
                bonuses.append(
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
        # =================================================

        total_steps = (
            brand_steps
            + generic_steps
            + (1 if phototherapy_required else 0)
        )

        if total_steps >= 3 or score < 40:
            fda_alignment = (
                "More restrictive than FDA label"
            )

        elif score > 55 or (
            total_steps == 0
            and not deductions
        ):
            fda_alignment = (
                "Favorable relative to FDA label"
            )

        else:
            fda_alignment = "Near FDA parity"

        # =================================================
        # FINAL OUTPUT
        # =================================================

        return {

            "brand": brand,

            "access_quality_score": score,

            "access_category": category,

            "fda_alignment": fda_alignment,

            "score_breakdown": {
                "deductions": deductions,
                "bonuses": bonuses
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
