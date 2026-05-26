import fitz
import json
from ollama import chat
from extractors.model_router import (
    ModelRouter
)


class ClinicalAccessExtractor:

    def __init__(self):

        # -------------------------------------------------
        # RETRIEVAL KEYWORDS
        # -------------------------------------------------

        self.retrieval_keywords = [

            "prescriber specialties",
            "prescriber specialty",
            "tb test",
            "tuberculosis",
            "latent tb",
            "precertification",
            "specialist",
            "must be prescribed by",
            "consultation with",
            "requires precertification"
        ]

        self.model_router = (
            ModelRouter()
        )

        # -------------------------------------------------
        # EXCLUSION KEYWORDS
        # -------------------------------------------------

        self.exclusion_keywords = [

            "references",
            "appendix",
            "policy history",
            "coding",
            "billing",
            "hcpcs",
            "ndc"
        ]

    # =====================================================
    # PAGE EXTRACTION
    # =====================================================

    def extract_pages(
        self,
        pdf_path
    ):

        doc = fitz.open(
            pdf_path
        )

        pages = []

        for i in range(len(doc)):

            text = doc[i].get_text()

            pages.append({

                "page_number": i + 1,

                "text": text
            })

        return pages

    # =====================================================
    # CONTEXT EXTRACTION
    # =====================================================

    def extract_clinical_access_context(
        self,
        pages,
        brand
    ):

        collected_pages = []

        for page in pages:

            text = page["text"]

            lower_text = text.lower()

            # ---------------------------------------------
            # EXCLUSION FILTER
            # ---------------------------------------------

            if any(
                exclusion in lower_text
                for exclusion in (
                    self.exclusion_keywords
                )
            ):

                continue

            # ---------------------------------------------
            # BRAND MATCH
            # ---------------------------------------------

            brand_match = (
                brand.lower()
                in lower_text
            )

            # ---------------------------------------------
            # ACCESS MATCH
            # ---------------------------------------------

            access_match = any(

                keyword in lower_text

                for keyword in (
                    self.retrieval_keywords
                )
            )

            # ---------------------------------------------
            # KEEP PAGE
            # ---------------------------------------------

            if (
                brand_match
                or access_match
            ):

                collected_pages.append(

                    f"\n\n===== PAGE "
                    f"{page['page_number']} =====\n\n"

                    + text
                )

        return "\n".join(
            collected_pages
        )

    # =====================================================
    # LLM EXTRACTION
    # =====================================================

    def extract_with_llm(
        self,
        brand,
        context
    ):

        context = context[:20000]

        prompt = f"""
        You are analyzing a healthcare prior authorization policy.

        Target Drug:
        {brand}

        Policy Context:
        {context}

        Your task is to extract clinical access restrictions
        ONLY for the TARGET DRUG.

        Focus primarily on:
        MODERATE-TO-SEVERE PLAQUE PSORIASIS (PsO)
        when multiple indications exist.

        EXTRACT:

        1. TB testing requirements
        2. Specialist type restrictions
        3. Precertification / prior authorization requirements

        IMPORTANT DEFINITIONS:

        TB TEST REQUIRED:
        Determine whether tuberculosis (TB) testing or screening
        is required before approval or treatment initiation.

        SPECIALIST TYPES:
        Identify the specific medical specialties acceptable for:
        - initiating treatment
        OR
        - managing treatment

        Examples include:
        - dermatologist
        - rheumatologist
        - gastroenterologist
        - immunologist

        Only capture explicit specialist restrictions.

        Do NOT infer specialist types.

        PRECERTIFICATION REQUIRED:
        Determine whether:
        - prior authorization
        - precertification
        - advance approval
        - payer authorization

        is required for coverage.

        IMPORTANT RULES:

        TB TEST REQUIRED:

        Return:
        - "Yes"
            if TB testing/screening is explicitly required

        - "No"
            if policy explicitly states TB testing is not required

        - "NA"
            if no usable TB testing evidence exists

        SPECIALIST TYPES:

        Return:
        - array of specialist types
            if specialist restrictions exist

        - "No"
            if policy explicitly states no specialist restriction

        - "NA"
            if no usable specialist evidence exists

        PRECERTIFICATION REQUIRED:

        Return:
        - "Yes"
            if precertification/prior authorization is required

        - "No"
            if explicitly stated not required

        - "NA"
            if no usable evidence exists

        IGNORE:
        - unrelated drugs
        - references
        - HCPCS/NDC sections
        - billing sections
        - dosage sections
        - quantity limit sections
        - dosing limit sections
        - examples not tied to requirements

        IMPORTANT:
        - Use ONLY evidence from provided context
        - Do NOT hallucinate restrictions
        - Preserve exact wording whenever possible

        Return STRICT JSON ONLY.

        Required JSON format:

        {{
            "tb_test_required": "NA",

            "specialist_types": "NA",

            "precertification_required": "NA",

            "source_statements": [],

            "reasoning": "",

            "confidence": 0.0
        }}

        IMPORTANT:

        tb_test_required must be EXACTLY ONE OF:
        - "Yes"
        - "No"
        - "NA"

        specialist_types must be EXACTLY ONE OF:
        - array of specialist types
        - "No"
        - "NA"

        precertification_required must be EXACTLY ONE OF:
        - "Yes"
        - "No"
        - "NA"
        """

        model = self.model_router.select_model(
            context
        )

        print(f"[MODEL SELECTED] {model}")

        response = self.model_router.generate(

            prompt=prompt,

            context=context
        )

        return response

    # =====================================================
    # CLEAN JSON
    # =====================================================

    def clean_json_output(
        self,
        text
    ):

        cleaned = (

            text
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        return cleaned

    # =====================================================
    # MAIN EXTRACT
    # =====================================================

    def extract(
        self,
        pages,
        brand
    ):

        try:

            # ---------------------------------------------
            # CONTEXT EXTRACTION
            # ---------------------------------------------

            context = (
                self.extract_clinical_access_context(
                    pages,
                    brand
                )
            )

            # ---------------------------------------------
            # DEBUG FILE
            # ---------------------------------------------

            debug_file = (

                f"debug/"
                f"debug_clinical_access_{brand}.txt"
            )

            with open(
                debug_file,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(context)

            # ---------------------------------------------
            # LLM EXTRACTION
            # ---------------------------------------------

            llm_output = (
                self.extract_with_llm(
                    brand,
                    context
                )
            )

            cleaned_output = (
                self.clean_json_output(
                    llm_output
                )
            )

            parsed_output = json.loads(
                cleaned_output
            )

            # ---------------------------------------------
            # FINAL OUTPUT
            # ---------------------------------------------

            return {

                "parameter_group": (
                    "Clinical Access"
                ),

                "brand": brand,

                "tb_test_required":

                    parsed_output.get(
                        "tb_test_required",
                        "NA"
                    ),

                "specialist_types":

                    parsed_output.get(
                        "specialist_types",
                        "NA"
                    ),

                "precertification_required":

                    parsed_output.get(
                        "precertification_required",
                        "NA"
                    ),

                "source_statements":

                    parsed_output.get(
                        "source_statements",
                        []
                    ),

                "reasoning":

                    parsed_output.get(
                        "reasoning"
                    ),

                "confidence":

                    parsed_output.get(
                        "confidence"
                    )
            }

        except Exception as e:

            return {

                "parameter_group": (
                    "Clinical Access"
                ),

                "brand": brand,

                "tb_test_required": "NA",

                "specialist_types": "NA",

                "precertification_required": "NA",

                "source_statements": [],

                "reasoning": str(e),

                "confidence": 0
            }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    extractor = (
        ClinicalAccessExtractor()
    )

    test_cases = [

        {
            "pdf": "378692-5003182.pdf",
            "brand": "STELARA"
        }
    ]

    BASE_FOLDER = "Sample_PsO_ADS_Track"

    all_results = []

    for idx, test in enumerate(test_cases):

        pdf_path = (
            f"{BASE_FOLDER}/"
            f"{test['pdf']}"
        )

        brand = test["brand"]

        print("\n" + "=" * 80)
        print(
            f"[{idx+1}/{len(test_cases)}] "
            f"PROCESSING: {brand}"
        )
        print("=" * 80)

        try:

            result = extractor.extract(

                pdf_path=pdf_path,

                brand=brand
            )

            all_results.append(result)

            print(
                json.dumps(
                    result,
                    indent=2
                )
            )

        except Exception as e:

            print(
                f"FAILED: {pdf_path}"
            )

            print(str(e))

    # -------------------------------------------------
    # SAVE RESULTS
    # -------------------------------------------------

    with open(

        "outputs/clinical_access_results.json",

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            all_results,

            f,

            indent=2
        )

    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)