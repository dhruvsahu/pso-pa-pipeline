import os

from utils.document_processor import DocumentProcessor
from extractors.age_extractor import AgeExtractor
from extractors.step_therapy_extractor import StepTherapyExtractor
from extractors.authorization_extractor import AuthorizationExtractor
from extractors.utilization_management_extractor import UtilizationManagementExtractor
from extractors.clinical_access_extractor import ClinicalAccessExtractor
from access_quality_scorer import AccessQualityScorer

# =========================================================
# INITIALIZE ONCE AT IMPORT TIME
# All extractors are stateless — safe to share across
# Flask requests.
# =========================================================

_processor = DocumentProcessor()
_age = AgeExtractor()
_therapy = StepTherapyExtractor()
_auth = AuthorizationExtractor()
_util = UtilizationManagementExtractor()
_clinical = ClinicalAccessExtractor()
_scorer = AccessQualityScorer()


def run_pipeline(pdf_path, brand):
    """
    Generator — yields (step_id, result_dict) after each
    extractor finishes.  The Flask SSE endpoint iterates
    over this and streams each result to the browser.

    Steps (in order):
        age | step_therapy | authorization |
        utilization | clinical_access | score
    """

    pages = _processor.process_pdf(pdf_path)
    pdf_name = os.path.basename(pdf_path)

    # -------------------------------------------------
    # AGE
    # -------------------------------------------------
    age_result = _age.extract(
        pages=pages,
        brand=brand,
        pdf_name=pdf_name
    )
    yield "age", age_result

    # -------------------------------------------------
    # STEP THERAPY
    # -------------------------------------------------
    therapy_result = _therapy.extract(
        pages=pages,
        brand=brand,
        pdf_name=pdf_name
    )
    yield "step_therapy", therapy_result

    # -------------------------------------------------
    # AUTHORIZATION
    # -------------------------------------------------
    auth_result = _auth.extract(
        pages=pages,
        brand=brand,
        pdf_name=pdf_name
    )
    yield "authorization", auth_result

    # -------------------------------------------------
    # UTILIZATION MANAGEMENT
    # -------------------------------------------------
    util_result = _util.extract(
        pages=pages,
        brand=brand,
        pdf_name=pdf_name
    )
    yield "utilization", util_result

    # -------------------------------------------------
    # CLINICAL ACCESS
    # -------------------------------------------------
    clinical_result = _clinical.extract(
        pages=pages,
        brand=brand,
        pdf_name=pdf_name
    )
    yield "clinical_access", clinical_result

    # -------------------------------------------------
    # SCORING
    # -------------------------------------------------
    score_result = _scorer.calculate_score(
        brand=brand,
        step_therapy_result=therapy_result,
        authorization_result=auth_result,
        utilization_result=util_result,
        clinical_access_result=clinical_result,
        age_result=age_result
    )
    yield "score", score_result
