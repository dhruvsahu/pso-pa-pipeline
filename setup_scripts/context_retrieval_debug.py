import fitz
import re
from ollama import chat
import json

# PDF_PATH = "Sample_PsO_ADS_Track/8898-4735285.pdf"
# TARGET_BRAND = "STELARA"

PDF_PATH = "Sample_PsO_ADS_Track/163262-4627017.pdf"
TARGET_BRAND = "BIMZELX"

# =========================================================
# PAGE SCORING CONFIG
# =========================================================

KEYWORDS = [
    "initial criteria",
    "age",
    "years of age",
    "pediatric",
    "adult",
    "approval",
    "authorization"
]


# =========================================================
# PAGE EXTRACTION
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

    # Brand match
    if brand.lower() in text_lower:
        score += 10

    # Keyword scoring
    for keyword in KEYWORDS:

        if keyword.lower() in text_lower:
            score += 2

    # Bonus for explicit age phrases
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
# GET TOP PAGES
# =========================================================

def get_top_pages(pages, brand, top_k=5):

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

def build_context(top_pages):

    context = ""

    for page in top_pages:

        context += f"\n\n===== PAGE {page['page_number']} =====\n"
        context += page["text"]

    return context


def resolve_age_with_llm(brand, context):

    prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Brand:
{brand}

Relevant Policy Context:
{context}

Your task:
1. Determine whether an age restriction exists.
2. Ignore unrelated brands.
3. Focus ONLY on the target brand.
4. If no age restriction exists, return "No Age Restriction".
5. If age restriction exists, return normalized format like ">=<number>".
6. Use only evidence from the provided context.
7. Return STRICT JSON only.
8. Do not include markdown.

Required JSON format:
{{
    "brand": "<brand>",
    "age_restriction_exists": true/false,
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
# MAIN
# =========================================================

pages = extract_pages(PDF_PATH)

print(f"\nTOTAL PAGES: {len(pages)}")

top_pages = get_top_pages(
    pages,
    TARGET_BRAND,
    top_k=3
)

print("\n" + "=" * 80)
print("TOP RELEVANT PAGES")
print("=" * 80)

for page in top_pages:

    print("\n")
    print("=" * 40)
    print(f"PAGE: {page['page_number']}")
    print(f"SCORE: {page['score']}")
    print("=" * 40)

    preview = page["text"][:2000]

    print(preview)

context = build_context(top_pages)

print("\n" + "=" * 80)
print("FINAL CONTEXT SENT TO LLM")
print("=" * 80)

print(context[:6000])

print("\n" + "=" * 80)
print("LLM OUTPUT")
print("=" * 80)

result = resolve_age_with_llm(
    TARGET_BRAND,
    context
)

print(result)