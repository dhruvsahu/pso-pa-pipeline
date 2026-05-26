import json
import pandas as pd

class AccessQualityScorer:

    def __init__(self):

        # =================================================
        # FDA BASELINE PROFILES
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

        score = 100

        deductions = []

        # -------------------------------------------------
        # LOAD FDA BASELINE
        # -------------------------------------------------

        baseline = self.fda_baselines.get(

            brand.upper(),

            {}
        )

        # =================================================
        # STEP THERAPY PENALTIES
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

        # extractor returns phototherapy_required ("Yes"/"No"/"NA"),
        # not a count — convert to 0 or 1
        phototherapy_steps = (
            1
            if step_therapy_result.get(
                "phototherapy_required"
            ) == "Yes"
            else 0
        )

        total_steps = (
            brand_steps
            + generic_steps
            + phototherapy_steps
        )

        if total_steps >= 5:

            score -= 40

            deductions.append(
                "Very high step therapy burden"
            )

        elif total_steps >= 3:

            score -= 25

            deductions.append(
                "High step therapy burden"
            )

        elif total_steps >= 1:

            score -= 10

            deductions.append(
                "Moderate step therapy burden"
            )

        # =================================================
        # SPECIALIST RESTRICTIONS
        # =================================================

        specialists = (
            clinical_access_result.get(
                "specialist_types",
                []
            )
        )

        if (
            isinstance(specialists, list)
            and len(specialists) > 0
        ):

            score -= 10

            deductions.append(
                "Specialist restriction applied"
            )

        # =================================================
        # PRECERTIFICATION
        # =================================================

        if clinical_access_result.get(
            "precertification_required"
        ) == "Yes":

            score -= 10

            deductions.append(
                "Precertification required"
            )

        # =================================================
        # REAUTHORIZATION
        # =================================================

        if authorization_result.get(
            "reauthorization_required"
        ) == "Yes":

            score -= 5

            deductions.append(
                "Reauthorization required"
            )

        # =================================================
        # QUANTITY LIMITS
        # =================================================

        quantity_limits = (
            utilization_result.get(
                "quantity_limits",
                []
            )
        )

        if (
            isinstance(quantity_limits, list)
            and len(quantity_limits) > 0
        ):

            score -= 5

            deductions.append(
                "Quantity limits applied"
            )

        # =================================================
        # AGE RESTRICTIONS
        # =================================================

        age_value = age_result.get(
            "value"
        )

        if (
            age_value
            and age_value not in (
                "ALL",
                "NA",
                "No Age Restriction"
            )
        ):

            score -= 5

            deductions.append(
                "Age restriction applied"
            )

        # =================================================
        # SCORE FLOOR / CEILING
        # =================================================

        score = max(
            0,
            min(score, 100)
        )

        # =================================================
        # ACCESS CATEGORY
        # =================================================

        if score <= 25:

            category = (
                "Highly Restricted"
            )

        elif score <= 50:

            category = (
                "Restricted Access"
            )

        elif score <= 75:

            category = (
                "FDA Parity"
            )

        else:

            category = (
                "Preferred Access"
            )

        # =================================================
        # FDA ALIGNMENT
        # =================================================

        if total_steps >= 3:

            fda_alignment = (
                "More restrictive than FDA label"
            )

        elif total_steps == 0:

            fda_alignment = (
                "Favorable relative to FDA label"
            )

        else:

            fda_alignment = (
                "Near FDA parity"
            )

        # =================================================
        # FINAL OUTPUT
        # =================================================

        return {

            "brand": brand,

            "access_quality_score": score,

            "access_category": category,

            "fda_alignment": fda_alignment,

            "score_breakdown": deductions
        }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    scorer = AccessQualityScorer()

    step_therapy_result = {

        "brand_steps": 3,

        "generic_steps": 1,

        "phototherapy_steps": 1
    }

    authorization_result = {

        "reauthorization_required": True
    }

    utilization_result = {

        "quantity_limits": [
            "1 vial every 8 weeks"
        ]
    }

    clinical_access_result = {

        "specialist_types": [
            "dermatologist"
        ],

        "precertification_required": True
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

    print(
        json.dumps(
            result,
            indent=2
        )
    )