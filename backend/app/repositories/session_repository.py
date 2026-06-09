import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.repositories.base_repository import BaseRepository
from app.schemas.session_schema import Session
from app.core.config import settings

logger = logging.getLogger(__name__)


class SessionRepository(BaseRepository[Session]):
    """
    In-memory session store for MVP.
    Thread-safe (concurrent WebSocket connections use the same store).
    Replace _store with Redis to scale beyond a single process.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._store.get(session_id)

    def create(self, session: Optional[Session] = None) -> Session:
        new_session = session or Session()
        with self._lock:
            self._store[new_session.session_id] = new_session
        logger.info("Session created: %s", new_session.session_id)
        return new_session

    def update(self, session_id: str, **kwargs) -> Optional[Session]:
        with self._lock:
            session = self._store.get(session_id)
            if not session:
                return None
            updated = session.model_copy(
                update={**kwargs, "last_activity": datetime.utcnow()}
            )
            self._store[session_id] = updated
            return updated

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                logger.info("Session deleted: %s", session_id)
                return True
            return False

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._store

    def cleanup_expired(self) -> int:
        """Remove sessions idle beyond TTL. Returns the count removed."""
        cutoff = datetime.utcnow() - timedelta(minutes=settings.session_ttl_minutes)
        expired = []
        with self._lock:
            for sid, session in self._store.items():
                if session.last_activity < cutoff:
                    expired.append(sid)
            for sid in expired:
                del self._store[sid]
        if expired:
            logger.info("Cleaned up %d expired session(s).", len(expired))
        return len(expired)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._store)


session_repository = SessionRepository()
