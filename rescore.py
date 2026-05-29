"""
rescore.py — Re-score all rows in the stored checkpoint JSON using the
current AccessQualityScorer, then regenerate CSV/XLSX via result_formatter.

No LLM calls are made.  Every row's access_quality block is recomputed
from its stored extraction sub-dicts (age, step_therapy, authorization,
utilization_management, clinical_access).

Usage:
    python rescore.py

Outcome:
  - outputs/final_access_results.json  — all rows re-scored, uniform schema
  - outputs/final_access_results.csv   — regenerated flat table
  - outputs/final_access_results.xlsx  — regenerated Excel
"""

import json
import os
import sys

from access_quality_scorer import AccessQualityScorer, SCORER_VERSION
from result_formatter import flatten_result, SUBMISSION_COLUMNS

import pandas as pd


INPUT_PATH  = "outputs/final_access_results.json"
OUTPUT_PATH = "outputs/final_access_results.json"
CSV_PATH    = "outputs/final_access_results.csv"
XLSX_PATH   = "outputs/final_access_results.xlsx"


def rescore_stored_results():
    """
    Load the checkpoint JSON, re-score every row with the current scorer,
    write the updated JSON, regenerate CSV/XLSX, and print distribution stats.
    """
    if not os.path.exists(INPUT_PATH):
        print(f"[ERROR] {INPUT_PATH} not found — run the full pipeline first.")
        sys.exit(1)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)

    print(f"[RESCORE] Loaded {len(results)} rows from {INPUT_PATH}")
    print(f"[RESCORE] Current scorer version: {SCORER_VERSION}")

    scorer = AccessQualityScorer()
    rescored = []
    changed  = 0

    for row in results:
        brand    = row.get("brand", "")
        filename = row.get("filename", "")

        old_score = (row.get("access_quality") or {}).get("access_quality_score")
        old_ver   = (row.get("access_quality") or {}).get("scorer_version", "<legacy>")

        new_quality = scorer.calculate_score(
            brand=brand,
            step_therapy_result=row.get("step_therapy", {}),
            authorization_result=row.get("authorization", {}),
            utilization_result=row.get("utilization_management", {}),
            clinical_access_result=row.get("clinical_access", {}),
            age_result=row.get("age", {}),
        )

        new_row = dict(row)
        new_row["access_quality"] = new_quality
        rescored.append(new_row)

        new_score = new_quality["access_quality_score"]
        if old_score != new_score or old_ver != SCORER_VERSION:
            changed += 1
            print(
                f"  [CHANGED] {brand} | {filename} "
                f"score {old_score}->{new_score}  "
                f"(was scorer_version={old_ver})"
            )

    print(f"\n[RESCORE] {changed} rows updated out of {len(rescored)} total")

    # ----- Write updated JSON -----
    os.makedirs("outputs", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rescored, f, indent=2)
    print(f"[RESCORE] Saved updated JSON -> {OUTPUT_PATH}")

    # ----- Regenerate CSV/XLSX via formatter -----
    rows = [flatten_result(r) for r in rescored]
    df   = pd.DataFrame(rows)[SUBMISSION_COLUMNS]

    df.to_csv(CSV_PATH, index=False)
    print(f"[RESCORE] Saved CSV  -> {CSV_PATH}")

    try:
        df.to_excel(XLSX_PATH, index=False)
        print(f"[RESCORE] Saved XLSX -> {XLSX_PATH}")
    except PermissionError:
        print(f"[RESCORE] XLSX skipped (file locked, likely open in Excel) -> {XLSX_PATH}")

    # ----- Distribution stats -----
    scores = df["Access Score"].dropna().astype(float)
    print("\n" + "=" * 60)
    print("SCORE DISTRIBUTION (use these to update README)")
    print("=" * 60)
    print(f"  Rows          : {len(scores)}")
    print(f"  Min           : {int(scores.min())}")
    print(f"  Max           : {int(scores.max())}")
    print(f"  Mean          : {scores.mean():.1f}")
    print(f"  Median        : {scores.median():.1f}")
    print(f"  ≥75 (Preferred): {(scores >= 75).sum()}")
    print(f"  50–74 (FDA Parity)    : {((scores >= 50) & (scores < 75)).sum()}")
    print(f"  25–49 (Restricted)    : {((scores >= 25) & (scores < 50)).sum()}")
    print(f"  0–24  (Highly Restricted): {(scores < 25).sum()}")
    print("=" * 60)

    return rescored, df


if __name__ == "__main__":
    rescore_stored_results()
