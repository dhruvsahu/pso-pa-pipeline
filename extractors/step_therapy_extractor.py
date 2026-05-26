import re
import json
import pandas as pd
from extractors.model_router import (
    ModelRouter
)

class StepTherapyExtractor:

    def __init__(self):

        therapy_df = pd.read_csv(
            "assets/therapy_dictionary_normalized.csv"
        )

        self.model_router = (
            ModelRouter()
        )

        self.known_therapies = sorted(

            set(
                therapy_df["raw_term"]
                .dropna()
                .astype(str)
                .str.lower()
                .str.strip()
            ),

            key=len,

            reverse=True
        )

        self.therapy_lookup = {}

        for _, row in therapy_df.iterrows():

            raw_term = str(
                row["raw_term"]
            ).lower().strip()

            normalized_name = str(
                row["normalized_name"]
            ).lower().strip()

            therapy_type = str(
                row["therapy_type"]
            ).lower().strip()

            if (
                normalized_name == ""
                or normalized_name == "nan"
            ):

                normalized_name = raw_term

            if (
                therapy_type == ""
                or therapy_type == "nan"
            ):

                therapy_type = "unknown"

            self.therapy_lookup[
                raw_term
            ] = {

                "normalized_name": (
                    normalized_name
                ),

                "therapy_type": (
                    therapy_type
                )
            }
    # =====================================================
    # PDF PAGE EXTRACTION
    # =====================================================

    def extract_pages(self, pdf_path):

        doc = fitz.open(pdf_path)

        pages = []

        for page_num, page in enumerate(doc):

            pages.append({
                "page_number": page_num + 1,
                "text": page.get_text()
            })

        return pages

    # =====================================================
    # EXTRACT APPROVAL SECTION
    # =====================================================

    def extract_approval_section(
        self,
        pages
    ):
        print("extracting approval section was used")
        """
        Extract ONLY the approval criteria section
        from the policy document.

        This removes:
        - references
        - clinical studies
        - FDA history
        - background sections
        - experimental sections
        """

        start_patterns = [

            "criteria for initial approval",
            "initial approval",
            "coverage criteria",
            "medical necessity"
        ]

        stop_patterns = [

            "experimental, investigational, or unproven",
            "background",
            "references",
            "coding",
            "appendix",
            "review history",
            "policy history"
        ]

        collecting = False

        collected_text = ""

        collected_pages = []

        for page in pages:

            text = page["text"]

            text_lower = text.lower()

            # -------------------------------------------------
            # START SECTION
            # -------------------------------------------------

            if not collecting:

                for pattern in start_patterns:

                    if pattern in text_lower:

                        collecting = True

                        break

            # -------------------------------------------------
            # COLLECT TEXT
            # -------------------------------------------------

            if collecting:

                stop_found = False

                for stop_pattern in stop_patterns:

                    if stop_pattern in text_lower:

                        stop_found = True
                        break

                if stop_found:

                    break

                collected_text += (
                    f"\n\n===== PAGE "
                    f"{page['page_number']} =====\n"
                )

                collected_text += text

                collected_pages.append(
                    page["page_number"]
                )

        return {

            "approval_text": collected_text,

            "approval_pages": collected_pages
        }

    # =====================================================
    # PAGE SCORING
    # =====================================================

    def score_page(self, page_text, brand):
        print("scoring page was used")
        score = 0

        text_lower = page_text.lower()

        # Brand frequency
        score += (
            text_lower.count(
                brand.lower()
            ) * 15
        )

        # Therapy keyword frequency
        for keyword in self.keywords:

            score += (
                text_lower.count(
                    keyword.lower()
                ) * 3
            )

        return score

    # =====================================================
    # RELEVANT PAGE RETRIEVAL
    # =====================================================

    def get_top_pages(
        self,
        pages,
        brand,
        top_k=6
    ):
        print("getting top pages was used")
        exclusion_patterns = [

            "references",
            "background",
            "clinical trial",
            "study",
            "placebo",
            "double-blind",
            "fda approved",
            "review history"
        ]

        scored_pages = []

        for page in pages:

            text_lower = page[
                "text"
            ].lower()

            # Hard brand filter
            if (
                brand.lower()
                not in text_lower
            ):

                continue

            if any(
                pattern in text_lower
                for pattern in exclusion_patterns
            ):
                continue

            score = self.score_page(
                page["text"],
                brand
            )

            scored_pages.append({

                "page_number": (
                    page["page_number"]
                ),

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
        print("building context was used")
        context = ""

        for page in top_pages:

            context += (
                f"\n\n===== PAGE "
                f"{page['page_number']} =====\n"
            )

            context += page["text"]

            # -----------------------------------------
            # REMOVE NOISY SECTIONS
            # -----------------------------------------

            noise_patterns = [

                r'Related Policies:.*?(?=Refer to)',
                r'References.*',
            ]

            for pattern in noise_patterns:

                context = re.sub(
                    pattern,
                    '',
                    context,
                    flags=re.IGNORECASE | re.DOTALL
                )

        return context

    # =====================================================
    # THERAPY SENTENCE EXTRACTION
    # =====================================================

    def extract_therapy_sentences(
        self,
        context
    ):
        print("extracting therapy sentences was used")
        lines = context.split("\n")

        therapy_sentences = []

        requirement_keywords = [

            "contraindication",
            "intolerance",
            "ineffective response",
            "trial",
            "previously received",
            "criteria is met",
            "failed",
            "failure",
            "step therapy",
            "must have"
        ]

        exclusion_keywords = [

            "related policies",
            "references",
            "overview/summary",
            "prescribing information",
            "scope of policy",
            "review history",
            "background",
            "experimental",
            "investigational",
            "unproven"
        ]

        for line in lines:

            clean_line = line.strip()

            if len(clean_line) < 5:
                continue

            lower_line = clean_line.lower()

            # -----------------------------------------
            # EXCLUSION FILTER
            # -----------------------------------------

            if any(
                exclusion in lower_line
                for exclusion in exclusion_keywords
            ):

                continue

            # -----------------------------------------
            # REQUIREMENT MATCH
            # -----------------------------------------

            requirement_match = any(

                keyword in lower_line

                for keyword in requirement_keywords
            )

            if not requirement_match:
                continue

            # -----------------------------------------
            # THERAPY DETECTION
            # -----------------------------------------

            detected = False

            for therapy in self.known_therapies:

                pattern = (
                    rf'\b{re.escape(therapy)}\b'
                )

                if re.search(
                    pattern,
                    lower_line,
                    re.IGNORECASE
                ):

                    detected = True
                    break

            # -----------------------------------------
            # KEEP LINE
            # -----------------------------------------

            if detected:

                therapy_sentences.append(
                    clean_line
                )

        return list(set(therapy_sentences))

    # =====================================================
    # RAW THERAPY MENTION EXTRACTION
    # =====================================================



    def extract_raw_therapy_mentions(
        self,
        therapy_sentences
    ):
        print("extracting raw therapy mentions was used")
        # ------------------------------------------
        # GUARD 1 — STOPWORDS
        # Common English words that will never be
        # a therapy name regardless of CSV contents.
        # ------------------------------------------
        STOPWORDS = {
            "not", "one", "and", "or", "the",
            "a", "an", "of", "to", "for",
            "with", "in", "is", "at", "by",
            "be", "as", "if", "it", "on"
        }
        # ------------------------------------------
        # GUARD 2 — MINIMUM TERM LENGTH
        # Skips abbreviations/noise under 5 chars.
        # "bsa", "not", "one" all fail this check.
        # ------------------------------------------
        MIN_TERM_LENGTH = 5
        mentions = set()
        for sentence in therapy_sentences:
            lower_sentence = (
                sentence.lower()
            )
            for therapy in self.known_therapies:
                # Guard 1 — skip stopwords
                if therapy.lower() in STOPWORDS:
                    continue
                # Guard 2 — skip short terms
                if len(therapy) < MIN_TERM_LENGTH:
                    continue
                pattern = (
                    rf'\b{re.escape(therapy)}\b'
                )
                if re.search(
                    pattern,
                    lower_sentence,
                    re.IGNORECASE
                ):
                    # Guard 3 — skip unknown types
                    # "topical", "bsa" map to unknown in the
                    # lookup — no therapy type, no match.
                    entry = self.therapy_lookup.get(
                        therapy.lower()
                    )
                    if (
                        not entry
                        or entry["therapy_type"]
                        == "unknown"
                    ):
                        continue
                    mentions.add(
                        therapy.lower()
                    )
        return sorted(
            list(mentions)
        )

    # =====================================================
    # LLM NARRATIVE EXTRACTION
    # =====================================================

    def resolve_step_therapy_with_llm(
        self,
        brand,
        context
    ):
        print("resolving step therapy with llm was used")
        context = context[:18000]

        prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Brand:
{brand}

Relevant Policy Context:
{context}

Your task:
1. Focus ONLY on the target brand.
2. Ignore unrelated brands.
3. Extract ALL step therapy requirements.
4. Preserve clinically important wording.
5. Return concise extraction.
6. Return STRICT JSON ONLY.

Required JSON format:

{{
    "brand": "{brand}",
    "step_therapy_requirements": [
        "<requirement>"
    ],
    "reasoning": "<short reasoning>",
    "confidence": <0-1>
}}
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
        llm_output
    ):
        print("cleaning json output was used")

        llm_output = llm_output.strip()

        # Strip markdown code fences (```json...``` or ```...```)
        llm_output = re.sub(
            r"```(?:json)?\s*",
            "",
            llm_output,
            flags=re.IGNORECASE
        )

        llm_output = llm_output.replace(
            "```",
            ""
        )

        # Extract the first complete JSON object {...}
        # in case the LLM prepends or appends prose
        match = re.search(
            r"\{.*\}",
            llm_output,
            flags=re.DOTALL
        )

        if match:
            return match.group(0).strip()

        return llm_output.strip()

    # =====================================================
    # MAIN EXTRACTION
    # =====================================================

    def extract(
        self,
        pages,
        brand
    ):
        print("main extraction was used")

        try:

            # -----------------------------------------
            # PAGE EXTRACTION
            # -----------------------------------------

            # pages = self.extract_pages(
            #     pdf_path
            # )

            # -----------------------------------------
            # APPROVAL SECTION EXTRACTION
            # -----------------------------------------

            approval_section = (
                self.extract_approval_section(
                    pages
                )
            )

            context = approval_section[
                "approval_text"
            ]

            retrieved_pages = approval_section[
                "approval_pages"
            ]

            # -----------------------------------------
            # NO APPROVAL SECTION FOUND
            # -----------------------------------------

            if (
                context is None
                or len(context.strip()) == 0
            ):

                return {

                    "parameter_group": (
                        "Step Therapy"
                    ),

                    "brand": brand,

                    "logic_type": [],

                    "brand_steps": "NA",

                    "generic_steps": "NA",

                    "phototherapy_required": "NA",

                    "brand_therapies": [],

                    "generic_therapies": [],

                    "reasoning": (
                        "No approval section found"
                    ),

                    "confidence": 0,

                    "retrieved_pages": (
                        retrieved_pages
                    )
                }

            # -----------------------------------------
            # LLM THERAPY EXTRACTION
            # -----------------------------------------

            llm_output = (
                self.extract_step_therapy_requirements_with_llm(
                    brand,
                    context
                )
            )

            cleaned_output = (
                self.clean_json_output(
                    llm_output
                )
            )

            try:
                requirements_output = json.loads(
                    cleaned_output
                )
            except json.JSONDecodeError as json_err:
                raise ValueError(
                    f"LLM (requirements) returned invalid JSON: "
                    f"{json_err}\nRaw output: {cleaned_output[:500]}"
                ) from json_err

            # -----------------------------------------
            # BUILD RAW THERAPY LIST
            # -----------------------------------------

            raw_therapy_mentions = []

            raw_therapy_mentions.extend(
                requirements_output.get(
                    "brand_therapies",
                    []
                )
            )

            raw_therapy_mentions.extend(
                requirements_output.get(
                    "generic_therapies",
                    []
                )
            )

            if requirements_output.get(
                "phototherapy_required",
                False
            ):

                raw_therapy_mentions.append(
                    "phototherapy"
                )

            therapy_sentences = []

            # -----------------------------------------
            # DEBUG CONTEXT
            # -----------------------------------------

            debug_file = (

                f"debug/"
                f"debug_step_therapy_{brand}.txt"
            )

            with open(
                debug_file,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(context)

            # -----------------------------------------
            # LLM EXTRACTION
            # -----------------------------------------

            llm_output = (
                self.resolve_step_therapy_with_llm(
                    brand,
                    context
                )
            )

            cleaned_output = (
                self.clean_json_output(
                    llm_output
                )
            )

            try:
                parsed_output = json.loads(
                    cleaned_output
                )
            except json.JSONDecodeError as json_err:
                raise ValueError(
                    f"LLM (resolve) returned invalid JSON: "
                    f"{json_err}\nRaw output: {cleaned_output[:500]}"
                ) from json_err

            # -----------------------------------------
            # FINAL OUTPUT
            # -----------------------------------------

            return {

                "parameter": (
                    "Step Therapy"
                ),

                "brand": parsed_output.get(
                    "brand",
                    brand
                ),

                "logic_type": requirements_output.get(
                    "logic_type",
                    []
                ),

                "brand_steps": requirements_output.get(
                    "brand_steps"
                ),

                "generic_steps": requirements_output.get(
                    "generic_steps"
                ),

                "phototherapy_required": requirements_output.get(
                    "phototherapy_required"
                ),

                "brand_therapies": requirements_output.get(
                    "brand_therapies",
                    []
                ),

                "generic_therapies": requirements_output.get(
                    "generic_therapies",
                    []
                ),

                "step_therapy_requirements": parsed_output.get(
                    "step_therapy_requirements",
                    []
                ),

                "reasoning": parsed_output.get(
                    "reasoning"
                ),

                "confidence": parsed_output.get(
                    "confidence"
                ),

                "retrieved_pages": (
                    retrieved_pages
                )
            }

        except Exception as e:

            return {

                "parameter_group": (
                    "Step Therapy"
                ),

                "brand": brand,

                "logic_type": "NA",

                "brand_steps": "NA",

                "generic_steps": "NA",

                "phototherapy_required": "NA",

                "brand_therapies": [],

                "generic_therapies": [],

                "reasoning": str(e),

                "confidence": 0,

                "retrieved_pages": []
            }

    # =====================================================
    # LLM THERAPY REQUIREMENT EXTRACTION
    # =====================================================

    def extract_step_therapy_requirements_with_llm(
        self,
        brand,
        context
    ):
        print("extracting step therapy requirements with llm was used")
        context = context[:20000]

        prompt = f"""
        You are analyzing a healthcare prior authorization policy.

        Target Drug:
        {brand}

        Policy Context:
        {context}

        TASK:
        Extract ALL step therapy requirements that apply BEFORE approval
        of the TARGET DRUG and compute final step counts.

        STEP 1 — COLLECT ALL CRITERIA:
        Combine BOTH of the following into one unified requirement set:
        1. Universal criteria (apply across all indications/brands)
        2. Indication-specific criteria for MODERATE-TO-SEVERE PLAQUE PSORIASIS (PsO)
        - If policy separates moderate-to-severe and severe PsO, use ONLY moderate-to-severe.
        These two sets are joined by AND — both must be satisfied.

        STEP 2 — CLASSIFY EACH STEP:
        For each required step in the combined set, classify as:

        BRANDED step if:
        - It names a specific biologic or brand drug
        - It names a drug class AND the target drug belongs to that class
        - It names a preferred ustekinumab or adalimumab product

        GENERIC step if:
        - It names a non-biologic / topical agent
        - It names a required step but does NOT specify a biologic or brand
        (no explicit biologic targeting → defaults to generic)

        PHOTOTHERAPY step if:
        - It mentions phototherapy, PUVA, or UVB
        - Count separately — DO NOT include in brand_steps or generic_steps

        STEP 3 — RESOLVE OR STATEMENTS:
        If steps appear in an OR group, take the LEAST RESTRICTIVE PATH
        (the path with the fewest total steps).
        Count only the steps along that least restrictive path.

        STEP 4 — OUTPUT COUNTS:
        brand_steps   = count of branded/biologic steps on the least restrictive path
        generic_steps = count of generic/non-biologic steps on the least restrictive path
        Both must be an INTEGER or exactly "NA" if none required.

        IGNORE:
        - HCPCS / NDC / billing / dosing-only sections
        - References, background, experimental sections
        - Therapies already established (not required as a prerequisite)

        Return STRICT JSON ONLY:

        {{
            "logic_type": [],
            "brand_therapies": [],
            "generic_therapies": [],
            "brand_steps": "NA",
            "generic_steps": "NA",
            "phototherapy_required": "Yes/No/NA",
            "phototherapy_steps": "NA",
            "reasoning": "",
            "confidence": 0.0
        }}

        RULES:
        - brand_steps and generic_steps must be an INTEGER (e.g. 0, 1, 2) or the string "NA"
        - phototherapy_required must be EXACTLY "Yes", "No", or "NA"
        - Do NOT hallucinate therapies — use ONLY evidence from the provided context
        - Preserve exact policy wording in brand_therapies and generic_therapies lists
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


# =========================================================
# LOCAL TESTING
# =========================================================

if __name__ == "__main__":

    from document_processor import (
        DocumentProcessor
    )

    extractor = (
        StepTherapyExtractor()
    )

    # -------------------------------------------------
    # PDF PATH
    # -------------------------------------------------

    pdf_path = (

        "Sample_PsO_ADS_Track/"
        "377585-4984547.pdf"
    )

    # -------------------------------------------------
    # DOCUMENT PROCESSOR
    # -------------------------------------------------

    document_processor = (
        DocumentProcessor()
    )

    pages = (
        document_processor.process_pdf(
            pdf_path
        )
    )

    # -------------------------------------------------
    # EXTRACTION
    # -------------------------------------------------

    result = extractor.extract(

        pages=pages,

        brand="STELARA"
    )

    # -------------------------------------------------
    # RAW LLM OUTPUT 1 - extract_step_therapy_requirements_with_llm
    # -------------------------------------------------

    approval_context = (
        extractor.extract_approval_section(pages)["approval_text"]
    )

    raw_llm_requirements = (
        extractor.extract_step_therapy_requirements_with_llm(
            brand="STELARA",
            context=approval_context
        )
    )

    print("\n===== RAW LLM OUTPUT 1 (requirements) =====")
    print(raw_llm_requirements)

    cleaned_1 = extractor.clean_json_output(raw_llm_requirements)
    print("\n===== CLEANED JSON 1 (requirements) =====")
    print(cleaned_1)

    # -------------------------------------------------
    # RAW LLM OUTPUT 2 - resolve_step_therapy_with_llm
    # -------------------------------------------------

    raw_llm_resolve = (
        extractor.resolve_step_therapy_with_llm(
            brand="STELARA",
            context=approval_context
        )
    )

    print("\n===== RAW LLM OUTPUT 2 (resolve) =====")
    print(raw_llm_resolve)

    cleaned_2 = extractor.clean_json_output(raw_llm_resolve)
    print("\n===== CLEANED JSON 2 (resolve) =====")
    print(cleaned_2)

    # -------------------------------------------------
    # FINAL RESULT
    # -------------------------------------------------

    print("\n===== FINAL RESULT =====")
    print(

        json.dumps(
            result,
            indent=2
        )
    )