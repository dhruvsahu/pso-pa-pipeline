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

# =========================================================
# LOAD SAMPLE BATCH
# =========================================================

batch_df = pd.read_csv(
    "assets/sample_batch.csv"
)

TEST_CASES = batch_df.to_dict(
    orient="records"
)

BASE_FOLDER = (
    "Sample_PsO_ADS_Track"
)

# =========================================================
# INITIALIZE EXTRACTORS
# =========================================================

age_extractor = (
    AgeExtractor()
)

therapy_extractor = (
    StepTherapyExtractor()
)

authorization_extractor = (
    AuthorizationExtractor()
)

utilization_extractor = (
    UtilizationManagementExtractor()
)

clinical_access_extractor = (
    ClinicalAccessExtractor()
)

scorer = (
    AccessQualityScorer()
)

processor = (
    DocumentProcessor()
)

# =========================================================
# RUN PIPELINE
# =========================================================

all_results = []

for idx, test in enumerate(TEST_CASES):

    pdf_path = (
        f"{BASE_FOLDER}/"
        f"{test['filename']}"
    )

    pages = processor.process_pdf(
        pdf_path
    )

    brand = test["brand"]

    print("\n" + "=" * 80)
    print(
        f"[{idx+1}/{len(TEST_CASES)}] "
        f"PROCESSING: {brand}"
    )
    print("=" * 80)

    try:

        # =================================================
        # AGE EXTRACTION
        # =================================================
        start = time.time()
        age_result = (
            age_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
        )
        print(
            f"[TIME] Age Extractor: "
            f"{round(time.time() - start, 2)}s"
        )
        time.sleep(20)
        # =================================================
        # STEP THERAPY EXTRACTION
        # =================================================
        start = time.time()
        therapy_result = (
            therapy_extractor.extract(
                pages=pages,
                brand=brand,
                pdf_name=test["filename"]
            )
        )
        print(
            f"[TIME] Step Therapy Extractor: "
            f"{round(time.time() - start, 2)}s"
        )
        time.sleep(20)
        # =================================================
        # AUTHORIZATION
        # =================================================
        start = time.time()
        authorization_result = (
            authorization_extractor.extract(

                pages=pages,

                brand=brand,

                pdf_name=test["filename"]
            )
        )
        print(
            f"[TIME] Authorization Extractor: "
            f"{round(time.time() - start, 2)}s"
        )
        time.sleep(20)
        # =================================================
        # UTILIZATION
        # =================================================
        start = time.time()
        utilization_result = (
            utilization_extractor.extract(

                pages=pages,

                brand=brand,

                pdf_name=test["filename"]
            )
        )
        print(
            f"[TIME] Utilization Management Extractor: "
            f"{round(time.time() - start, 2)}s"
        )
        time.sleep(20)
        # =================================================
        # CLINICAL ACCESS
        # =================================================
        start = time.time()
        clinical_access_result = (
            clinical_access_extractor.extract(

                pages=pages,

                brand=brand,

                pdf_name=test["filename"]
            )
        )
        print(
            f"[TIME] Clinical Access Extractor: "
            f"{round(time.time() - start, 2)}s"
        )
        # =================================================
        # ACCESS QUALITY SCORE
        # =================================================
        start = time.time()
        access_score_result = (
            scorer.calculate_score(

                brand=brand,

                step_therapy_result=(
                    therapy_result
                ),

                # step_therapy_result=(
                #     step_count_result
                # ),

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
        )
        print(
            f"[TIME] Access Quality Scorer: "
            f"{round(time.time() - start, 2)}s"
        )
        # =================================================
        # FINAL COMBINED OUTPUT
        # =================================================

        final_result = {

            "brand": brand,

            "filename": test["filename"],

            "age": age_result,

            "step_therapy": (
                therapy_result
            ),

            "authorization": (
                authorization_result
            ),

            "utilization_management": (
                utilization_result
            ),

            "clinical_access": (
                clinical_access_result
            ),

            "access_quality": (
                access_score_result
            )
        }

        all_results.append(
            final_result
        )

        print(
            json.dumps(
                final_result,
                indent=2
            )
        )

    except Exception as e:
        import traceback
        print(f"FAILED: {brand}")
        traceback.print_exc()

# =========================================================
# SAVE OUTPUT
# =========================================================

# Ensure the output directory exists
os.makedirs("outputs", exist_ok=True)

with open(

    "outputs/final_access_results.json",

    "w",

    encoding="utf-8"

) as f:

    json.dump(

        all_results,

        f,

        indent=2
    )

print("\n" + "=" * 80)
print("PIPELINE COMPLETE")
print("=" * 80)