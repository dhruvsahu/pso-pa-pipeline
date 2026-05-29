"""
Re-score the stored pipeline results with the CURRENT scorer.

Recomputes each row's `access_quality` block from its STORED extraction
values (age / step_therapy / authorization / utilization_management /
clinical_access) — no LLM call, no PDF re-parse. This:

- normalizes every row to the current scorer schema (fixes the legacy
  flat-list `score_breakdown` row that scored 70 under an older scorer), and
- stamps each row with `scorer_version`, making the dataset reproducible
  from the code in this repo.

Usage:
    python rescore.py            # re-score outputs/final_access_results.json in place
    python result_formatter.py   # then regenerate CSV + XLSX from the re-scored JSON
"""

import json

from access_quality_scorer import AccessQualityScorer, SCORER_VERSION

RESULTS_PATH = "outputs/final_access_results.json"


def rescore_stored_results(path=RESULTS_PATH):
    """Recompute access_quality for every stored row using the current scorer."""
    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    scorer = AccessQualityScorer()

    for row in results:
        row["access_quality"] = scorer.calculate_score(
            brand=row.get("brand"),
            step_therapy_result=row.get("step_therapy") or {},
            authorization_result=row.get("authorization") or {},
            utilization_result=row.get("utilization_management") or {},
            clinical_access_result=row.get("clinical_access") or {},
            age_result=row.get("age") or {},
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    rows = rescore_stored_results()
    print(
        f"Re-scored {len(rows)} rows with scorer v{SCORER_VERSION} "
        f"-> {RESULTS_PATH}"
    )
