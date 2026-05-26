import fitz
import re
import json
import pandas as pd
from pathlib import Path
from ollama import chat


# =========================================================
# CONFIG
# =========================================================

PDF_FOLDER = "Sample_PsO_ADS_Track"

TEST_CASES = [
    ("8898-4735285.pdf", "STELARA"),
    # ("163262-4627017.pdf", "BIMZELX"),
    # ("167126-4508319.pdf", "TREMFYA"),
    # ("176207-4867884.pdf", "TREMFYA"),
    # ("176806-5005129.pdf", "STELARA"),
    # ("176810-4889390.pdf", "TREMFYA"),
    # ("183953-4805567.pdf", "TREMFYA"),
    # ("187701-5050284.pdf", "TREMFYA"),
    # ("195158-4643510.pdf", "SKYRIZI"),
    # ("195239-4641478.pdf", "OTEZLA"),
    # ("203402-5001149.pdf", "YESINTEK")
]

KEYWORDS = [
    "initial criteria",
    "age restrictions",
    "years of age",
    "pediatric",
    "adult",
    "authorization",
    "approval"
]


# =========================================================
# PDF PAGE EXTRACTION
# =========================================================

def extract_pages(pdf_path):

    doc = fitz.open(pdf_path)

    pages = []

    for page_num, page in enumerate(doc):

        text = page.get_text()

        pages.append({
            "page_number": page_num + 1,
            "text": text
        })

    return pages


# =========================================================
# PAGE SCORING
# =========================================================

def score_page(page_text, brand):

    score = 0

    text_lower = page_text.lower()

    # Brand weighting
    brand_matches = text_lower.count(brand.lower())

    score += brand_matches * 20

    # Keyword scoring
    for keyword in KEYWORDS:

        keyword_matches = text_lower.count(keyword.lower())

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


# =========================================================
# RELEVANT PAGE RETRIEVAL
# =========================================================

def get_top_pages(pages, brand, top_k=3):

    scored_pages = []

    for page in pages:

        text_lower = page["text"].lower()

        # HARD BRAND FILTER
        if brand.lower() not in text_lower:
            continue

        score = score_page(
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


# =========================================================
# CONTEXT BUILDING
# =========================================================

def build_context(top_pages):

    context = ""

    for page in top_pages:

        context += f"\n\n===== PAGE {page['page_number']} =====\n"
        context += page["text"]

    return context


# =========================================================
# LLM RESOLUTION
# =========================================================

def resolve_age_with_llm(brand, context):

    context = context[:12000]

    prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Brand:
{brand}

Relevant Policy Context:
{context}

Your task:
1. Focus ONLY on the target brand.
2. Ignore unrelated brands.
3. Determine the applicable age restriction.
4. If no age restriction exists, return:
   "No Age Restriction"
5. If age restriction exists, return normalized format like:
   ">=18"
6. Use only evidence from the provided context.
7. Return STRICT JSON only.
8. Do not include markdown or explanations outside JSON.

Required JSON format:
{{
    "brand": "<brand>",
    "resolved_age": ">=<number>" OR "No Age Restriction",
    "source_statement": "<exact supporting statement>",
    "reasoning": "<short explanation>",
    "confidence": <0-1 score>
}}
"""

    response = chat(
        model='qwen2.5:7b',
        messages=[
            {
                'role': 'user',
                'content': prompt
            }
        ]
    )

    return response.message.content


# =========================================================
# MAIN BATCH PIPELINE
# =========================================================

results = []

for pdf_name, brand in TEST_CASES:

    print("\n" + "=" * 80)
    print(f"PROCESSING: {pdf_name} | {brand}")
    print("=" * 80)

    pdf_path = Path(PDF_FOLDER) / pdf_name

    try:

        # ---------------------------------------------
        # Extract Pages
        # ---------------------------------------------

        pages = extract_pages(pdf_path)

        print(f"TOTAL PAGES: {len(pages)}")

        # ---------------------------------------------
        # Retrieve Relevant Pages
        # ---------------------------------------------

        top_pages = get_top_pages(
            pages,
            brand,
            top_k=3
        )

        print(f"RELEVANT PAGES FOUND: {len(top_pages)}")

        if len(top_pages) == 0:

            results.append({
                "pdf": pdf_name,
                "brand": brand,
                "resolved_age": "NO BRAND MATCH FOUND",
                "source_statement": None,
                "reasoning": "Brand not found in document",
                "confidence": 0
            })

            continue

        # ---------------------------------------------
        # Build Context
        # ---------------------------------------------

        context = build_context(top_pages)

        # ---------------------------------------------
        # Save Raw Context (Optional Debugging)
        # ---------------------------------------------

        debug_context_path = f"debug_context_{brand}_{pdf_name}.txt"

        with open(debug_context_path, "w", encoding="utf-8") as f:
            f.write(context)

        # ---------------------------------------------
        # LLM Extraction
        # ---------------------------------------------

        llm_output = resolve_age_with_llm(
            brand,
            context
        )

        print("\nRAW LLM OUTPUT:\n")
        print(llm_output)

        # ---------------------------------------------
        # JSON Cleanup
        # ---------------------------------------------

        llm_output = llm_output.strip()

        llm_output = llm_output.replace(
            "```json",
            ""
        )

        llm_output = llm_output.replace(
            "```",
            ""
        )

        # ---------------------------------------------
        # Parse JSON
        # ---------------------------------------------

        parsed_output = json.loads(llm_output)

        parsed_output["pdf"] = pdf_name

        parsed_output["retrieved_pages"] = [
            p["page_number"] for p in top_pages
        ]

        results.append(parsed_output)

        print("\nSUCCESS")

    except Exception as e:

        print(f"\nFAILED: {e}")

        results.append({
            "pdf": pdf_name,
            "brand": brand,
            "resolved_age": None,
            "source_statement": None,
            "reasoning": str(e),
            "confidence": 0
        })


# =========================================================
# FINAL RESULTS
# =========================================================

df = pd.DataFrame(results)

print("\n" + "=" * 80)
print("FINAL RESULTS")
print("=" * 80)

print(df)

df.to_csv(
    "age_extraction_results.csv",
    index=False
)

print("\nSaved: age_extraction_results.csv")