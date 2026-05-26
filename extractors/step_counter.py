import re
import json
import pandas as pd

from extractors.step_therapy_extractor import (
    StepTherapyExtractor
)


class StepCounter:

    def __init__(self, therapy_dictionary_path):

        self.therapy_df = pd.read_csv(
            therapy_dictionary_path
        )

        self.therapy_lookup = (
            self.build_lookup()
        )

    # =====================================================
    # BUILD THERAPY LOOKUP
    # =====================================================

    def build_lookup(self):

        lookup = {}

        for _, row in self.therapy_df.iterrows():

            raw_term = str(
                row["raw_term"]
            ).lower().strip()

            normalized_name = str(
                row["normalized_name"]
            ).lower().strip()

            therapy_type = str(
                row["therapy_type"]
            ).lower().strip()

            # ---------------------------------------------
            # FALLBACK NORMALIZATION
            # ---------------------------------------------

            if (
                normalized_name == ""
                or normalized_name == "nan"
            ):

                normalized_name = raw_term

            # ---------------------------------------------
            # FALLBACK TYPE INFERENCE
            # ---------------------------------------------

            if (
                therapy_type == ""
                or therapy_type == "nan"
            ):

                if (
                    raw_term.endswith("mab")
                    or raw_term.endswith("cept")
                    or raw_term.endswith("nib")
                ):

                    therapy_type = "brand"

                elif raw_term in [
                    "methotrexate",
                    "mtx",
                    "cyclosporine",
                    "acitretin"
                ]:

                    therapy_type = "generic"

                elif raw_term in [
                    "phototherapy",
                    "uvb",
                    "puva"
                ]:

                    therapy_type = "phototherapy"

                else:

                    therapy_type = "unknown"

            lookup[raw_term] = {
                "normalized_name": normalized_name,
                "therapy_type": therapy_type
            }

        return lookup

    # =====================================================
    # DETECT LOGIC TYPE
    # =====================================================

    def detect_logic_type(self, therapy_sentences):

        combined_text = " ".join(
            therapy_sentences
        ).lower()

        # -------------------------------------------------
        # TRUE OR GROUPS
        # -------------------------------------------------

        or_patterns = [
            "one of the following",
            "at least one",
            "any of the following",
            "one or more"
        ]

        for pattern in or_patterns:

            if pattern in combined_text:

                return "OR"

        # -------------------------------------------------
        # OTHERWISE DEFAULT TO AND
        # -------------------------------------------------

        return "AND"

    # =====================================================
    # MAP RAW MENTIONS
    # =====================================================

    def map_therapy_mentions(
        self,
        mentions
    ):

        mapped_mentions = []

        for mention in mentions:

            # =================================================
            # OR GROUP
            # =================================================

            if isinstance(
                mention,
                list
            ):

                group = []

                for therapy in mention:

                    therapy = (
                        therapy.lower()
                        .strip()
                    )

                    entry = (
                        self.therapy_lookup.get(
                            therapy
                        )
                    )

                    if entry:

                        group.append({

                            "raw_term": therapy,

                            "normalized_name": (
                                entry[
                                    "normalized_name"
                                ]
                            ),

                            "therapy_type": (
                                entry[
                                    "therapy_type"
                                ]
                            )
                        })

                if len(group) > 0:

                    mapped_mentions.append(
                        group
                    )

            # =================================================
            # SINGLE THERAPY
            # =================================================

            else:

                mention = (
                    mention.lower()
                    .strip()
                )

                entry = (
                    self.therapy_lookup.get(
                        mention
                    )
                )

                if entry:

                    mapped_mentions.append({

                        "raw_term": mention,

                        "normalized_name": (
                            entry[
                                "normalized_name"
                            ]
                        ),

                        "therapy_type": (
                            entry[
                                "therapy_type"
                            ]
                        )
                    })

        return mapped_mentions

    # =====================================================
    # REMOVE DUPLICATES
    # =====================================================

    def deduplicate_therapies(
        self,
        therapies
    ):

        deduped = []

        seen = set()

        for therapy in therapies:

            # =================================================
            # OR GROUP
            # =================================================

            if isinstance(
                therapy,
                list
            ):

                group = []

                group_keys = []

                for item in therapy:

                    key = (

                        item[
                            "normalized_name"
                        ],

                        item[
                            "therapy_type"
                        ]
                    )

                    if key not in seen:

                        seen.add(key)

                        group.append(item)

                        group_keys.append(
                            str(key)
                        )

                if len(group) > 0:

                    deduped.append(group)

            # =================================================
            # SINGLE THERAPY
            # =================================================

            else:

                key = (

                    therapy[
                        "normalized_name"
                    ],

                    therapy[
                        "therapy_type"
                    ]
                )

                if key not in seen:

                    seen.add(key)

                    deduped.append(
                        therapy
                    )

        return deduped

    # =====================================================
    # COUNT STEPS
    # =====================================================

    def count_steps_by_type(
        self,
        therapies
    ):

        brand_steps = 0

        generic_steps = 0

        phototherapy_steps = 0

        for therapy in therapies:

            # =================================================
            # OR GROUP
            # =================================================

            if isinstance(
                therapy,
                list
            ):

                therapy_types = set(

                    item[
                        "therapy_type"
                    ]

                    for item in therapy
                )

                # ---------------------------------------------
                # OR group counts as ONE step
                # ---------------------------------------------

                if "brand" in therapy_types:

                    brand_steps += 1

                elif "generic" in therapy_types:

                    generic_steps += 1

                elif "phototherapy" in therapy_types:

                    phototherapy_steps += 1

            # =================================================
            # SINGLE THERAPY
            # =================================================

            else:

                therapy_type = therapy[
                    "therapy_type"
                ]

                if therapy_type == "brand":

                    brand_steps += 1

                elif therapy_type == "generic":

                    generic_steps += 1

                elif therapy_type == "phototherapy":

                    phototherapy_steps += 1

        return {

            "brand_steps": (
                brand_steps
            ),

            "generic_steps": (
                generic_steps
            ),

            "phototherapy_steps": (
                phototherapy_steps
            )
        }

    # =====================================================
    # MAIN EXTRACTION
    # =====================================================

    def extract(
        self,
        therapy_sentences,
        raw_therapy_mentions
    ):

        # -------------------------------------------------
        # LOGIC TYPE
        # -------------------------------------------------

        logic_type = self.detect_logic_type(
            therapy_sentences
        )

        # -------------------------------------------------
        # MAP THERAPIES
        # -------------------------------------------------

        mapped_therapies = (
            self.map_therapy_mentions(
                raw_therapy_mentions
            )
        )

        # -------------------------------------------------
        # DEDUPLICATE
        # -------------------------------------------------

        mapped_therapies = (
            self.deduplicate_therapies(
                mapped_therapies
            )
        )

        # -------------------------------------------------
        # COUNT STEPS
        # -------------------------------------------------

        step_counts = (
            self.count_steps_by_type(
                mapped_therapies
            )
        )

        # -------------------------------------------------
        # FINAL OUTPUT
        # -------------------------------------------------

        return {

            "parameter": (
                "Therapy Step Counts"
            ),

            "logic_type": logic_type,

            "brand_steps": (
                step_counts[
                    "brand_steps"
                ]
            ),

            "generic_steps": (
                step_counts[
                    "generic_steps"
                ]
            ),

            "phototherapy_steps": (
                step_counts[
                    "phototherapy_steps"
                ]
            ),

            "detected_therapies": (
                mapped_therapies
            )
        }


