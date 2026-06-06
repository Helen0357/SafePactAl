from typing import Optional

from fastapi import APIRouter, Header

from app.api.handlers.message_handler import handle_generate_message
from app.schemas.message_schema import GenerateMessageRequest, GenerateMessageResponse

router = APIRouter()


def _norm_lang(value: Optional[str]) -> str:
    """Clamp the X-Language header to the allowed set: 'ar' or 'en' (default 'en')."""
    return "ar" if str(value or "").strip().lower().startswith("ar") else "en"


@router.post(
    "/generate-message",
    response_model=GenerateMessageResponse,
    summary="Generate a message from selected risks",
    description=(
        "Generate a professional message (email or WhatsApp) targeting one or more "
        "identified contract risks. Supports clarification, negotiation, rejection, "
        "and amendment request types. Phase 3 implementation. The X-Language header "
        "('ar' or 'en') controls the language of the generated draft."
    ),
)
async def generate_message(
    request: GenerateMessageRequest,
    x_language: Optional[str] = Header(None, alias="X-Language"),
):
    return await handle_generate_message(request, language=_norm_lang(x_language))
