import fitz
import re


class DocumentProcessor:

    def __init__(self):

        pass

    # =====================================================
    # TEXT CLEANING
    # =====================================================

    def clean_text(
        self,
        text
    ):

        # ---------------------------------------------
        # REMOVE EXCESSIVE NEWLINES
        # ---------------------------------------------

        text = re.sub(
            r'\n\s*\n+',
            '\n',
            text
        )

        # ---------------------------------------------
        # COLLAPSE MULTIPLE SPACES
        # ---------------------------------------------

        text = re.sub(
            r'[ \t]+',
            ' ',
            text
        )

        # ---------------------------------------------
        # REMOVE SPECIAL PDF CHARACTERS
        # ---------------------------------------------

        text = re.sub(
            r'[☒☐®©]',
            '',
            text
        )

        return text.strip()

    # =====================================================
    # PDF PARSING
    # =====================================================

    def process_pdf(
        self,
        pdf_path
    ):

        pages = []

        # Context manager ensures the native C-level file
        # handle and memory-mapped pages are released
        # immediately after extraction, preventing resource
        # leaks across the 79-PDF batch run (P2-11 fix).
        with fitz.open(pdf_path) as doc:

            for i in range(len(doc)):

                raw_text = (
                    doc[i].get_text()
                )

                cleaned_text = (
                    self.clean_text(
                        raw_text
                    )
                )

                pages.append({

                    "page_number": i + 1,

                    "text": cleaned_text
                })

        return pages
