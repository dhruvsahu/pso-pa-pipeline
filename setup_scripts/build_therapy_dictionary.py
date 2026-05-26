import fitz
import re
import pandas as pd
from pathlib import Path


# =========================================================
# CONFIG
# =========================================================

PDF_FOLDER = "Sample_PsO_ADS_Track"

OUTPUT_CSV = "therapy_dictionary.csv"

THERAPY_KEYWORDS = [
    "methotrexate",
    "cyclosporine",
    "acitretin",
    "adalimumab",
    "ustekinumab",
    "secukinumab",
    "ixekizumab",
    "guselkumab",
    "etanercept",
    "phototherapy",
    "uvb",
    "puva",
    "biologic",
    "systemic therapy",
    "targeted synthetic"
]

# Additional therapy regex patterns
THERAPY_PATTERNS = [
    r'\b[a-zA-Z]+mab\b',
    r'\b[a-zA-Z]+nib\b',
    r'\b[a-zA-Z]+cept\b',
    r'\bphototherapy\b',
    r'\bPUVA\b',
    r'\bUVB\b'
]


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def extract_text(pdf_path):

    doc = fitz.open(pdf_path)

    text = ""

    for page in doc:

        text += page.get_text()

    return text


# =========================================================
# THERAPY SENTENCE EXTRACTION
# =========================================================

def extract_therapy_sentences(text):

    lines = text.split("\n")

    therapy_lines = []

    for line in lines:

        clean_line = line.strip()

        if len(clean_line) < 10:
            continue

        lower_line = clean_line.lower()

        # Keyword matches
        matched = False

        for keyword in THERAPY_KEYWORDS:

            if keyword.lower() in lower_line:

                matched = True
                break

        # Regex pattern matches
        if not matched:

            for pattern in THERAPY_PATTERNS:

                if re.search(
                    pattern,
                    clean_line,
                    re.IGNORECASE
                ):

                    matched = True
                    break

        if matched:

            therapy_lines.append(clean_line)

    return therapy_lines


# =========================================================
# TERM EXTRACTION
# =========================================================

def extract_possible_therapy_terms(line):

    terms = []

    patterns = [

        # monoclonal antibodies
        r'\b[a-zA-Z]+mab\b',

        # biologics
        r'\b[a-zA-Z]+cept\b',

        # kinase inhibitors
        r'\b[a-zA-Z]+nib\b',

        # all caps abbreviations
        r'\b[A-Z]{2,10}\b',

        # common therapy words
        r'\bphototherapy\b',
        r'\bPUVA\b',
        r'\bUVB\b',

        # generic drug style words
        r'\b[a-zA-Z]+trexate\b',
        r'\b[a-zA-Z]+sporine\b',
        r'\b[a-zA-Z]+retin\b'
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            line
        )

        for match in matches:

            cleaned = (
                match
                .strip()
                .lower()
            )

            if len(cleaned) > 2:

                terms.append(cleaned)

    return list(set(terms))

# =========================================================
# THERAPY TYPE GUESSING
# =========================================================

def guess_therapy_type(term):

    phototherapy_terms = [
        "phototherapy",
        "uvb",
        "puva"
    ]

    generic_terms = [
        "methotrexate",
        "cyclosporine",
        "acitretin"
    ]

    if term.lower() in phototherapy_terms:

        return "phototherapy"

    if term.lower() in generic_terms:

        return "generic"

    # Heuristic:
    # biologics often end with mab / cept
    if (
        term.endswith("mab")
        or term.endswith("cept")
    ):

        return "brand"

    return "unknown"


# =========================================================
# MAIN
# =========================================================

all_records = []

pdf_files = list(
    Path(PDF_FOLDER).glob("*.pdf")
)

print(f"\nTOTAL PDFS FOUND: {len(pdf_files)}")

for idx, pdf_path in enumerate(pdf_files):

    print(
        f"\n[{idx + 1}/{len(pdf_files)}] "
        f"PROCESSING: {pdf_path.name}"
    )

    try:

        text = extract_text(pdf_path)

        therapy_lines = extract_therapy_sentences(
            text
        )

        for line in therapy_lines:

            terms = extract_possible_therapy_terms(
                line
            )

            for term in terms:

                record = {
                    "raw_term": term,
                    "normalized_name": "",
                    "therapy_type": guess_therapy_type(term),
                    "source_pdf": pdf_path.name,
                    "source_line": line
                }

                all_records.append(record)

    except Exception as e:

        print(f"FAILED: {e}")


# =========================================================
# CREATE DATAFRAME
# =========================================================

df = pd.DataFrame(all_records)

# Remove duplicates
# df = df.drop_duplicates(
#     subset=["raw_term"]
# )

# Sort
df = df.sort_values(
    by="raw_term"
)

term_counts = (
    df["raw_term"]
    .value_counts()
    .reset_index()
)

term_counts.columns = [
    "raw_term",
    "frequency"
]

df = df.merge(
    term_counts,
    on="raw_term",
    how="left"
)

print("\nEXTRACTED TERMS:\n")

print(df.head(50))

# =========================================================
# SAVE CSV
# =========================================================

df.to_csv(
    OUTPUT_CSV,
    index=False
)

print(f"\nSaved: {OUTPUT_CSV}")