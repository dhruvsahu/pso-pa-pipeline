import json
import pandas as pd
from utils.model_router import (
    ModelRouter
)
from utils.extractor_utils import (
    clean_json_output,
    write_debug_context,
    get_brand_aliases,
    sort_by_relevance
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
    # STEP THERAPY RETRIEVAL KEYWORDS
    # =====================================================

    STEP_KEYWORDS = [
        "step therapy",
        "prior therapy",
        "tried and failed",
        "failure of",
        "inadequate response",
        "trial of",
        "must have tried",
        "previously received",
        "previously treated",
        "ineffective or not tolerated",
        "intolerance",
        "failed therapy",
        "criteria for initial",
        "approval criteria",
        "initial approval",
        "coverage criteria",
        "medical necessity",
        "phototherapy",
        "conventional systemic",
        "biologic",
    ]

    STEP_EXCLUSIONS = [
        "policy history",
        "review history",
        "table of contents",
    ]

    # Tight signals used ONLY for sorting collected pages.
    # These appear on actual PA criteria pages but NOT on
    # clinical background / FDA indication table pages.
    # Deliberately excludes broad terms like "biologic",
    # "inadequate response", "phototherapy" that match
    # background sections and skew the ranking.
    STEP_SORT_SIGNALS = [
        "criteria for approval",
        "criteria for initial",
        "initial evaluation",
        "approval criteria",
        "coverage criteria",
        "medical necessity",
        "will be approved",
        "target agent",
        "step 1",
        "step 2",
        "preferred",
        "non-preferred",
        "initial authorization",
        "prior authorization criteria",
    ]

    # =====================================================
    # TWO-PASS KEYWORD RETRIEVAL
    # =====================================================

    def _collect_strict(self, pages, brand):

        collected = []

        aliases = get_brand_aliases(brand)

        for page in pages:

            text = page["text"]
            lower = text.lower()

            if any(
                ex in lower
                for ex in self.STEP_EXCLUSIONS
            ):
                continue

            if (
                any(alias in lower for alias in aliases)
                and any(
                    kw in lower
                    for kw in self.STEP_KEYWORDS
                )
            ):
                collected.append(
                    f"\n\n===== PAGE "
                    f"{page['page_number']} =====\n\n"
                    + text
                )

        return collected

    def _collect_proximity(
        self, pages, brand, window=2
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
            lower = text.lower()

            if any(
                ex in lower
                for ex in self.STEP_EXCLUSIONS
            ):
                continue

            if not any(
                kw in lower
                for kw in self.STEP_KEYWORDS
            ):
                continue

            if any(
                abs(idx - b) <= window
                for b in brand_indices
            ) and page["page_number"] not in seen:

                seen.add(page["page_number"])
                collected.append(
                    f"\n\n===== PAGE "
                    f"{page['page_number']} "
                    f"[proximity] =====\n\n"
                    + text
                )

        return collected

    def retrieve_context(self, pages, brand):
        """
        Primary: strict + proximity run together (union).
        Running both means pages that mention the brand by
        name AND pages adjacent to those that hold the
        criteria text (but don't repeat the brand name) are
        all included before sorting.

        Previously the proximity pass was only a fallback
        for when strict returned nothing — that caused criteria
        pages 2-3 to be missed when page 1 (brand mention in
        header) already satisfied the strict pass.

        Pages are sorted by criteria-signal density so the
        LLM's 20K window sees criteria pages first.
        Fallback: extract_approval_section for single-drug
        dedicated policy docs.
        """

        strict = self._collect_strict(pages, brand)
        proximity = self._collect_proximity(pages, brand)

        # Union — deduplicate by page number extracted from
        # the "===== PAGE N =====" header line.
        import re as _re
        seen_page_nums = set()
        collected = []
        for page_text in strict + proximity:
            m = _re.search(r"===== PAGE (\d+)", page_text)
            key = m.group(1) if m else page_text.strip()[:60]
            if key not in seen_page_nums:
                seen_page_nums.add(key)
                collected.append(page_text)

        if collected:
            collected = sort_by_relevance(
                collected, self.STEP_SORT_SIGNALS
            )
            return "\n".join(collected)

        # Fallback to section-header approach
        approval = self.extract_approval_section(pages)
        return approval.get("approval_text") or ""

    # =====================================================
    # PDF PAGE EXTRACTION
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
            "approval criteria",
            "coverage criteria",
            "medical necessity"
        ]

        stop_patterns = [

            "experimental, investigational, or unproven",
            "background",
            "references",
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
    # STEP COUNTING (deterministic)
    # =====================================================

    def count_steps(self, step_slots):
        """
        Each slot in step_slots represents ONE required step.
        OR alternatives live inside the slot — they don't add steps.
        Returns integer count, or "NA" if no slots exist.
        """

        if not step_slots:
            return "NA"

        return len(step_slots)

    # =====================================================
    # MAIN EXTRACTION
    # =====================================================

    def extract(
        self,
        pages,
        brand,
        pdf_name=""
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
            # CONTEXT RETRIEVAL
            # Two-pass keyword+brand first; section-
            # header approach as fallback.
            # -----------------------------------------

            context = self.retrieve_context(
                pages, brand
            )

            # -----------------------------------------
            # DEBUG CONTEXT
            # Always write before any LLM calls or
            # early returns so every run is traceable.
            # -----------------------------------------

            write_debug_context(
                "step_therapy",
                brand,
                context or "",
                pdf_name
            )

            # -----------------------------------------
            # NO CONTEXT FOUND
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
                        "No step therapy context found"
                    ),

                    "confidence": 0,

                    "retrieved_pages": []
                }

            # -----------------------------------------
            # SINGLE LLM CALL — slots + narrative
            # -----------------------------------------

            llm_output = (
                self.extract_step_therapy_requirements_with_llm(
                    brand,
                    context
                )
            )

            cleaned_output = clean_json_output(llm_output)

            try:
                parsed = json.loads(cleaned_output)
            except json.JSONDecodeError as json_err:
                raise ValueError(
                    f"LLM returned invalid JSON: {json_err}"
                    f"\nRaw output: {llm_output[:600]}"
                ) from json_err

            # -----------------------------------------
            # COMPUTE STEPS FROM SLOTS (deterministic)
            # -----------------------------------------

            brand_step_slots = parsed.get(
                "brand_step_slots", []
            )

            generic_step_slots = parsed.get(
                "generic_step_slots", []
            )

            brand_steps = self.count_steps(brand_step_slots)
            generic_steps = self.count_steps(generic_step_slots)

            brand_therapies = [
                therapy
                for slot in brand_step_slots
                for therapy in slot.get("alternatives", [])
            ]

            generic_therapies = [
                therapy
                for slot in generic_step_slots
                for therapy in slot.get("alternatives", [])
            ]

            # -----------------------------------------
            # FINAL OUTPUT
            # -----------------------------------------

            return {

                "parameter": "Step Therapy",

                "brand": brand,

                "logic_type": [],

                "brand_steps": brand_steps,

                "generic_steps": generic_steps,

                "phototherapy_required": parsed.get(
                    "phototherapy_required", "NA"
                ),

                "brand_therapies": brand_therapies,

                "generic_therapies": generic_therapies,

                "step_therapy_requirements": parsed.get(
                    "step_therapy_requirements", []
                ),

                "reasoning": parsed.get("reasoning"),

                "confidence": parsed.get("confidence"),

                "retrieved_pages": []
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
        - It names a specific BIOLOGIC drug (injectable/infused monoclonal antibody
          or fusion protein — e.g. Humira, Enbrel, Remicade, Cosentyx, Stelara,
          Tremfya, Skyrizi, Taltz, Otezla, Cimzia, Simponi, Siliq, Ilumya)
        - It names a biologic drug CLASS (e.g. "TNF blocker", "IL-17 inhibitor",
          "IL-23 inhibitor") AND the target drug belongs to that class
        - It names a preferred biologic biosimilar product

        GENERIC step if:
        - It names ANY topical agent — regardless of whether it is a brand name
          (Tazorac, Elidel, Protopic, Dovonex) or a generic name
          (tazarotene, pimecrolimus, tacrolimus, calcipotriene)
        - It names a conventional systemic non-biologic
          (methotrexate, cyclosporine, acitretin, apremilast)
        - It names a required step but does NOT specify a biologic
          (no biologic targeting → defaults to generic)

        IMPORTANT: Tazorac, Elidel, Protopic, and similar topical brand names
        are NOT biologics. They MUST go in generic_step_slots, never brand_step_slots.

        PHOTOTHERAPY step if:
        - It mentions phototherapy, PUVA, or UVB
        - Count separately — DO NOT include in brand_step_slots or generic_step_slots

        STEP 3 — GROUP OR ALTERNATIVES INTO SLOTS:
        Each required step = ONE slot.
        If multiple therapies appear as OR alternatives for the SAME step,
        list all alternatives inside ONE slot's "alternatives" list.
        AND requirements between distinct steps each get their own separate slot.

        Example A — sequential AND steps:
        "Must try Humira OR Enbrel, then must try Cosentyx"
        → brand_step_slots: [
              {{"alternatives": ["Humira", "Enbrel"]}},
              {{"alternatives": ["Cosentyx"]}}
          ]
        → brand_steps = 2

        CRITICAL RULE — "AT LEAST N OF [LIST]" PATTERN:
        If the policy says "failed at least N of the following: [list]"
        OR "unresponsive to at least N conventional therapies: [list]"
        OR "inadequate response to N therapies from: [list]"
        this is EXACTLY ONE SLOT — NOT N slots and NOT len(list) slots.
        Put ALL items from the list as alternatives in ONE slot.
        The threshold number (N) does NOT multiply the slot count.

        Example B — "at least N of list":
        "Unresponsive to at least 2 conventional therapies
        (topical corticosteroids, vitamin D analogs, Tazorac,
        topical tacrolimus, Elidel, phototherapy)"
        → generic_step_slots: [
              {{"alternatives": ["topical corticosteroids", "vitamin D analogs",
                                "Tazorac", "topical tacrolimus", "Elidel", "phototherapy"]}}
          ]
        → generic_steps = 1  ← ONE slot, regardless of threshold being 2

        PHOTOTHERAPY RULE:
        Mark phototherapy_required = "Yes" ONLY if phototherapy is listed as
        its OWN standalone sequential step (e.g. "must complete phototherapy course").
        If phototherapy appears as one option INSIDE a parenthetical alternatives list
        (as in Example B above), do NOT set phototherapy_required = "Yes" —
        it is just one alternative within the generic slot.

        STEP THERAPY GRID / TABLE FORMAT:
        Some policies present step therapy as a GRID TABLE where:
        - Rows = indications (e.g. Psoriasis, RA, CD)
        - Columns = step positions (Step 1/Preferred, Step 2, Step 3 ... or N/A)
        - Each cell lists the drugs allowed at that step for that indication

        HOW TO READ A STEP THERAPY GRID:
        1. Find the ROW for Psoriasis (PS) or Plaque Psoriasis (PsO).
        2. Find which COLUMN the target drug appears in.
        3. All drugs in EARLIER columns (lower step number) for the SAME ROW
           are REQUIRED prior steps before the target drug can be approved.
        4. If the target drug is in Column 1 / Step 1 / "Preferred" column:
           → NO prior steps required → brand_step_slots = [], generic_step_slots = []
        5. If the target drug is in Column 2:
           → The Column 1 drugs are required prior steps (1 brand slot if biologics)
        6. If the target drug is in Column 3:
           → Column 1 AND Column 2 drugs are each a required prior step (2 brand slots)

        GRID EXAMPLE:
        Step 1 (Preferred): Humira, Cosentyx, Enbrel, Skyrizi, Tremfya
        Step 2 (N/A): —
        Step 3: Cimzia, Ilumya
        Step 4: Siliq, Taltz, Bimzelx

        For target drug = Humira → brand_step_slots = []  (Step 1, no prior steps)
        For target drug = Siliq  → brand_step_slots = [
              {{"alternatives": ["Humira", "Cosentyx", "Enbrel", "Skyrizi", "Tremfya"]}}
          ]
          (must try one Step 1 biologic first = 1 brand slot)

        IMPORTANT: IGNORE rows for other indications (RA, CD, UC, PsA, etc.)
        Focus ONLY on Psoriasis (PS) / Plaque Psoriasis (PsO) row.

        IGNORE:
        - HCPCS / NDC / billing / dosing-only sections
        - References, background, experimental sections
        - Therapies already established (not required as a prerequisite)

        Return STRICT JSON ONLY:

        {{
            "brand_step_slots": [
                {{"alternatives": ["<drug name>"]}}
            ],
            "generic_step_slots": [
                {{"alternatives": ["<drug name>"]}}
            ],
            "phototherapy_required": "Yes/No/NA",
            "step_therapy_requirements": [
                "<one plain-English sentence per required step, quoting policy wording>"
            ],
            "reasoning": "",
            "confidence": 0.0
        }}

        RULES:
        - Each element in brand_step_slots / generic_step_slots is ONE required step
        - OR alternatives for the same step go inside the same slot's "alternatives" list
        - AND requirements between steps each get their own separate slot
        - "at least N of [list]" → 1 slot containing all list items, NOT N slots
        - Return empty list [] for brand_step_slots or generic_step_slots if none required
        - phototherapy_required must be EXACTLY "Yes", "No", or "NA"
        - step_therapy_requirements: one human-readable sentence per required step,
          preserving exact policy wording where possible
        - Do NOT hallucinate therapies — use ONLY evidence from the provided context
        - Preserve exact policy wording inside alternatives lists
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

    from utils.document_processor import (
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

    raw_llm = (
        extractor.extract_step_therapy_requirements_with_llm(
            brand="STELARA",
            context=approval_context
        )
    )

    print("\n===== RAW LLM OUTPUT =====")
    print(raw_llm)

    cleaned = clean_json_output(raw_llm)
    print("\n===== CLEANED JSON =====")
    print(cleaned)

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