import json
import pandas as pd
import os


# =========================================================
# VALUE HELPER
# =========================================================

def join_or_na(value, sep="; "):
    """
    Render a free-text parameter value for the CSV.

    - list  -> join with `sep`, but an EMPTY list becomes "NA"
               (NOT "" — an empty join would otherwise leave the cell blank,
               violating the "all parameters populated" deliverable rule).
    - other -> the value itself, or "NA" if falsy.
    """
    if isinstance(value, list):
        return sep.join(value) if value else "NA"
    return value or "NA"


# Internal extractor sentinels / empties that must never reach a graded
# cell. They are mapped to the standard missing-value token "NA".
_SENTINELS = {"NO BRAND MATCH FOUND", "", None}


def clean_cell(value):
    """Map known internal sentinels / blanks to 'NA'; pass values through."""
    return "NA" if value in _SENTINELS else value


# =========================================================
# SUBMISSION SCHEMA — single source of truth
# Column names AND order must match the PA_Business_Rules.xlsx
# "Submissions" tab exactly (hyphenated "Step through-Phototherapy";
# "Quantity Limits" before "Specialist Types"). Both the batch
# formatter and the Flask UI import this list so they cannot drift.
# =========================================================

SUBMISSION_COLUMNS = [
    "Filename",
    "Brand",
    "Age",
    "Step Therapy Requirements Documented in Policy",
    "Number of Steps through Brands",
    "Number of Steps through Generic",
    "Step through-Phototherapy",
    "TB Test required",
    "Quantity Limits",
    "Specialist Types",
    "Initial Authorization Duration(in-months)",
    "Reauthorization Duration(in-months)",
    "Reauthorization Required",
    "Reauthorization Requirements Documented in Policy",
    "Access Score",
]


# =========================================================
# REAUTHORIZATION-REQUIRED DERIVATION
# Business rule: this column is Yes/No (never "NA"). "Yes" if the policy
# states reauthorization is required, OR gives a reauth duration, OR
# documents reauth requirements; otherwise "No".
# =========================================================

def derive_reauth_required(reauth_required, reauth_dur, reauth_reqs):
    explicit_yes = str(reauth_required).strip().lower() == "yes"
    dur_present = (
        reauth_dur is not None
        and str(reauth_dur).strip().upper() not in ("NA", "")
    )
    reqs_present = isinstance(reauth_reqs, list) and len(reauth_reqs) > 0
    return "Yes" if (explicit_yes or dur_present or reqs_present) else "No"


# =========================================================
# FLATTEN HELPER — reusable by app.py for single-result CSV
# =========================================================

def flatten_result(result):
    """
    Flatten one pipeline result dict into a single CSV row dict.
    Called by result_formatter (batch) and app.py (single-PDF UI).
    """
    ql = result.get("utilization_management", {}).get("quantity_limits", [])
    spec = result.get("clinical_access", {}).get("specialist_types", [])
    st_reqs = result.get("step_therapy", {}).get("step_therapy_requirements", [])
    reauth_reqs = result.get("authorization", {}).get("reauthorization_requirements", [])
    init_auth = result.get("authorization", {}).get("initial_authorization_months")
    reauth_dur = result.get("authorization", {}).get("reauthorization_duration_months")

    row = {
        "Filename": result.get("filename"),
        "Brand": result.get("brand"),
        "Age": result.get("age", {}).get("value"),
        "Step Therapy Requirements Documented in Policy":
            join_or_na(st_reqs),
        "Number of Steps through Brands":
            result.get("step_therapy", {}).get("brand_steps"),
        "Number of Steps through Generic":
            result.get("step_therapy", {}).get("generic_steps"),
        "Step through-Phototherapy":
            result.get("step_therapy", {}).get("phototherapy_required"),
        "TB Test required":
            result.get("clinical_access", {}).get("tb_test_required"),
        "Quantity Limits":
            join_or_na(ql),
        "Specialist Types":
            join_or_na(spec, sep=", "),
        "Initial Authorization Duration(in-months)":
            "NA" if init_auth is None else str(int(init_auth)) if isinstance(init_auth, float) else str(init_auth),
        "Reauthorization Duration(in-months)":
            "NA" if reauth_dur is None else str(int(reauth_dur)) if isinstance(reauth_dur, float) else str(reauth_dur),
        "Reauthorization Required":
            derive_reauth_required(
                result.get("authorization", {}).get("reauthorization_required"),
                reauth_dur,
                reauth_reqs,
            ),
        "Reauthorization Requirements Documented in Policy":
            join_or_na(reauth_reqs),
        "Access Score":
            result.get("access_quality", {}).get("access_quality_score"),
    }

    # Defensive: never emit an internal sentinel or blank in a graded cell.
    return {key: clean_cell(value) for key, value in row.items()}


# =========================================================
# BATCH ENTRY POINT
# Guarded under main() so importing flatten_result / join_or_na
# (e.g. from app.py or the re-score routine) has no side effects.
# =========================================================

def main():

    # -----------------------------------------------------
    # LOAD RESULTS
    # -----------------------------------------------------

    with open(
        "outputs/final_access_results.json",
        "r",
        encoding="utf-8"
    ) as f:
        results = json.load(f)

    # -----------------------------------------------------
    # FLATTEN RESULTS
    # -----------------------------------------------------

    rows = [flatten_result(result) for result in results]

    # Force exact column names + order to match the Submissions tab.
    df = pd.DataFrame(rows, columns=SUBMISSION_COLUMNS)

    # -----------------------------------------------------
    # SAVE CSV + EXCEL
    # -----------------------------------------------------

    os.makedirs("outputs", exist_ok=True)

    df.to_csv(
        "outputs/final_access_results.csv",
        index=False
    )

    df.to_excel(
        "outputs/final_access_results.xlsx",
        index=False
    )

    print("\n" + "=" * 80)
    print("RESULT FORMATTING COMPLETE")
    print("=" * 80)

    print(df.head())


if __name__ == "__main__":
    main()
