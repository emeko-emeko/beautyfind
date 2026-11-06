"""Session management and state storage for the Telegram bot."""

import time
import uuid

SESSIONS: dict[str, dict] = {}
LAST_TOKEN: dict[int, str] = {}


def new_session(chat_id: int, ttl: int, **data) -> str:
    now = time.time()
    for t in [t for t, s in SESSIONS.items() if now - s["ts"] > ttl]:
        SESSIONS.pop(t, None)
    while len(SESSIONS) > 300:
        SESSIONS.pop(next(iter(SESSIONS)))
    token = uuid.uuid4().hex[:8]
    SESSIONS[token] = {"chat_id": chat_id, "shown": 0, "ts": now, **data}
    LAST_TOKEN[chat_id] = token
    return token
