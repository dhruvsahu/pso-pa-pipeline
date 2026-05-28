import json
from utils.model_router import (
    ModelRouter
)
from utils.extractor_utils import (
    clean_json_output,
    write_debug_context,
    collect_wide_fallback,
    get_brand_aliases,
    sort_by_relevance
)


class AuthorizationExtractor:

    def __init__(self):

        # -------------------------------------------------
        # AUTHORIZATION SECTION KEYWORDS
        # -------------------------------------------------

        self.authorization_keywords = [

            "prior authorization",
            "initial approval",
            "coverage duration",
            "authorization duration",
            "reauthorization",
            "renewal criteria",
            "continued therapy",
            "renewal",
            "approval duration",
            "approved for",
            "authorized for"
        ]

        # -------------------------------------------------
        # EXCLUSION KEYWORDS
        # -------------------------------------------------

        self.exclusion_keywords = [

            "policy history",
            "review history",
            "table of contents"
        ]

        self.model_router = (
            ModelRouter()
        )

    # =====================================================
    # AUTHORIZATION CONTEXT EXTRACTION
    # Two-pass: strict brand+keyword, then proximity
    # fallback — same pattern as other extractors.
    # =====================================================

    def extract_authorization_context(
        self,
        pages,
        brand
    ):

        collected = self._collect_strict(pages, brand)

        if not collected:
            collected = self._collect_proximity(
                pages, brand
            )

        if not collected:
            collected = collect_wide_fallback(
                pages,
                brand,
                self.authorization_keywords,
                self.exclusion_keywords
            )

        collected = sort_by_relevance(
            collected, self.authorization_keywords
        )

        return "\n".join(collected)

    # =====================================================
    # PASS 1 — STRICT
    # =====================================================

    def _collect_strict(self, pages, brand):

        collected = []

        aliases = get_brand_aliases(brand)

        for page in pages:

            text = page["text"]
            lower_text = text.lower()

            if any(
                ex in lower_text
                for ex in self.exclusion_keywords
            ):
                continue

            brand_match = any(
                alias in lower_text for alias in aliases
            )

            auth_match = any(
                kw in lower_text
                for kw in self.authorization_keywords
            )

            if brand_match and auth_match:

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
        self, pages, brand, window=2
    ):

        aliases = get_brand_aliases(brand)

        brand_indices = set()

        for idx, page in enumerate(pages):
            if any(
                alias in page["text"].lower()
                for alias in aliases
            ):
                brand_indices.add(idx)

        collected = []
        seen = set()

        for idx, page in enumerate(pages):

            text = page["text"]
            lower_text = text.lower()

            if any(
                ex in lower_text
                for ex in self.exclusion_keywords
            ):
                continue

            auth_match = any(
                kw in lower_text
                for kw in self.authorization_keywords
            )

            if not auth_match:
                continue

            near_brand = any(
                abs(idx - b) <= window
                for b in brand_indices
            )

            if (
                near_brand
                and page["page_number"] not in seen
            ):
                seen.add(page["page_number"])
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

        # ---------------------------------------------
        # TOKEN SAFETY
        # ---------------------------------------------

        context = context[:20000]

        prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Drug:
{brand}

Policy Context:
{context}

Your task is to extract authorization and reauthorization information
ONLY for the TARGET BRAND.

IMPORTANT:
Authorization rules may vary by indication.
Focus primarily on Psoriasis (PsO) related indications when multiple indications exist.

Extract:

1. Initial authorization duration
2. Whether reauthorization is required
3. Reauthorization duration
4. Reauthorization requirements documented in policy

NORMALIZATION RULES:

INITIAL AUTHORIZATION DURATION:
- Convert explicit durations into INTEGER MONTHS
- Example:
    "6 months" → 6
    "12-month approval" → 12

- If authorization is mentioned but duration is not specified.
    return:
    "Unspecified"

- If no authorization duration evidence exists:
    return:
    "NA"

REAUTHORIZATION REQUIRED:
Return "Yes" if ANY of the following are present:
- explicit reauthorization requirement
- reauthorization duration exists
- reauthorization requirements exist
- continuation criteria exist
- renewal approval language exists

Otherwise return "No".

Incase of no evidence of reauthorization requirements, return "NA".

REAUTHORIZATION DURATION:
- Convert explicit durations into INTEGER MONTHS
- If reauthorization exists but duration unspecified:
    return:
    "Unspecified"

- If no evidence exists and no reauthorization requirements exist:
    return:
    NA

REAUTHORIZATION REQUIREMENTS:
Extract ONLY explicit continuation or renewal criteria such as:
- continued clinical benefit
- lack of disease progression
- updated clinical documentation
- physician attestation
- response to therapy
- produce the output as "The document .." OR "The policy states ..." statements quoting the document.

Return as ARRAY OF STRINGS.

IMPORTANT RULES:
- Use ONLY evidence from provided context
- Ignore unrelated brands
- Ignore references
- Ignore examples
- Ignore HCPCS/NDC sections
- Ignore dosage-only sections
- Ignore unrelated indications
- Do NOT hallucinate durations

Return STRICT JSON ONLY.

Required JSON format:

{{
    "initial_authorization_months": "NA",
    "reauthorization_required": "NA",
    "reauthorization_duration_months": "NA",
    "reauthorization_requirements": [],
    "source_statements": [],
    "reasoning": "",
    "confidence": 0.0
}}

IMPORTANT:
Duration fields may contain:
- integer month value
- "Unspecified"
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
            # PAGE EXTRACTION
            # ---------------------------------------------

            # pages = self.extract_pages(
            #      pdf_path
            # )

            # ---------------------------------------------
            # CONTEXT EXTRACTION
            # ---------------------------------------------

            context = (
                self.extract_authorization_context(
                    pages,
                    brand
                )
            )

            # ---------------------------------------------
            # DEBUG FILE
            # ---------------------------------------------

            write_debug_context(
                "authorization",
                brand,
                context,
                pdf_name
            )

            # ---------------------------------------------
            # EMPTY CONTEXT GUARD
            # ---------------------------------------------

            if not context.strip():

                return {
                    "parameter_group": "Authorization",
                    "brand": brand,
                    "initial_authorization_months": "NA",
                    "reauthorization_required": "NA",
                    "reauthorization_duration_months": "NA",
                    "reauthorization_requirements": [],
                    "reasoning": "No authorization context found in policy",
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
                    "Authorization"
                ),

                "brand": brand,

                "initial_authorization_months":

                    parsed_output.get(
                        "initial_authorization_months"
                    ),

                "reauthorization_required":

                    parsed_output.get(
                        "reauthorization_required"
                    ),

                "reauthorization_duration_months":

                    parsed_output.get(
                        "reauthorization_duration_months"
                    ),

                "reauthorization_requirements":

                    parsed_output.get(
                        "reauthorization_requirements",
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
                    "Authorization"
                ),

                "brand": brand,

                "initial_authorization_months": None,

                "reauthorization_required": False,

                "reauthorization_duration_months": None,

                "reauthorization_requirements": [],

                "reasoning": str(e),

                "confidence": 0
            }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":


    extractor = AuthorizationExtractor()

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

        "authorization_results.json",

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