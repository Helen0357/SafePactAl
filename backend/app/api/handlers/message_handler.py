import logging

from app.schemas.message_schema import GenerateMessageRequest, GenerateMessageResponse
from app.services.message_service import message_service

logger = logging.getLogger(__name__)


async def handle_generate_message(
    request: GenerateMessageRequest,
    language: str = "en",
) -> GenerateMessageResponse:
    """Call message_service and return the generated draft.

    ``language`` ('ar' or 'en', from the X-Language header) controls the
    language of the generated draft.
    """
    return await message_service.generate_message(request, language=language)
