import json
from extractors.model_router import (
    ModelRouter
)
from utils.extractor_utils import (
    clean_json_output,
    write_debug_context
)

class UtilizationManagementExtractor:

    def __init__(self):
        
        self.model_router = (
            ModelRouter()
        )

        # -------------------------------------------------
        # RETRIEVAL KEYWORDS
        # -------------------------------------------------

        self.retrieval_keywords = [

            # Explicit QL labels (must match LLM prompt)
            "quantity limit",
            "quantity limits",
            "quantity level limit",
            "quantity restriction",
            "ql",

            # Dispensing / supply limits
            "dispensing limit",
            "days supply",
            "day supply",
            "max units",
            "maximum units",
            "maximum quantity",
            "units per",

            # Dose-based QL language
            "dose limit",
            "maximum dose",
            "frequency limit",
            "per 28 days",
            "per 56 days",
            "per 84 days",

            # Fill-related
            "split fill",
            "partial fill",

            # Site / form
            "site of care",
            "vials",
            "syringe"
        ]

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
    # CONTEXT RETRIEVAL
    # =====================================================

    def extract_utilization_context(
        self,
        pages,
        brand
    ):

        # ---------------------------------------------
        # PASS 1 — strict: brand AND utilization keyword
        # on the same page. Avoids pulling in unrelated
        # drug QL sections.
        # ---------------------------------------------

        collected_pages = self._collect_strict(
            pages,
            brand
        )

        # ---------------------------------------------
        # PASS 2 — proximity fallback: if strict pass
        # found nothing, take utilization-keyword pages
        # within ±2 pages of a brand-match page.
        # Handles QL tables where drug name is in a row
        # but section header is on the previous page.
        # ---------------------------------------------

        if not collected_pages:

            collected_pages = self._collect_proximity(
                pages,
                brand
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

        for page in pages:

            text = page["text"]

            lower_text = text.lower()

            if any(
                exclusion in lower_text
                for exclusion in self.exclusion_keywords
            ):
                continue

            brand_match = brand.lower() in lower_text

            utilization_match = any(
                keyword in lower_text
                for keyword in self.retrieval_keywords
            )

            if brand_match and utilization_match:

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

        # Build set of page indices where brand appears
        brand_indices = set()

        for idx, page in enumerate(pages):

            if brand.lower() in page["text"].lower():

                brand_indices.add(idx)

        # Collect utilization-keyword pages within
        # `window` pages of any brand-match page
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

            utilization_match = any(
                keyword in lower_text
                for keyword in self.retrieval_keywords
            )

            if not utilization_match:
                continue

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

Your task is to extract utilization management information
ONLY for the TARGET DRUG.

EXTRACT:

1. Quantity limits explicitly documented in policy

QUANTITY LIMIT RULES:

Capture ONLY statements explicitly described as:
- quantity limit
- quantity limits
- QL
- quantity restriction

DO NOT capture:
- dosage limits
- dosing limits
- dose escalation language
- frequency recommendations
- administration schedules

UNLESS they are explicitly labeled as
quantity limits.

IMPORTANT:
- Extract quantity limit language EXACTLY as written
- Ignore unrelated drugs
- Ignore references
- Ignore HCPCS/NDC sections
- Ignore examples
- Ignore dosage-only sections
- Use ONLY evidence from provided context

NORMALIZATION RULES:

Return:
- ARRAY OF STRINGS
    if quantity limits exist

- "No"
    if policy explicitly indicates no quantity limits

- "NA"
    if no usable quantity limit information exists

Return STRICT JSON ONLY.

Required JSON format:

{{
    "quantity_limits": "NA",
    "source_statements": [],
    "reasoning": "",
    "confidence": 0.0
}}

IMPORTANT:
quantity_limits must be EXACTLY ONE OF:
- array of strings
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

    def extract(
        self,
        pages,
        brand,
        pdf_name=""
    ):

        try:

            # ---------------------------------------------
            # CONTEXT RETRIEVAL
            # ---------------------------------------------

            context = (
                self.extract_utilization_context(
                    pages,
                    brand
                )
            )

            # ---------------------------------------------
            # DEBUG FILE
            # ---------------------------------------------

            write_debug_context(
                "utilization",
                brand,
                context,
                pdf_name
            )

            # ---------------------------------------------
            # EMPTY CONTEXT GUARD
            # ---------------------------------------------

            if not context.strip():

                return {
                    "parameter_group": "Utilization Management",
                    "brand": brand,
                    "quantity_limits": "NA",
                    "source_statements": [],
                    "reasoning": "No utilization management context found in policy",
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
                    "Utilization Management"
                ),

                "brand": brand,

                "quantity_limits":

                    parsed_output.get(
                        "quantity_limits",
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
                    "Utilization Management"
                ),

                "brand": brand,

                "quantity_limits": "NA",

                "source_statements": [],

                "reasoning": str(e),

                "confidence": 0
            }

# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    extractor = (
        UtilizationManagementExtractor()
    )

    test_cases = [

        {
            "pdf": "378692-5003182.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "378792-5004240.pdf",
            "brand": "TREMFYA"
        },

        {
            "pdf": "379899-5030421.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "51842-4975862.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "55182-4590747.pdf",
            "brand": "SILIQ"
        },

        {
            "pdf": "56061-4538520.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "56263-4803097.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "56403-5061730.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "58918-4969735.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "66156-4274314.pdf",
            "brand": "CIMZIA"
        },

        {
            "pdf": "84074-5053811.pdf",
            "brand": "STELARA"
        },

        {
            "pdf": "8889-4641730.pdf",
            "brand": "AMJEVITA"
        },

        {
            "pdf": "8898-4735285.pdf",
            "brand": "COSENTYX"
        },

        {
            "pdf": "9023-4381765.pdf",
            "brand": "ENBREL"
        },

        {
            "pdf": "9026-4997564.pdf",
            "brand": "REMICADE"
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

        "utilization_management_results.json",

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