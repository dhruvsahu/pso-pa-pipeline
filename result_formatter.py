import json
import pandas as pd
import os


# =========================================================
# LOAD RESULTS
# =========================================================

with open(

    "outputs/final_access_results.json",

    "r",

    encoding="utf-8"

) as f:

    results = json.load(f)

# =========================================================
# FLATTEN RESULTS
# =========================================================

rows = []

for result in results:

    row = {

        # -------------------------------------------------
        # BASIC INFO
        # -------------------------------------------------

        "Filename":

            result.get(
                "filename"
            ),

        "Brand":

            result.get(
                "brand"
            ),

        # -------------------------------------------------
        # AGE
        # -------------------------------------------------

        "Age":

            result.get(
                "age",
                {}
            ).get(
                "value"
            ),

        # -------------------------------------------------
        # STEP THERAPY
        # -------------------------------------------------

        "Step Therapy Requirements Documented in Policy":

            (
                result.get(
                    "step_therapy",
                    {}
                ).get(
                    "brand_steps"
                ) != "NA"
            ),

        "Number of Steps through Brands":

            result.get(
                "step_therapy",
                {}
            ).get(
                "brand_steps"
            ),

        "Number of Steps through Generic":

            result.get(
                "step_therapy",
                {}
            ).get(
                "generic_steps"
            ),

        "Step through Phototherapy":

            result.get(
                "step_therapy",
                {}
            ).get(
                "phototherapy_required"
            ),

        # -------------------------------------------------
        # CLINICAL ACCESS
        # -------------------------------------------------

        "TB Test required":

            result.get(
                "clinical_access",
                {}
            ).get(
                "tb_test_required"
            ),

        "Specialist Types":

            (
                ", ".join(

                    result.get(
                        "clinical_access",
                        {}
                    ).get(
                        "specialist_types",
                        []
                    )

                )

                if isinstance(

                    result.get(
                        "clinical_access",
                        {}
                    ).get(
                        "specialist_types",
                        []
                    ),

                    list
                )

                else

                result.get(
                    "clinical_access",
                    {}
                ).get(
                    "specialist_types",
                    "NA"
                )
            ),

        # -------------------------------------------------
        # UTILIZATION
        # -------------------------------------------------

        "Quantity Limits":

            "; ".join(

                result.get(
                    "utilization_management",
                    {}
                ).get(
                    "quantity_limits",
                    []
                )
            ),

        # -------------------------------------------------
        # AUTHORIZATION
        # -------------------------------------------------

        "Initial Authorization Duration(in-months)":

            result.get(
                "authorization",
                {}
            ).get(
                "initial_authorization_months"
            ),

        "Reauthorization Duration(in-months)":

            result.get(
                "authorization",
                {}
            ).get(
                "reauthorization_duration_months"
            ),

        "Reauthorization Required":

            result.get(
                "authorization",
                {}
            ).get(
                "reauthorization_required"
            ),

        "Reauthorization Requirements Documented in Policy":

            len(

                result.get(
                    "authorization",
                    {}
                ).get(
                    "reauthorization_requirements",
                    []
                )
            ) > 0,

        # -------------------------------------------------
        # ACCESS SCORE
        # -------------------------------------------------

        "Access Score":

            result.get(
                "access_quality",
                {}
            ).get(
                "access_quality_score"
            )
    }

    rows.append(row)

# =========================================================
# CREATE DATAFRAME
# =========================================================

df = pd.DataFrame(
    rows
)

# =========================================================
# CREATE OUTPUT DIRECTORY
# =========================================================

os.makedirs(
    "outputs",
    exist_ok=True
)

# =========================================================
# SAVE CSV
# =========================================================

df.to_csv(

    "outputs/final_access_results.csv",

    index=False
)

# =========================================================
# SAVE EXCEL
# =========================================================

df.to_excel(

    "outputs/final_access_results.xlsx",

    index=False
)

print("\n" + "=" * 80)
print("RESULT FORMATTING COMPLETE")
print("=" * 80)

print(
    df.head()
)