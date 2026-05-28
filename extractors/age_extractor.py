import re
import json
from utils.model_router import (
    ModelRouter
)
from utils.extractor_utils import (
    clean_json_output,
    write_debug_context,
    get_brand_aliases
)

class AgeExtractor:

    def __init__(self):

        self.keywords = [

            # -----------------------------------------
            # AGE SIGNALS
            # -----------------------------------------

            "years of age",
            "18 years",
            "12 years",
            "6 years",

            "adult patients",
            "pediatric patients",
            "pediatric",
            "adult",

            "children",
            "adolescents",

            "younger than",
            "older than",

            "minimum age",
            "age requirement",
            "age restriction",

            # -----------------------------------------
            # FDA / INDICATION LANGUAGE
            # -----------------------------------------

            "FDA labelled age",
            "FDA-approved age",
            "indicated for",

            "indicated in adults",
            "indicated in pediatric",

            # -----------------------------------------
            # CLINICAL CRITERIA
            # -----------------------------------------

            "initial criteria",
            "patient eligibility",
            "coverage criteria",

            # -----------------------------------------
            # DISEASE SIGNALS
            # -----------------------------------------

            "plaque psoriasis",
            "psoriasis",
            "psoriatic arthritis",
            "crohn's disease",
            "ulcerative colitis",

            "moderate-to-severe",
            "adult patients with",
            "pediatric patients with",

            "indicated for treatment of",
            "FDA-approved indication"
        ]

        self.model_router = (
            ModelRouter()
        )

    # =====================================================
    # PAGE SCORING
    # =====================================================

    def score_page(self, page_text, brand):

        score = 0

        text_lower = page_text.lower()

        # Brand weighting — count both brand and generic
        for alias in get_brand_aliases(brand):
            score += text_lower.count(alias) * 20

        # Keyword scoring
        for keyword in self.keywords:

            keyword_matches = text_lower.count(
                keyword.lower()
            )

            score += keyword_matches * 2

        # Age pattern scoring
        age_patterns = [
            r'years of age',
            r'\d+\s+years',
            r'>=\s*\d+'
        ]

        for pattern in age_patterns:

            matches = re.findall(
                pattern,
                page_text,
                re.IGNORECASE
            )

            score += len(matches)

        return score

    # =====================================================
    # RELEVANT PAGE RETRIEVAL
    # =====================================================

    def get_top_pages(
        self,
        pages,
        brand,
        top_k=3
    ):

        scored_pages = []

        for page in pages:

            text_lower = page["text"].lower()

            # Hard brand/generic filter
            aliases = get_brand_aliases(brand)
            if not any(alias in text_lower for alias in aliases):
                continue

            score = self.score_page(
                page["text"],
                brand
            )

            scored_pages.append({
                "page_number": page["page_number"],
                "score": score,
                "text": page["text"]
            })

        scored_pages = sorted(
            scored_pages,
            key=lambda x: x["score"],
            reverse=True
        )

        return scored_pages[:top_k]

    # =====================================================
    # CONTEXT BUILDING
    # =====================================================

    def build_context(self, top_pages):

        context = ""

        for page in top_pages:

            context += (
                f"\n\n===== PAGE "
                f"{page['page_number']} =====\n"
            )

            context += page["text"]

        return context

    # =====================================================
    # LLM EXTRACTION
    # =====================================================

    def resolve_age_with_llm(
        self,
        brand,
        context
    ):

        # Limit context size
        context = context[:12000]

        prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Brand:
{brand}

Relevant Policy Context:
{context}

Your task is to determine the age eligibility requirement for the TARGET BRAND ONLY.

IMPORTANT RULES:

1. Focus ONLY on the target brand.
2. Ignore unrelated brands or therapies.
3. Extract the MINIMUM eligible age requirement if present.
4. If multiple age thresholds are present, return the YOUNGEST eligible age.
5. Age may appear as:
   - explicit numerical thresholds
   - FDA labelled age wording
   - adult/pediatric population references
   - indication-based eligibility

NORMALIZATION RULES:

1. If the policy refers to:
    - adult patients
    → resolve as ">=18"

