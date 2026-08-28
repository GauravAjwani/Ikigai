from __future__ import annotations

import re

from ikigai.notes import safe_plain
from ikigai.schemas import Card, Verdict

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def one_line(text: str, limit: int = 160) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    line = _SENTENCE.split(t, maxsplit=1)[0].strip()
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


def topic_line(text: str, limit: int = 72) -> str:
    """Short topic, not a pasted Slack quote."""
    t = re.sub(r"<@[^>]+>", "", text or "")
    t = re.sub(r"<#[^>]+>", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip().strip("\"'`")
    t = re.sub(
        r"^(hey|hi|hello|so|um+|uh+|ok(ay)?|yeah|so yeah)[,.\s]+",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"^(let'?s|we should|we need to|we('re| are) going to|i think we (should|need to)|proposal:?|decision:?|call:?)\s+",
        "",
        t,
        flags=re.I,
    )
    return one_line(t, limit) or one_line(text, limit)


def lead_summary(what: str, status: str = "current") -> str:
    body = one_line(what)
    if status == "reversed":
        prefix = "Later reversed"
    elif status == "concurrent":
        prefix = "Two live approaches"
    else:
        prefix = "Already decided"
    if not body:
        return f"{prefix}."
    return f"{prefix} — {body}"


def direct_answer(text: str, limit: int = 280) -> str:
    """One-line summary first; optional second sentence."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    parts = _SENTENCE.split(t, maxsplit=2)
    t = " ".join(p.strip() for p in parts[:2] if p.strip())
    return t[:limit]


def card_from_verdict(v: Verdict) -> Card:
    if v.status == "reversed":
        title = "Heads up — this was later reversed"
        share = f"Ikigai: this call was reversed. {v.what} {v.permalink}".strip()
    elif v.status == "concurrent":
        title = "Two live approaches here"
        share = f"Ikigai: concurrent. {v.what}"
    else:
        title = "This was already decided"
        share = f"Ikigai: {v.what} ({v.permalink})"
    summary = direct_answer(v.answer) or lead_summary(v.what, v.status)
    who = (v.who or "").strip().lstrip("@")
    return Card(
        warning=v.warning,
        title=safe_plain(title, 150) or title,
        status=v.status,
        what=(v.what or "").strip(),
        why=(v.why or "").strip(),
        aftermath=(v.aftermath or v.concurrent_note or "").strip(),
        permalink=v.permalink,
        related_permalinks=v.related_permalinks,
        clarifying_question=v.clarifying_question,
        confidence=v.confidence,
        share_text=share,
        summary=summary,
        who=who,
    )
