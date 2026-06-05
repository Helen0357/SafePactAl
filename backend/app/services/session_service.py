import logging
from datetime import datetime

from app.core.exceptions import SessionNotFoundError
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import ConversationMessage, GeneratedMessage, Session

logger = logging.getLogger(__name__)


class SessionService:
    """Manages session lifecycle and state mutations."""

    def create_session(self) -> Session:
        return session_repository.create()

    def get_session(self, session_id: str) -> Session:
        session = session_repository.get(session_id)
        if not session:
            raise SessionNotFoundError(session_id)
        return session

    def set_active_clause(self, session_id: str, active_clause_id: str) -> Session:
        updated = session_repository.update(session_id, active_clause_id=active_clause_id)
        if not updated:
            raise SessionNotFoundError(session_id)
        logger.debug("Active clause set [%s] → %s", session_id, active_clause_id)
        return updated

    def set_selected_clauses(self, session_id: str, selected_clause_ids: list[str]) -> Session:
        ids = [c for c in (selected_clause_ids or []) if c]
        updated = session_repository.update(session_id, selected_clause_ids=ids)
        if not updated:
            raise SessionNotFoundError(session_id)
        logger.debug("Selected clauses set [%s] → %s", session_id, ",".join(ids) or "(none)")
        return updated

    def add_debug_log(self, session_id: str, entry: str) -> None:
        session = session_repository.get(session_id)
        if session:
            session_repository.update(
                session_id,
                debug_logs=session.debug_logs + [f"[{datetime.utcnow().isoformat()}] {entry}"],
            )

    def add_conversation_turn(self, session_id: str, role: str, content: str) -> None:
        session = session_repository.get(session_id)
        if session:
            message = ConversationMessage(role=role, content=content)
            session_repository.update(
                session_id,
                conversation_history=session.conversation_history + [message],
            )

    def add_generated_message(self, session_id: str, message: GeneratedMessage) -> None:
        session = session_repository.get(session_id)
        if session:
            session_repository.update(
                session_id,
                generated_messages=session.generated_messages + [message],
            )

    def cleanup_expired_sessions(self) -> int:
        return session_repository.cleanup_expired()


session_service = SessionService()