# =========================================================
# LOCAL TESTING
# =========================================================

if __name__ == "__main__":

    PDF_PATH = (
        "Sample_PsO_ADS_Track/"
        "148593-4960549.pdf"
    )

    TARGET_BRAND = "STELARA"

    # -----------------------------------------------------
    # STEP 1 — THERAPY EXTRACTION
    # -----------------------------------------------------

    therapy_extractor = (
        StepTherapyExtractor()
    )

    therapy_result = (
        therapy_extractor.extract(
            pdf_path=PDF_PATH,
            brand=TARGET_BRAND
        )
    )

    print("\n" + "=" * 80)
    print("THERAPY EXTRACTION")
    print("=" * 80)

    print(
        json.dumps(
            therapy_result,
            indent=2
        )
    )

    # -----------------------------------------------------
    # STEP 2 — STEP COUNTING
    # -----------------------------------------------------

    counter = StepCounter(
        therapy_dictionary_path=(
            "assets/therapy_dictionary_normalized.csv"
        )
    )

    result = counter.extract(

        therapy_sentences=(
            therapy_result[
                "therapy_sentences"
            ]
        ),

        raw_therapy_mentions=(
            therapy_result[
                "raw_therapy_mentions"
            ]
        )
    )

    print("\n" + "=" * 80)
    print("FINAL STEP COUNTS")
    print("=" * 80)

    print(
        json.dumps(
            result,
            indent=2
        )
    )