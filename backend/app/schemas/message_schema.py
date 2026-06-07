from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, field_validator


class MessageType(str, Enum):
    CLARIFICATION = "clarification"
    NEGOTIATION = "negotiation"
    REJECTION = "rejection"
    AMENDMENT_REQUEST = "amendment_request"


class MessageTone(str, Enum):
    POLITE = "polite"
    FIRM = "firm"
    PROFESSIONAL = "professional"


class MessageFormat(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


# Defensive aliases: the frontend sends canonical English values, but if Arabic
# display labels (or English display labels) ever reach the API they are mapped to
# the canonical enum value here so message type/tone/format always resolve correctly.
_TYPE_ALIASES = {
    "استفسار": "clarification", "توضيح": "clarification", "clarify": "clarification",
    "تفاوض": "negotiation", "negotiate": "negotiation",
    "رفض": "rejection", "reject": "rejection",
    "تعديل": "amendment_request", "amendment": "amendment_request", "amend": "amendment_request",
}
_TONE_ALIASES = {
    "رسمي": "professional", "احترافي": "professional", "pro": "professional",
    "حازم": "firm",
    "لطيف": "polite", "مهذب": "polite",
}
_FORMAT_ALIASES = {
    "بريد": "email", "بريد إلكتروني": "email", "إيميل": "email", "ايميل": "email",
    "واتساب": "whatsapp", "واتس اب": "whatsapp", "واتس": "whatsapp", "رسالة": "whatsapp",
}


def _normalize_choice(value, aliases):
    """Map an Arabic/display label to its canonical enum value; pass through
    canonical values (lowercased) and leave unknown values for enum validation."""
    if not isinstance(value, str):
        return value
    key = value.strip()
    if key in aliases:            # exact match (Arabic labels)
        return aliases[key]
    low = key.lower()
    return aliases.get(low, low)  # English alias, else assume canonical


class GenerateMessageRequest(BaseModel):
    session_id: str
    clause_ids: List[str]
    message_type: MessageType = MessageType.CLARIFICATION
    tone: MessageTone = MessageTone.PROFESSIONAL
    format: MessageFormat = MessageFormat.EMAIL
    extra_instruction: Optional[str] = None

    @field_validator("message_type", mode="before")
    @classmethod
    def _norm_message_type(cls, v):
        return _normalize_choice(v, _TYPE_ALIASES)

    @field_validator("tone", mode="before")
    @classmethod
    def _norm_tone(cls, v):
        return _normalize_choice(v, _TONE_ALIASES)

    @field_validator("format", mode="before")
    @classmethod
    def _norm_format(cls, v):
        return _normalize_choice(v, _FORMAT_ALIASES)


class GenerateMessageResponse(BaseModel):
    draft: str
    session_id: str
    clause_ids: List[str]
    message_type: str
    tone: str
    format: str
