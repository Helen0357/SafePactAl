from typing import Optional

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel

from app.api.handlers.report_handler import handle_download_pdf
from app.services.report_service import PDF_FILENAME

router = APIRouter()


class DownloadPdfRequest(BaseModel):
    session_id: str
    language: Optional[str] = None


def _resolve_lang(header: Optional[str], body: Optional[str]) -> str:
    """X-Language header wins, then request-body language, else 'en'. Clamped to en/ar."""
    value = header or body or "en"
    return "ar" if str(value).strip().lower().startswith("ar") else "en"


@router.post(
    "/download-pdf",
    summary="Download the contract risk report as a PDF",
    description=(
        "Generate a clean, landlord-shareable PDF of the analyzed risk report for "
        "the given session. The PDF is built in memory and streamed straight to the "
        "browser — nothing is written to disk or stored. Returns 404 if the session "
        "is unknown, 409 if it has no analyzed report yet."
    ),
    responses={200: {"content": {"application/pdf": {}}, "description": "The PDF report"}},
)
async def download_pdf(
    request: DownloadPdfRequest,
    x_language: Optional[str] = Header(None, alias="X-Language"),
):
    language = _resolve_lang(x_language, request.language)
    pdf_bytes = await handle_download_pdf(request.session_id, language)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{PDF_FILENAME}"'},
    )
