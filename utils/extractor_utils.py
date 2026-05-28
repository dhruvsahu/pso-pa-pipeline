import re
import os

# ---------------------------------------------------------
# BRAND → GENERIC NAME MAPPING
# Used so retrieval works when a payer's QL table, formulary
# section, or criteria doc lists the generic name instead of
# the brand (e.g. "Ustekinumab 45 mg" instead of "STELARA").
# ---------------------------------------------------------

BRAND_TO_GENERIC = {
    "stelara":    "ustekinumab",
    "humira":     "adalimumab",
    "amjevita":   "adalimumab",   # adalimumab biosimilar
    "hadlima":    "adalimumab",
    "hyrimoz":    "adalimumab",
    "cyltezo":    "adalimumab",
    "cosentyx":   "secukinumab",
    "taltz":      "ixekizumab",
    "skyrizi":    "risankizumab",
    "tremfya":    "guselkumab",
    "bimzelx":    "bimekizumab",
    "siliq":      "brodalumab",
    "ilumya":     "tildrakizumab",
    "spevigo":    "spesolimab",
    "sotyktu":    "deucravacitinib",
    "otezla":     "apremilast",
    "remicade":   "infliximab",
    "enbrel":     "etanercept",
    "cimzia":     "certolizumab",
    "simponi":    "golimumab",
    "kevzara":    "sarilumab",
    "orencia":    "abatacept",
}


def get_brand_aliases(brand):
    """
    Return a list of lowercase search terms for `brand`.
    Always includes the brand itself; adds the generic name
    when one is known so retrieval works on documents that
    use generic names in their formulary tables.
    """
    brand_lower = brand.lower()
    aliases = [brand_lower]
    generic = BRAND_TO_GENERIC.get(brand_lower)
    if generic:
        aliases.append(generic)
    return aliases


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


def sort_by_relevance(collected_pages, signal_keywords):
    """
    Re-order collected context pages so the most relevant ones
    appear first — before the LLM's 20K-char truncation window
    cuts off.

    Relevance = number of signal_keywords found in the page text.
    Pages that match more keywords (actual criteria pages) float
    to the top; background / FDA-indication table pages sink to
    the bottom and get truncated instead.

    Each extractor passes its own retrieval_keywords list so the
    scoring is tuned to that extractor's content type.
    """
    def _score(page_text):
        lower = page_text.lower()
        return sum(
            1 for kw in signal_keywords
            if kw in lower
        )

    return sorted(
        collected_pages,
        key=_score,
        reverse=True
    )


def collect_wide_fallback(
    pages,
    brand,
    keywords,
    exclusions,
    window=10
):
    """
    Last-resort fallback for large multi-drug formulary
    documents where the target brand appears in a list/
    table far from the criteria section.

    Collects pages containing any of `keywords` that are
    within `window` pages of ANY brand-mention page.
    Uses a wider window (default ±10) than the standard
    proximity pass (±2).

    Called only when both strict and ±2-proximity passes
    return empty.
    """

    aliases = get_brand_aliases(brand)

    brand_indices = {
        idx for idx, p in enumerate(pages)
        if any(alias in p["text"].lower() for alias in aliases)
    }

    if not brand_indices:
        return []

    collected = []
    seen = set()

    for idx, page in enumerate(pages):

        text = page["text"]
        lower = text.lower()

        if any(ex in lower for ex in exclusions):
            continue

        if not any(kw in lower for kw in keywords):
            continue

        near = any(
            abs(idx - b) <= window
            for b in brand_indices
        )

        if near and page["page_number"] not in seen:
            seen.add(page["page_number"])
            collected.append(
                f"\n\n===== PAGE "
                f"{page['page_number']} "
                f"[wide-fallback] =====\n\n"
                + text
            )

    return collected


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
