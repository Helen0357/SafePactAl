import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: str 
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GeneratedMessage(BaseModel):
    clause_ids: List[str]
    message_type: str
    tone: str
    format: str
    draft: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contract_text: Optional[str] = None
    risk_report: Optional[Dict[str, Any]] = None
    active_clause_id: Optional[str] = None
    selected_clause_ids: List[str] = Field(default_factory=list)
    language: str = "en"  
    conversation_history: List[ConversationMessage] = Field(default_factory=list)
    generated_messages: List[GeneratedMessage] = Field(default_factory=list)
    debug_logs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
