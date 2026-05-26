import fitz
import re
import json
from ollama import chat


PDF_PATH = "Sample_PsO_ADS_Track/195158-4643510.pdf"
TARGET_BRAND = "SIRTURO"


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def extract_text(pdf_path):

    doc = fitz.open(pdf_path)

    print(f"TOTAL PAGES: {len(doc)}")

    full_text = ""

    for page_num, page in enumerate(doc):

        text = page.get_text()

        full_text += f"\n--- PAGE {page_num + 1} ---\n"
        full_text += text
    
    print(f"TOTAL TEXT LENGTH: {len(full_text)}")
    
    return full_text


# =========================================================
# INITIAL CRITERIA SECTION EXTRACTION
# =========================================================

def extract_initial_criteria_section(text):

    start_patterns = [
        "Initial Criteria",
        "INITIAL CRITERIA"
    ]

    end_patterns = [
        "Renewal Criteria",
        "RENEWAL CRITERIA",
        "Policy Guidelines",
        "POLICY GUIDELINES"
    ]

    start_idx = -1
    end_idx = len(text)

    for pattern in start_patterns:

        idx = text.find(pattern)

        if idx != -1:
            start_idx = idx
            break

    if start_idx == -1:
        return text

    for pattern in end_patterns:

        idx = text.find(pattern, start_idx)

        if idx != -1:
            end_idx = idx
            break

    return text[start_idx:end_idx]


# =========================================================
# BRAND CONTEXT WINDOW EXTRACTION
# =========================================================

def extract_brand_windows(section_text, brand, window_size=12):

    lines = section_text.split("\n")

    windows = []

    for idx, line in enumerate(lines):

        if brand.lower() in line.lower():

            start = max(0, idx - window_size)
            end = min(len(lines), idx + window_size)

            context = lines[start:end]

            windows.append({
                "brand_match_line": idx,
                "context": context
            })

    return windows


# =========================================================
# CANDIDATE AGE EXTRACTION
# =========================================================

def extract_candidate_age_statements(windows):

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

    candidates = []

    for window in windows:

        for idx, line in enumerate(window["context"]):

            clean_line = line.strip()

            if len(clean_line) < 5:
                continue

            for pattern in patterns:

                if re.search(pattern, clean_line, re.IGNORECASE):

                    candidates.append({
                        "brand_match_line": window["brand_match_line"],
                        "window_line_number": idx,
                        "text": clean_line
                    })

                    break

    return candidates


# =========================================================
# LLM RESOLUTION
# =========================================================

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
4. If no explicit brand-specific rule exists, use the general/default rule.
5. Return age in normalized format like ">=<number>"
6. Return STRICT JSON only.
7. Do not include markdown.
8. If confidence is low, still choose the best supported answer.

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


# =========================================================
# MAIN FLOW
# =========================================================

text = extract_text(PDF_PATH)

initial_criteria = extract_initial_criteria_section(text)

print("\n" + "=" * 80)
print("INITIAL CRITERIA SECTION")
print("=" * 80)

print(initial_criteria[:5000])

windows = extract_brand_windows(
    initial_criteria,
    TARGET_BRAND
)

print("\n" + "=" * 80)
print("BRAND WINDOWS FOUND")
print("=" * 80)

print(f"Total Windows: {len(windows)}")

candidates = extract_candidate_age_statements(windows)

print("\n" + "=" * 80)
print("CANDIDATE AGE STATEMENTS")
print("=" * 80)

for c in candidates:
    print(json.dumps(c, indent=2))

print("\n" + "=" * 80)
print("FINAL LLM OUTPUT")
print("=" * 80)

final_output = resolve_age_with_llm(
    TARGET_BRAND,
    candidates
)

print(final_output)