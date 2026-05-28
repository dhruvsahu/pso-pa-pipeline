import json
import time
import pandas as pd
import os

from extractors.age_extractor import (
    AgeExtractor
)

from extractors.step_therapy_extractor import (
    StepTherapyExtractor
)

from extractors.authorization_extractor import (
    AuthorizationExtractor
)

from extractors.utilization_management_extractor import (
    UtilizationManagementExtractor
)

from extractors.clinical_access_extractor import (
    ClinicalAccessExtractor
)

from access_quality_scorer import (
    AccessQualityScorer
)

from utils.document_processor import (
    DocumentProcessor
)


# =========================================================
# CONFIG
# =========================================================

BASE_FOLDER = "Sample_PsO_ADS_Track"
OUTPUT_PATH = "outputs/final_access_results.json"
# Rate limiting is now handled by ModelRouter._gemini_throttle()
# No fixed sleep needed here.


def main():

    # =========================================================
    # LOAD SAMPLE BATCH
    # =========================================================

    batch_df = pd.read_csv(
        "assets/sample_batch.csv"
    )

    TEST_CASES = batch_df.to_dict(
        orient="records"
    )

    # =========================================================
    # CHECKPOINT — load previously completed results
    # =========================================================

    os.makedirs("outputs", exist_ok=True)

    all_results = []

    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            try:
                all_results = json.load(f)
            except json.JSONDecodeError:
                all_results = []
        print(
            f"[CHECKPOINT] Loaded {len(all_results)} "
            f"previously completed results"
        )

    completed_keys = {
        (r["filename"], r["brand"])
        for r in all_results
    }

    # =========================================================
    # INITIALIZE EXTRACTORS
    # =========================================================

    age_extractor = AgeExtractor()
    therapy_extractor = StepTherapyExtractor()
    authorization_extractor = AuthorizationExtractor()
    utilization_extractor = UtilizationManagementExtractor()
    clinical_access_extractor = ClinicalAccessExtractor()
    scorer = AccessQualityScorer()
    processor = DocumentProcessor()

    # =========================================================
    # RUN PIPELINE
    # =========================================================

    remaining = [
        t for t in TEST_CASES
        if (t["filename"], t["brand"]) not in completed_keys
    ]

    print(
        f"\n[BATCH] {len(TEST_CASES)} total | "
        f"{len(completed_keys)} already done | "
        f"{len(remaining)} to process\n"
    )

    for idx, test in enumerate(remaining):

        pdf_path = (
            f"{BASE_FOLDER}/"
            f"{test['filename']}"
        )

        brand = test["brand"]

        print("\n" + "=" * 80)
        print(
            f"[{idx+1}/{len(remaining)}] "
            f"PROCESSING: {brand}  |  {test['filename']}"
        )
        print("=" * 80)

        # -------------------------------------------------
        # Verify PDF exists before spending API calls
        # -------------------------------------------------
        if not os.path.exists(pdf_path):
            print(f"[SKIP] PDF not found: {pdf_path}")
            continue

        try:

            pages = processor.process_pdf(pdf_path)

            # =============================================
            # AGE EXTRACTION
            # =============================================
            start = time.time()
            age_result = age_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
            print(
                f"[TIME] Age: "
                f"{round(time.time() - start, 2)}s"
            )
            # throttling handled by ModelRouter

            # =============================================
            # STEP THERAPY EXTRACTION
            # =============================================
            start = time.time()
            therapy_result = therapy_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
            print(
                f"[TIME] Step Therapy: "
                f"{round(time.time() - start, 2)}s"
            )
            # throttling handled by ModelRouter

            # =============================================
            # AUTHORIZATION
            # =============================================
            start = time.time()
            authorization_result = authorization_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
            print(
                f"[TIME] Authorization: "
                f"{round(time.time() - start, 2)}s"
            )
            # throttling handled by ModelRouter

            # =============================================
            # UTILIZATION MANAGEMENT
            # =============================================
            start = time.time()
            utilization_result = utilization_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
            print(
                f"[TIME] Utilization: "
                f"{round(time.time() - start, 2)}s"
            )
            # throttling handled by ModelRouter

            # =============================================
            # CLINICAL ACCESS
            # =============================================
            start = time.time()
            clinical_access_result = clinical_access_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
            print(
                f"[TIME] Clinical Access: "
                f"{round(time.time() - start, 2)}s"
            )

            # =============================================
            # ACCESS QUALITY SCORE
            # =============================================
            start = time.time()
            access_score_result = scorer.calculate_score(
                brand=brand,
                step_therapy_result=therapy_result,
                authorization_result=authorization_result,
                utilization_result=utilization_result,
                clinical_access_result=clinical_access_result,
                age_result=age_result
            )
            print(
                f"[TIME] Scorer: "
                f"{round(time.time() - start, 2)}s"
            )

            # =============================================
            # COMBINE & CHECKPOINT SAVE
            # =============================================

            final_result = {
                "brand": brand,
                "filename": test["filename"],
                "age": age_result,
                "step_therapy": therapy_result,
                "authorization": authorization_result,
                "utilization_management": utilization_result,
                "clinical_access": clinical_access_result,
                "access_quality": access_score_result
            }

            all_results.append(final_result)

            # Write checkpoint after every drug
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)

            print(
                f"[SAVED] Checkpoint: {len(all_results)} "
                f"results written to {OUTPUT_PATH}"
            )

            print(
                json.dumps(final_result, indent=2)
            )

        except Exception as e:
            import traceback
            print(f"FAILED: {brand}  |  {pdf_path}")
            traceback.print_exc()

    # =========================================================
    # DONE
    # =========================================================

    print("\n" + "=" * 80)
    print(
        f"PIPELINE COMPLETE — "
        f"{len(all_results)} results in {OUTPUT_PATH}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
