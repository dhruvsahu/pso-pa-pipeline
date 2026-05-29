import json
import logging
from utils.model_router import get_router
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
            "continuation",
            "renewal",
            "approval duration",
            "approved for",
            "authorized for",
            "authorization of",
            "may be granted",
        ]

        # -------------------------------------------------
        # TIGHT SORT SIGNALS
        # Used only for ranking collected pages — these
        # appear on actual authorization criteria pages
        # but NOT on general policy / formulary listing
        # pages.  Pages that score high here float to the
        # top of the 20K context window.
        # -------------------------------------------------

        self.auth_sort_signals = [
            "initial authorization",
            "approval criteria",
            "initial approval criteria",
            "approved for",
            "may be approved",
            "authorization of",
            "may be granted",
            "renewal criteria",
            "reauthorization criteria",
            "continued therapy criteria",
            "plaque psoriasis",
            "moderate to severe",
            "12 months",
            "6 months",
        ]

        # -------------------------------------------------
        # EXCLUSION KEYWORDS
        # -------------------------------------------------

        self.exclusion_keywords = [

            "policy history",
            "review history",
            "table of contents"
        ]

        self.model_router = get_router()

    # =====================================================
    # AUTHORIZATION CONTEXT EXTRACTION
    # Two-pass: strict brand+keyword, then proximity
    # fallback — same pattern as other extractors.
    # =====================================================

    # Narrow keyword set used ONLY for the renewal sweep.
    # These terms are specific to continuation/renewal pages
    # and won't appear on initial-criteria pages.
    RENEWAL_KEYWORDS = [
        "renewal",
        "reauthorization",
        "continuation",
        "continued therapy",
        "continued use",
        "renewal criteria",
        "re-authorization",
    ]

    def extract_authorization_context(
        self,
        pages,
        brand
    ):

        # Always run both passes and union the results.
        import re as _re

        strict = self._collect_strict(pages, brand)
        proximity = self._collect_proximity(pages, brand)

        seen = set()
        collected = []
        for page_text in strict + proximity:
            m = _re.search(r"PAGE (\d+)", page_text)
            key = m.group(1) if m else page_text.strip()[:60]
            if key not in seen:
                seen.add(key)
                collected.append(page_text)

        # -------------------------------------------------
        # RENEWAL SWEEP — targeted third pass
        # Check whether any collected page mentions BOTH the
        # brand AND a renewal keyword.  Noise pages from other
        # drugs may contain "renewal" but won't mention the
        # brand, so this check is brand-aware.
        # -------------------------------------------------
        brand_aliases = get_brand_aliases(brand)

        def _page_has_brand_renewal(page_text):
            lower = page_text.lower()
            return (
                any(a in lower for a in brand_aliases)
                and any(kw in lower for kw in self.RENEWAL_KEYWORDS)
            )

        has_renewal = any(
            _page_has_brand_renewal(p) for p in collected
        )

        if not has_renewal:
            renewal_pages = self._collect_renewal_sweep(
                pages, brand
            )
            for page_text in renewal_pages:
                m = _re.search(r"PAGE (\d+)", page_text)
                key = m.group(1) if m else page_text.strip()[:60]
                if key not in seen:
                    seen.add(key)
                    collected.append(page_text)

        if not collected:
            collected = collect_wide_fallback(
                pages,
                brand,
                self.authorization_keywords,
                self.exclusion_keywords
            )

        collected = sort_by_relevance(
            collected, self.auth_sort_signals
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
        self, pages, brand, window=4
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
    # PASS 3 — RENEWAL SWEEP
    # Wider ±8 window, renewal-specific keywords only.
    # Only called when normal collection found no renewal
    # content — avoids adding noise on normal runs.
    # =====================================================

    def _collect_renewal_sweep(
        self, pages, brand, window=8
    ):

        aliases = get_brand_aliases(brand)

        brand_indices = {
            idx for idx, p in enumerate(pages)
            if any(alias in p["text"].lower() for alias in aliases)
        }

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

            renewal_match = any(
                kw in lower_text
                for kw in self.RENEWAL_KEYWORDS
            )

            if not renewal_match:
                continue

            near_brand = any(
                abs(idx - b) <= window
                for b in brand_indices
            )

            if near_brand and page["page_number"] not in seen:
                seen.add(page["page_number"])
                collected.append(
                    f"\n\n===== PAGE "
                    f"{page['page_number']} "
                    f"[renewal-sweep] =====\n\n"
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
Duration fields (initial_authorization_months, reauthorization_duration_months) must be:
- integer month value (e.g. 6, 12) — explicit duration stated in the policy
- "Unspecified" — authorization/approval section exists for this brand but no explicit
  duration in months is stated
- "NA" — no authorization criteria found for this brand in the provided context

Use "Unspecified" (NOT "NA") when an authorization or approval section for this brand
exists in the context but does not specify a number of months.
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
            # Post-parse coercion:
            # When context exists but no explicit months found,
            # use "Unspecified" rather than None/"NA" (Req 2.4).
            # ---------------------------------------------
            def _coerce_duration(val):
                """None or 'NA' → 'Unspecified' when auth context exists."""
                if val is None or val == "NA":
                    return "Unspecified"
                return val

            # ---------------------------------------------
            # FINAL OUTPUT
            # ---------------------------------------------

            return {

                "parameter_group": (
                    "Authorization"
                ),

                "brand": brand,

                "initial_authorization_months":

                    _coerce_duration(
                        parsed_output.get(
                            "initial_authorization_months"
                        )
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

            logging.warning(
                "[AuthorizationExtractor] extraction failed for brand=%s pdf=%s: %s",
                brand, pdf_name, e, exc_info=True
            )
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

                "confidence": 0,

                "extraction_error": True,
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