2. If policy refers only to:
    - pediatric patients
    - adolescents
    - FDA-approved pediatric indication
    WITHOUT explicit numeric age
    → resolve as:
    "FDA labelled age"

3. If policy explicitly indicates no age restriction:
   → return:
   "No Age Restriction"

4. If no usable age information exists in the context:
   → return:
   "NA"

5. If both FDA-labelled wording and explicit age exist:
   prioritize explicit age.

IMPORTANT:
- Use ONLY evidence from the provided context.
- Do NOT infer unsupported ages.
- Do NOT hallucinate FDA ages.
- Prefer exact policy wording.
- If evidence is weak or absent, return "NA".
Age eligibility may be implied through indication wording such as:
- "adult patients with..."
- "pediatric patients with..."
- "indicated for treatment of..."
Treat these as valid age evidence.

If explicit numerical age exists anywhere in the policy context,
ALWAYS prioritize the numerical age.

Example:
"6 years of age and older"
→ return:
">=6"

Return:
"FDA labelled age"
ONLY IF:
- FDA-labelled age is referenced
AND
- NO explicit numerical age exists anywhere in the relevant context.

Return STRICT JSON ONLY.

Required JSON format:

{{
    "brand": "{brand}",
    "resolved_age": "",
    "source_statement": "",
    "reasoning": "",
    "confidence": 0.0
}}

Where:
- resolved_age must be EXACTLY ONE OF:
    - ">=<number>"
    - "FDA labelled age"
    - "No Age Restriction"
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
    # MAIN EXTRACTION METHOD
    # =====================================================

    def extract(
        self,
        pages,
        brand,
        pdf_name=""
    ):

        try:

            # -----------------------------------------
            # Extract Pages
            # -----------------------------------------

            # pages = self.extract_pages(
            #     pdf_path
            # )

            # -----------------------------------------
            # Retrieve Relevant Pages
            # -----------------------------------------

            top_pages = self.get_top_pages(
                pages,
                brand,
                top_k=3
            )

            if len(top_pages) == 0:

                return {
                    "parameter": "Age",
                    "brand": brand,
                    "value": "NO BRAND MATCH FOUND",
                    "source_statement": None,
                    "reasoning": (
                        "Brand not found "
                        "in retrieved pages"
                    ),
                    "confidence": 0,
                    "retrieved_pages": []
                }

            # -----------------------------------------
            # Build Context
            # -----------------------------------------

            context = self.build_context(
                top_pages
            )

            # -----------------------------------------
            # DEBUG FILE
            # -----------------------------------------

            write_debug_context(
                "age",
                brand,
                context,
                pdf_name
            )

            # -----------------------------------------
            # LLM Resolution
            # -----------------------------------------

            llm_output = self.resolve_age_with_llm(
                brand,
                context
            )

            # -----------------------------------------
            # Cleanup JSON
            # -----------------------------------------

            cleaned_output = clean_json_output(
                llm_output
            )

            parsed_output = json.loads(
                cleaned_output
            )

            # -----------------------------------------
            # Standardized Output
            # -----------------------------------------

            return {
                "parameter": "Age",
                "brand": parsed_output.get(
                    "brand",
                    brand
                ),
                "value": parsed_output.get(
                    "resolved_age"
                ),
                "source_statement": parsed_output.get(
                    "source_statement"
                ),
                "reasoning": parsed_output.get(
                    "reasoning"
                ),
                "confidence": parsed_output.get(
                    "confidence"
                ),
                "retrieved_pages": [
                    p["page_number"]
                    for p in top_pages
                ]
            }

        except Exception as e:

            return {
                "parameter": "Age",
                "brand": brand,
                "value": None,
                "source_statement": None,
                "reasoning": str(e),
                "confidence": 0,
                "retrieved_pages": []
            }


# =========================================================
# LOCAL TESTING
# =========================================================

if __name__ == "__main__":

    extractor = AgeExtractor()

    result = extractor.extract(
        pdf_path="Sample_PsO_ADS_Track/148593-4960549.pdf",
        brand="STELARA"
    )

    print(json.dumps(result, indent=2))