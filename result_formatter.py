import json
import pandas as pd
import os


# =========================================================
# HELPERS
# =========================================================

def join_or_na(value, sep="; "):
    """
    Join a list with `sep`, or return the scalar/None value.
    Always returns "NA" for an empty list or falsy scalar —
    never returns an empty string.
    """
    if isinstance(value, list):
        return sep.join(value) if value else "NA"
    return value or "NA"


# Known internal sentinels that must never appear in graded cells.
_SENTINELS = {"NO BRAND MATCH FOUND", "", None}


def clean_cell(value):
    """Map any known internal sentinel to 'NA'; pass all other values through."""
    return "NA" if value in _SENTINELS else value


# =========================================================
# SUBMISSION COLUMN ORDER — single source of truth
# Names and order must match the Submissions-tab header exactly.
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

    return {
        "Filename": result.get("filename"),
        "Brand": result.get("brand"),
        "Age": clean_cell(result.get("age", {}).get("value")),
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
            result.get("authorization", {}).get("reauthorization_required"),
        "Reauthorization Requirements Documented in Policy":
            join_or_na(reauth_reqs),
        "Access Score":
            result.get("access_quality", {}).get("access_quality_score"),
    }


# =========================================================
# BATCH FORMATTER — only runs when executed directly
# =========================================================

def main():
    # ----- Load results -----
    with open("outputs/final_access_results.json", "r", encoding="utf-8") as f:
        results = json.load(f)

    # ----- Flatten -----
    rows = [flatten_result(r) for r in results]

    # ----- Build DataFrame reindexed to submission column order -----
    df = pd.DataFrame(rows)[SUBMISSION_COLUMNS]

    # ----- Write outputs -----
    os.makedirs("outputs", exist_ok=True)

    df.to_csv("outputs/final_access_results.csv", index=False)
    df.to_excel("outputs/final_access_results.xlsx", index=False)

    print("\n" + "=" * 80)
    print("RESULT FORMATTING COMPLETE")
    print("=" * 80)
    print(df.head())


if __name__ == "__main__":
    main()