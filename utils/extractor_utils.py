import re
import os


def clean_json_output(text):
    """
    Strip markdown code fences and extract the first valid JSON object.

    Handles:
    - ```json ... ``` wrappers
    - ``` ... ``` wrappers
    - Prose before or after the JSON block
    """

    text = text.strip()

    text = re.sub(
        r"```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = text.replace("```", "")

    # Extract the first complete JSON object {...}
    # in case the LLM prepends or appends prose
    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL
    )

    if match:
        return match.group(0).strip()

    return text.strip()


def write_debug_context(
    extractor_name,
    brand,
    context,
    pdf_name=""
):
    """
    Write retrieved context to a debug txt file.

    Filename format:
        debug/debug_{extractor_name}_{brand}_{pdf_stem}.txt
        e.g. debug/debug_utilization_STELARA_378692-5003182.txt

    Falls back to:
        debug/debug_{extractor_name}_{brand}.txt
        if pdf_name is not provided.

    Creates the debug/ directory if it does not exist.
    """

    os.makedirs("debug", exist_ok=True)

    # Strip directory and extension from pdf_name
    pdf_stem = (
        os.path.splitext(
            os.path.basename(pdf_name)
        )[0]
        if pdf_name
        else ""
    )

    parts = ["debug", extractor_name, brand]

    if pdf_stem:
        parts.append(pdf_stem)

    filename = "_".join(parts) + ".txt"

    debug_path = os.path.join("debug", filename)

    with open(
        debug_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(context)
