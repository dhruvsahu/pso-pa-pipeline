import fitz
import re
import json
from ollama import chat


PDF_PATH = "Sample_PsO_ADS_Track/195158-4643510.pdf"
TARGET_BRAND = "SKYRIZI"


def extract_text(pdf_path):

    doc = fitz.open(pdf_path)

    text = ""

    for page_num, page in enumerate(doc):

        page_text = page.get_text()

        text += f"\n--- PAGE {page_num + 1} ---\n"
        text += page_text

    return text


def extract_candidate_age_statements(text):

    lines = text.split("\n")

    candidates = []

    patterns = [
        r'years of age or older',
        r'\d+\+',
        r'>=\s*\d+',
        r'greater than or equal to',
        r'adults?',
        r'pediatric',
        r'patients \d+ years and older',
        r'ages \d+ and older'
    ]

    for idx, line in enumerate(lines):

        clean_line = line.strip()

        if len(clean_line) < 5:
            continue

        for pattern in patterns:

            if re.search(pattern, clean_line, re.IGNORECASE):

                candidate = {
                    "line_number": idx,
                    "text": clean_line
                }

                candidates.append(candidate)

                break

    return candidates


def resolve_age_with_llm(brand, candidates):

    formatted_candidates = json.dumps(
        candidates,
        indent=2
    )

    prompt = f"""
You are analyzing a healthcare prior authorization policy.

Target Brand:
{brand}

Candidate Age Statements:
{formatted_candidates}

Your task:
1. Identify the correct age requirement for the target brand.
2. Ignore unrelated brands.
3. Prefer explicit brand-specific rules.
4. If no brand-specific rule exists, use the default/general rule.
5. Return STRICT JSON only.
6. Do not include markdown.
7. Return age in normalized format like ">=<number>"

Required JSON format:
{{
    "brand": "<brand>",
    "resolved_age": ">=<number>",
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


# MAIN FLOW

text = extract_text(PDF_PATH)

candidates = extract_candidate_age_statements(text)

print("\nCANDIDATE STATEMENTS:\n")

for c in candidates:
    print(json.dumps(c, indent=2))


print("\n" + "=" * 80)

resolved_output = resolve_age_with_llm(
    TARGET_BRAND,
    candidates
)

print("\nFINAL JSON OUTPUT:\n")
print(resolved_output)