import json
from utils.model_router import (
    ModelRouter
)
from utils.extractor_utils import (
    clean_json_output,
    write_debug_context,
    collect_wide_fallback,
    get_brand_aliases
)


class ClinicalAccessExtractor:

    def __init__(self):

        # -------------------------------------------------
        # RETRIEVAL KEYWORDS
        # -------------------------------------------------

        self.retrieval_keywords = [

            # TB testing
            "tuberculosis",
            "latent tb",
            "tb test",
            "tb screening",
            "tuberculin",
            "ppd",
            "igra",
            "quantiferon",

            # Precertification / prior auth
            "precertification",
            "requires precertification",
            "prior authorization",
            "prior auth",
            "preauthorization",
            "advance approval",

            # Specialist restrictions
            "prescriber specialties",
            "prescriber specialty",
            "specialist",
            "must be prescribed by",
            "prescribed by a",
            "dermatologist",
            "rheumatologist",
            "gastroenterologist",
            "initiated by",
            "under the supervision",
            "consultation with"
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
    # CONTEXT EXTRACTION
    # =====================================================

    def extract_clinical_access_context(
        self,
        pages,
        brand
    ):

        # ---------------------------------------------
        # PASS 1 — strict: brand AND access keyword
        # on the same page.  Avoids pulling in shared
        # policy sections about unrelated drugs.
        # ---------------------------------------------

        collected_pages = self._collect_strict(
            pages,
            brand
        )

        # ---------------------------------------------
        # PASS 2 — proximity fallback: if strict pass
        # found nothing, take access-keyword pages that
        # sit within ±2 pages of a brand-match page.
        # Handles policies where TB / precert language
        # lives in a shared section that doesn't repeat
        # the brand name.
        # ---------------------------------------------

        if not collected_pages:

            collected_pages = self._collect_proximity(
                pages,
                brand
            )

        if not collected_pages:

            collected_pages = collect_wide_fallback(
                pages,
                brand,
                self.retrieval_keywords,
                self.exclusion_keywords
            )

        return "\n".join(
            collected_pages
        )

    # =====================================================
    # PASS 1 — STRICT COLLECTION
    # =====================================================

    def _collect_strict(
        self,
        pages,
        brand
    ):

        collected = []

        aliases = get_brand_aliases(brand)

        for page in pages:

            text = page["text"]

            lower_text = text.lower()

            if any(
                exclusion in lower_text
                for exclusion in self.exclusion_keywords
            ):
                continue

            brand_match = any(
                alias in lower_text for alias in aliases
            )

            access_match = any(
                keyword in lower_text
                for keyword in self.retrieval_keywords
            )

            if brand_match and access_match:

                collected.append(

                    f"\n\n===== PAGE "
                    f"{page['page_number']} =====\n\n"

                    + text
                )

        return collected

    # =====================================================
    # PASS 2 — PROXIMITY FALLBACK
    # =====================================================

    def _collect_proximity(
        self,
        pages,
        brand,
        window=2
    ):

        # Build a set of page indices where brand or generic appears
        aliases = get_brand_aliases(brand)

        brand_indices = set()

        for idx, page in enumerate(pages):

            if any(
                alias in page["text"].lower()
                for alias in aliases
            ):
                brand_indices.add(idx)

        # Collect pages with access keywords that are
        # within `window` pages of any brand-match page
        collected = []

        seen_page_numbers = set()

        for idx, page in enumerate(pages):

            text = page["text"]

            lower_text = text.lower()

            if any(
                exclusion in lower_text
                for exclusion in self.exclusion_keywords
            ):
                continue

            access_match = any(
                keyword in lower_text
                for keyword in self.retrieval_keywords
            )

            if not access_match:
                continue

            # Check proximity to any brand page
            near_brand = any(
                abs(idx - b_idx) <= window
                for b_idx in brand_indices
            )

            if (
                near_brand
                and page["page_number"] not in seen_page_numbers
            ):

                seen_page_numbers.add(
                    page["page_number"]
                )

                collected.append(

                    f"\n\n===== PAGE "
                    f"{page['page_number']} "
                    f"[proximity] =====\n\n"

                    + text
                )

        return collected

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
    # MAIN EXTRACT
    # =====================================================

    def extract(
        self,
        pages,
        brand,
        pdf_name=""
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

            write_debug_context(
                "clinical_access",
                brand,
                context,
                pdf_name
            )

            # ---------------------------------------------
            # EMPTY CONTEXT GUARD
            # ---------------------------------------------

            if not context.strip():

                return {
                    "parameter_group": "Clinical Access",
                    "brand": brand,
                    "tb_test_required": "NA",
                    "specialist_types": "NA",
                    "precertification_required": "NA",
                    "source_statements": [],
                    "reasoning": "No clinical access context found in policy",
                    "confidence": 0.0
                }

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
                clean_json_output(
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