import logging

from fastapi import HTTPException

from app.repositories.session_repository import session_repository
from app.services.report_service import generate_risk_report_pdf

logger = logging.getLogger(__name__)


async def handle_download_pdf(session_id: str, language: str = "en") -> bytes:
    """Return the risk-report PDF bytes for a session (in memory, nothing stored).

    Raises:
        404 — session not found (e.g. expired / wrong id).
        409 — session exists but has no analyzed risk_report yet.
    """
    if not session_repository.exists(session_id):
        raise HTTPException(
            status_code=404,
            detail="Session not found. Please analyze the contract again.",
        )

    session = session_repository.get(session_id)
    if not session or not session.risk_report:
        raise HTTPException(
            status_code=409,
            detail="No risk report available for this session. Please analyze a contract first.",
        )

    try:
        return generate_risk_report_pdf(session.risk_report, language=language or "en")
    except Exception as exc:  # noqa: BLE001 — never leak a stack trace to the client
        logger.error("[Report] PDF generation failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to generate the PDF report.") from exc
