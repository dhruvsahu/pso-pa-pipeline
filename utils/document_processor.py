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

        # Note: a previous `\n{3,} → \n\n` pass was removed here — it was
        # unreachable, since the first substitution above already collapses
        # every run of blank lines to a single '\n'.

        return text.strip()

    # =====================================================
    # PDF PARSING
    # =====================================================

    def process_pdf(
        self,
        pdf_path
    ):

        # Context manager ensures the native PyMuPDF handle is released
        # even if parsing raises — important across the 79-PDF batch.
        with fitz.open(pdf_path) as doc:

            pages = []

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
