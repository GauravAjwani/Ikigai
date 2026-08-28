"""Who is away. Separate from the decision graph. Memory first, Firestore if GCP is on."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from ikigai.settings import get_settings

_lock = Lock()
_away: dict[str, "Away"] = {}
_items: dict[str, dict[str, "BriefItem"]] = {}
_fs_col = None
_fs_tried = False


@dataclass
class Away:
    user_id: str
    channel_id: str
    at: float
    user_label: str = ""


@dataclass
class BriefItem:
    item_id: str
    title: str
    detail: str
    permalink: str
    channel_name: str = ""
    urgency: str = "later"


def _col():
    global _fs_col, _fs_tried
    if _fs_tried:
        return _fs_col
    _fs_tried = True
    import os

    s = get_settings()
    # Only persist on Cloud Run. Local tests and laptop runs stay in memory.
    if not s.google_cloud_project or not os.environ.get("K_SERVICE"):
        return None
    try:
        from google.cloud import firestore

        _fs_col = firestore.Client(project=s.google_cloud_project).collection("ikigai_presence")
    except Exception:
        _fs_col = None
    return _fs_col


def logout(user_id: str, channel_id: str = "", user_label: str = "", at: float | None = None) -> Away:
    rec = Away(
        user_id=user_id,
        channel_id=channel_id or "",
        at=float(at if at is not None else time.time()),
        user_label=user_label or "",
    )
    with _lock:
        _away[user_id] = rec
        _items.pop(user_id, None)
    col = _col()
    if col is not None and user_id:
        try:
            col.document(user_id).set(
                {
                    "channel_id": rec.channel_id,
                    "at": rec.at,
                    "user_label": rec.user_label,
                    "kind": "away",
                }
            )
        except Exception:
            pass
    return rec


def get_away(user_id: str) -> Away | None:
    with _lock:
        rec = _away.get(user_id)
        if rec:
            return Away(**rec.__dict__)
    col = _col()
    if col is None or not user_id:
        return None
    try:
        snap = col.document(user_id).get()
        data = snap.to_dict() if snap.exists else None
        if not data or data.get("kind") != "away":
            return None
        rec = Away(
            user_id=user_id,
            channel_id=str(data.get("channel_id") or ""),
            at=float(data.get("at") or 0),
            user_label=str(data.get("user_label") or ""),
        )
        with _lock:
            _away[user_id] = rec
        return Away(**rec.__dict__)
    except Exception:
        return None


def clear_away(user_id: str) -> Away | None:
    with _lock:
        rec = _away.pop(user_id, None)
    col = _col()
    if col is not None and user_id:
        try:
            col.document(user_id).delete()
        except Exception:
            pass
    return rec


def save_items(user_id: str, items: list[BriefItem]) -> None:
    with _lock:
        _items[user_id] = {i.item_id: i for i in items}


def get_item(user_id: str, item_id: str) -> BriefItem | None:
    with _lock:
        found = (_items.get(user_id) or {}).get(item_id)
        return BriefItem(**found.__dict__) if found else None


def reset() -> None:
    with _lock:
        _away.clear()
        _items.clear()
