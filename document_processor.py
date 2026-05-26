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

        # ---------------------------------------------
        # LIMIT NEWLINES
        # ---------------------------------------------

        text = re.sub(
            r'\n{3,}',
            '\n\n',
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

        doc = fitz.open(
            pdf_path
        )

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