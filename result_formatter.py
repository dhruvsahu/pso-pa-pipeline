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
                "; ".join(
                    result.get(
                        "step_therapy",
                        {}
                    ).get(
                        "step_therapy_requirements",
                        []
                    )
                )
                if isinstance(
                    result.get(
                        "step_therapy",
                        {}
                    ).get(
                        "step_therapy_requirements",
                        []
                    ),
                    list
                )
                else
                result.get(
                    "step_therapy",
                    {}
                ).get(
                    "step_therapy_requirements",
                    "NA"
                )
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

            (
                "; ".join(
                    result.get(
                        "utilization_management",
                        {}
                    ).get(
                        "quantity_limits",
                        []
                    )
                )
                if isinstance(
                    result.get(
                        "utilization_management",
                        {}
                    ).get(
                        "quantity_limits",
                        []
                    ),
                    list
                )
                else
                result.get(
                    "utilization_management",
                    {}
                ).get(
                    "quantity_limits",
                    "NA"
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

            (
                "; ".join(
                    result.get(
                        "authorization",
                        {}
                    ).get(
                        "reauthorization_requirements",
                        []
                    )
                )
                if isinstance(
                    result.get(
                        "authorization",
                        {}
                    ).get(
                        "reauthorization_requirements",
                        []
                    ),
                    list
                )
                else
                result.get(
                    "authorization",
                    {}
                ).get(
                    "reauthorization_requirements",
                    "NA"
                )
            ),

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
# NORMALISE MIXED-TYPE DURATION COLUMNS
# initial_authorization_months / reauthorization_duration_months
# can be int (12), "NA", "Unspecified", or None depending on
# what the LLM returned.  Coerce everything to string here so
# the Excel column has a consistent dtype and no "nan" cells.
# =========================================================

_DURATION_COLS = [
    "Initial Authorization Duration(in-months)",
    "Reauthorization Duration(in-months)",
]

for _col in _DURATION_COLS:
    df[_col] = df[_col].apply(
        lambda x: "NA" if x is None else str(int(x)) if isinstance(x, float) else str(x)
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