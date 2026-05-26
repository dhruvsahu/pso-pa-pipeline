import json
import pandas as pd
from ollama import chat


# =========================================================
# CONFIG
# =========================================================

INPUT_CSV = "therapy_dictionary.csv"

OUTPUT_CSV = "therapy_dictionary_normalized.csv"

MODEL_NAME = "qwen2.5:7b"


# =========================================================
# LLM NORMALIZATION
# =========================================================

def normalize_therapy(
    raw_term,
    source_line
):

    prompt = f"""
You are normalizing healthcare therapy names.

Your task:
1. Determine the canonical therapy name.
2. Determine therapy type.

Allowed therapy types:
- brand
- generic
- phototherapy
- unknown

Normalization Rules:
- Normalize generic biologic names to brand names if obvious.
- MTX should normalize to methotrexate.
- UVB/PUVA should normalize to phototherapy.
- If uncertain, preserve original term.

Raw Therapy:
{raw_term}

Source Context:
{source_line}

Return STRICT JSON ONLY.

Required format:

{{
    "normalized_name": "<canonical_name>",
    "therapy_type": "<therapy_type>"
}}
"""

    try:

        response = chat(

            model=MODEL_NAME,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = (
            response.message.content
            .strip()
            .replace("```json", "")
            .replace("```", "")
        )

        parsed = json.loads(content)

        return {

            "normalized_name": parsed.get(
                "normalized_name",
                raw_term.lower()
            ).lower(),

            "therapy_type": parsed.get(
                "therapy_type",
                "unknown"
            ).lower()
        }

    except Exception as e:

        print(
            f"\nFAILED: {raw_term}"
        )

        print(e)

        return {

            "normalized_name": (
                raw_term.lower()
            ),

            "therapy_type": "unknown"
        }


# =========================================================
# SELECT BEST CONTEXT
# =========================================================

def select_best_context(group):

    """
    Select highest quality context line
    for normalization.
    """

    best_line = ""

    best_score = -1

    for line in group["source_line"]:

        line = str(line)

        score = 0

        # Strong signal:
        # brand + generic pair
        if "(" in line and ")" in line:

            score += 5

        # Drug formatting clues
        if "/" in line:

            score += 2

        # Longer informative lines
        score += min(
            len(line) / 100,
            5
        )

        if score > best_score:

            best_score = score
            best_line = line

    return best_line


# =========================================================
# MAIN
# =========================================================

def main():

    df = pd.read_csv(INPUT_CSV)

    # ---------------------------------------------
    # Ensure Required Columns
    # ---------------------------------------------

    required_columns = [

        "raw_term",
        "normalized_name",
        "therapy_type",
        "source_line"
    ]

    for col in required_columns:

        if col not in df.columns:

            df[col] = ""

    # ---------------------------------------------
    # UNIQUE THERAPIES ONLY
    # ---------------------------------------------

    unique_terms = (
        df["raw_term"]
        .dropna()
        .astype(str)
        .str.lower()
        .str.strip()
        .unique()
    )

    print(
        f"\nUNIQUE THERAPIES: "
        f"{len(unique_terms)}"
    )

    # ---------------------------------------------
    # BUILD NORMALIZATION LOOKUP
    # ---------------------------------------------

    normalization_lookup = {}

    for idx, raw_term in enumerate(unique_terms):

        # -----------------------------------------
        # Skip Existing Fully Normalized Terms
        # -----------------------------------------

        existing_rows = df[
            df["raw_term"]
            .str.lower()
            .str.strip()
            == raw_term
        ]

        existing_normalized = (
            existing_rows[
                "normalized_name"
            ]
            .dropna()
            .astype(str)
            .str.strip()
        )

        existing_types = (
            existing_rows[
                "therapy_type"
            ]
            .dropna()
            .astype(str)
            .str.strip()
        )

        already_done = (

            len(existing_normalized) > 0

            and

            any(
                x.lower() != "nan"
                and x != ""
                for x in existing_normalized
            )

            and

            len(existing_types) > 0

            and

            any(
                x.lower() != "nan"
                and x != ""
                for x in existing_types
            )
        )

        if already_done:

            normalized_name = (
                existing_normalized.iloc[0]
            )

            therapy_type = (
                existing_types.iloc[0]
            )

            normalization_lookup[
                raw_term
            ] = {

                "normalized_name": (
                    normalized_name
                ),

                "therapy_type": (
                    therapy_type
                )
            }

            continue

        # -----------------------------------------
        # Select Best Context
        # -----------------------------------------

        best_context = (
            select_best_context(
                existing_rows
            )
        )

        print(
            f"\n[{idx + 1}/"
            f"{len(unique_terms)}] "
            f"Normalizing: {raw_term}"
        )

        # -----------------------------------------
        # LLM NORMALIZATION
        # -----------------------------------------

        result = normalize_therapy(
            raw_term,
            best_context
        )

        normalization_lookup[
            raw_term
        ] = result

    # =====================================================
    # APPLY LOOKUP TO ALL ROWS
    # =====================================================

    print("\nApplying normalization...")

    for idx, row in df.iterrows():

        raw_term = str(
            row["raw_term"]
        ).lower().strip()

        if raw_term in normalization_lookup:

            df.at[
                idx,
                "normalized_name"
            ] = normalization_lookup[
                raw_term
            ][
                "normalized_name"
            ]

            df.at[
                idx,
                "therapy_type"
            ] = normalization_lookup[
                raw_term
            ][
                "therapy_type"
            ]

    # =====================================================
    # SAVE OUTPUT
    # =====================================================

    df.to_csv(
        OUTPUT_CSV,
        index=False
    )

    print("\nDONE")

    print(
        f"Saved: {OUTPUT_CSV}"
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()