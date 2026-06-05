from typing import Optional

from fastapi import APIRouter, File, Form, Header, UploadFile

from app.api.handlers.contract_handler import handle_analyze_contract
from app.schemas.contract_schema import AnalyzeResponse

router = APIRouter()


def _norm_lang(value: Optional[str]) -> str:
    """Clamp the X-Language header to the allowed set: 'ar' or 'en' (default 'en')."""
    return "ar" if str(value or "").strip().lower().startswith("ar") else "en"


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze a contract",
    description=(
        "Upload a contract as a PDF file or plain text. "
        "Returns a structured risk report and a session_id for subsequent requests. "
        "Phase 2 implementation."
    ),
)
async def analyze_contract(
    file: Optional[UploadFile] = File(None, description="Contract PDF"),
    text: Optional[str] = Form(None, description="Contract text (alternative to file)"),
    x_language: Optional[str] = Header(None, alias="X-Language"),
):
    return await handle_analyze_contract(file, text, language=_norm_lang(x_language))
