import fitz

pdf_path = "Sample_PsO_ADS_Track/8898-4735285.pdf"

doc = fitz.open(pdf_path)

print(f"Pages: {len(doc)}")

for i in range(min(5, len(doc))):
    page = doc[i]
    text = page.get_text()

    print("\n")
    print("=" * 80)
    print(f"PAGE {i+1}")
    print("=" * 80)

    print(text[:4000])