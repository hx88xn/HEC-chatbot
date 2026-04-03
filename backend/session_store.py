from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionData:
    session_id: str
    marksheet_text: str | None = None
    marksheet_summary: str | None = None
    history: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)


_sessions: dict[str, SessionData] = {}


def get_or_create(session_id: str) -> SessionData:
    if session_id not in _sessions:
        _sessions[session_id] = SessionData(session_id=session_id)
    session = _sessions[session_id]
    session.last_active = datetime.utcnow()
    return session


def get(session_id: str) -> SessionData | None:
    return _sessions.get(session_id)


def update_marksheet(session_id: str, text: str, summary: str) -> None:
    session = get_or_create(session_id)
    session.marksheet_text = text
    session.marksheet_summary = summary


def append_history(session_id: str, role: str, content: str) -> None:
    session = get_or_create(session_id)
    session.history.append({"role": role, "content": content})


def cleanup_old_sessions(max_age_hours: int = 2) -> None:
    cutoff = datetime.utcnow()
    to_delete = [
        sid
        for sid, s in _sessions.items()
        if (cutoff - s.last_active).total_seconds() > max_age_hours * 3600
    ]
    for sid in to_delete:
        del _sessions[sid]
