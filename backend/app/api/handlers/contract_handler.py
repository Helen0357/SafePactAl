import logging
from typing import Optional

from fastapi import HTTPException, UploadFile

from app.schemas.contract_schema import AnalyzeResponse
from app.schemas.risk_schema import RiskReport
from app.services.contract_service import contract_service

logger = logging.getLogger(__name__)


async def handle_analyze_contract(
    file: Optional[UploadFile],
    text: Optional[str],
    language: str = "en",
) -> AnalyzeResponse:
    """Validate input, call contract_service, return AnalyzeResponse.
    language ('en'|'ar') comes from the X-Language header and controls whether the
    user-facing risk fields are returned in Arabic."""
    if file is not None:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        filename = file.filename or "contract"
        lower = filename.lower()
        if lower.endswith(".txt"):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                text_content = content.decode("latin-1", errors="replace")
            session = await contract_service.analyze_from_text(text_content, language=language)
        elif lower.endswith(".docx"):
            session = await contract_service.analyze_from_docx(content, filename, language=language)
        elif lower.endswith(".pdf"):
            session = await contract_service.analyze_from_pdf(content, filename, language=language)
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload a PDF, DOCX, or TXT file.",
            )
    elif text and text.strip():
        session = await contract_service.analyze_from_text(text.strip(), language=language)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either a PDF file (field: 'file') or contract text (field: 'text').",
        )

    # session.risk_report is a plain dict from model_dump(mode='json').
    # Reconstruct the typed RiskReport for the response schema.
    return AnalyzeResponse(
        session_id=session.session_id,
        risk_report=RiskReport(**session.risk_report),
    )
