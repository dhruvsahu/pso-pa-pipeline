import json
import pandas as pd
import os


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
        "Age": result.get("age", {}).get("value"),
        "Step Therapy Requirements Documented in Policy":
            "; ".join(st_reqs) if isinstance(st_reqs, list) else st_reqs or "NA",
        "Number of Steps through Brands":
            result.get("step_therapy", {}).get("brand_steps"),
        "Number of Steps through Generic":
            result.get("step_therapy", {}).get("generic_steps"),
        "Step through Phototherapy":
            result.get("step_therapy", {}).get("phototherapy_required"),
        "TB Test required":
            result.get("clinical_access", {}).get("tb_test_required"),
        "Specialist Types":
            ", ".join(spec) if isinstance(spec, list) else spec or "NA",
        "Quantity Limits":
            "; ".join(ql) if isinstance(ql, list) else ql or "NA",
        "Initial Authorization Duration(in-months)":
            "NA" if init_auth is None else str(int(init_auth)) if isinstance(init_auth, float) else str(init_auth),
        "Reauthorization Duration(in-months)":
            "NA" if reauth_dur is None else str(int(reauth_dur)) if isinstance(reauth_dur, float) else str(reauth_dur),
        "Reauthorization Required":
            result.get("authorization", {}).get("reauthorization_required"),
        "Reauthorization Requirements Documented in Policy":
            "; ".join(reauth_reqs) if isinstance(reauth_reqs, list) else reauth_reqs or "NA",
        "Access Score":
            result.get("access_quality", {}).get("access_quality_score"),
    }


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
    rows.append(flatten_result(result))

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