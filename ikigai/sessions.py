"""In-memory private chats. User IDs never go to the decision graph."""

from __future__ import annotations

from threading import Lock

_MAX_TURNS = 12
_lock = Lock()
_sessions: dict[str, dict] = {}


def start(user_id: str, *, source_channel: str, source_permalink: str = "") -> dict:
    with _lock:
        rec = {
            "source_channel": source_channel,
            "source_permalink": source_permalink,
            "turns": [],
        }
        _sessions[user_id] = rec
        return rec


def get(user_id: str) -> dict | None:
    with _lock:
        rec = _sessions.get(user_id)
        return dict(rec) if rec else None


def append(user_id: str, role: str, text: str) -> None:
    text = (text or "").strip()
    if not user_id or not text:
        return
    with _lock:
        rec = _sessions.setdefault(user_id, {"source_channel": "", "source_permalink": "", "turns": []})
        rec["turns"].append({"role": role, "text": text[:800]})
        rec["turns"] = rec["turns"][-_MAX_TURNS:]


def prompt_with_history(user_id: str, latest: str) -> str:
    """Build a search prompt that includes the private follow-up thread."""
    rec = get(user_id)
    latest = (latest or "").strip()
    if not rec or not rec.get("turns"):
        return latest
    lines = []
    src = rec.get("source_channel") or ""
    if src:
        lines.append(f"Conversation context from Slack channel {src}.")
    for turn in rec["turns"][-8:]:
        who = "User" if turn["role"] == "user" else "Ikigai"
        lines.append(f"{who}: {turn['text']}")
    lines.append(f"User: {latest}")
    lines.append(
        "First understand this conversation. Then answer the latest user message "
        "from prior decisions. Do not paste raw Slack quotes."
    )
    return "\n".join(lines)
