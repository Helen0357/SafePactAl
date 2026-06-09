import logging

from app.schemas.message_schema import GenerateMessageRequest, GenerateMessageResponse
from app.services.message_service import message_service

logger = logging.getLogger(__name__)


async def handle_generate_message(
    request: GenerateMessageRequest,
    header_language: str | None = None,
) -> GenerateMessageResponse:
    """Call message_service and return the generated draft.

    ``header_language`` is the raw X-Language header (or None). The service
    resolves the final draft language with priority: request body 'language' >
    header > session language > 'en'.
    """
    return await message_service.generate_message(request, header_language=header_language)
