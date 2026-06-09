from typing import Optional

from fastapi import APIRouter, Header

from app.api.handlers.message_handler import handle_generate_message
from app.schemas.message_schema import GenerateMessageRequest, GenerateMessageResponse

router = APIRouter()


@router.post(
    "/generate-message",
    response_model=GenerateMessageResponse,
    summary="Generate a message from selected risks",
    description=(
        "Generate a professional message (email or WhatsApp) targeting one or more "
        "identified contract risks. Supports clarification, negotiation, rejection, "
        "and amendment request types. The draft language is resolved with priority: "
        "request body 'language' > X-Language header > session language > 'en'."
    ),
)
async def generate_message(
    request: GenerateMessageRequest,
    x_language: Optional[str] = Header(None, alias="X-Language"),
):
    return await handle_generate_message(request, header_language=x_language)
