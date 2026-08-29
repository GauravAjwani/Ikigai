"""Catch-up briefing for /ikigai login. One Gemini pass; facts only."""

from __future__ import annotations

import re

from ikigai.cards import topic_line
from ikigai.gemini_client import GeminiError, generate_json
from ikigai.notes import for_prompt, notable, pack_messages, untrusted
from ikigai.prefilter import is_chatter, is_decision_call
from ikigai.presence import BriefItem
from ikigai.schemas import Briefing, BriefingItem, SlackMessage
from ikigai.settings import get_settings
from ikigai.slack_store import SlackStore

BRIEF_PROMPT = """You are Ikigai. Read the notes. Fill JSON.
Warm, like a teammate who's glad they're back. Concise. Not a story.
Name who made each call. Paraphrase. Never quote. Never invent permalinks.
Never say you could not read messages.

Prefer later outcomes when a thread changed its mind. Greeting MUST match {daypart}.
Name: {name}. Scope: {scope}.
Away unix {away_at}. Now unix {now_at}.

Working notes (copy permalinks exactly):
{messages}

JSON:
- greeting: one warm line matching {daypart}, using their name if you have it
- happened: one-line summary first, then 2-4 short factual lines (newlines): who, what, outcome
- attention: unused, leave empty
- rest: unused, leave empty
- items: 0-8 actual decisions or calls only
  - item_id: i1, i2, ...
  - title: the decision, max 12 words, not a quote
  - detail: @username of who proposed it, nothing else
  - permalink: copied exactly from the notes
  - channel_name: if known
"""


def daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def farewell(hour: int) -> str:
    part = daypart(hour)
    if part == "evening" or part == "night":
        lead = "Have a good evening. Rest well."
    elif part == "afternoon":
        lead = "Enjoy the rest of your afternoon."
    else:
        lead = "Have a good one."
    return (
        f"{lead} I'll keep an eye on this chat. When you're back, `/ikigai login` "
        "and I'll catch you up — only you will see it."
    )


def default_greeting(hour: int, name: str = "") -> str:
    who = f", {name}" if name and name not in {"you", "member"} else ""
    part = daypart(hour)
    if part == "morning":
        return f"Good morning{who}. Glad you're here."
    if part == "afternoon":
        return f"Good afternoon{who}. Welcome back."
    if part == "evening":
        return f"Welcome back{who}. Hope the evening's treating you kindly."
    return f"Welcome back{who}. Hope you got some rest."


def collect_since(
    store: SlackStore,
    *,
    channel_id: str,
    oldest: float,
    all_channels: bool,
    limit: int = 24,
) -> list[SlackMessage]:
    oldest_s = str(oldest)
    rows: list[SlackMessage] = []
    seen: set[tuple[str, str]] = set()

    def _add(msgs: list[SlackMessage]) -> None:
        for m in msgs:
            key = (m.channel_id, m.ts)
            if key in seen:
                continue
            seen.add(key)
            rows.append(m)

    if channel_id:
        try:
            _add(store.history(channel_id, oldest=oldest_s))
        except Exception:
            pass
    if all_channels:
        try:
            others = list(store.channels())
        except Exception:
            others = []
        # Live Slack: cap history fan-out. Fixture Replay must see every chat.
        if type(store).__name__ != "FixtureSlack":
            others = others[:12]
        for ch in others:
            if channel_id and ch.id == channel_id:
                continue
            try:
                _add(store.history(ch.id, oldest=oldest_s))
            except Exception:
                continue
    rows.sort(key=lambda m: m.ts)
    out = rows[-limit:]
    for m in out:
        if m.permalink:
            continue
        try:
            m.permalink = store.permalink(m.channel_id, m.ts)
        except Exception:
            continue
    return out


def _topic(text: str, limit: int = 72) -> str:
    return topic_line(text, limit=limit)


_READ_FAIL = re.compile(
    r"couldn'?t read|could not read|unable to read|can'?t read|"
    r"don'?t have access|do not have access|failed to (read|fetch|load)",
    re.I,
)


def _looks_unread(text: str) -> bool:
    return bool(_READ_FAIL.search(text or ""))


def _decision_pool(messages: list[SlackMessage]) -> list[SlackMessage]:
    seen: set[str] = set()
    out: list[SlackMessage] = []
    for m in messages:
        if not is_decision_call(m.text) or is_chatter(m.text):
            continue
        key = f"{m.channel_id}:{m.thread_ts or m.ts}"
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def _item_from(m: SlackMessage, idx: int) -> BriefingItem:
    who = (m.user_label or "").strip().lstrip("@")
    title = _topic(m.text)[:60] or "Decision"
    return BriefingItem(
        item_id=f"i{idx}",
        title=title,
        detail=f"@{who}" if who else "",
        urgency="now",
        permalink=m.permalink,
        channel_name=m.channel_name,
    )


def fallback_briefing(
    messages: list[SlackMessage],
    *,
    hour: int,
    name: str,
    scope: str,
) -> Briefing:
    greeting = default_greeting(hour, name)
    meat = _decision_pool(messages)
    seen = notable(messages)
    if not seen and not meat:
        if messages:
            n = len(messages)
            happened = (
                f"{n} message{'s' if n != 1 else ''} while you were away — "
                "nothing that looks like a new call."
            )
        else:
            happened = "Quiet while you were away — nothing new to catch up on."
        return Briefing(
            greeting=greeting,
            happened=happened,
            attention="",
            rest="",
            items=[],
        )
    bits = []
    for m in seen[-8:]:
        who = (m.user_label or "someone").strip().lstrip("@")
        bits.append(f"@{who} — {_topic(m.text, 70).rstrip('.')}.")
    happened = "Here's what happened.\n" + "\n".join(bits[:6])
    items = [_item_from(m, i + 1) for i, m in enumerate(meat[:8])]
    if not meat:
        happened = happened.rstrip() + "\nNo new calls locked."
    return Briefing(
        greeting=greeting,
        happened=happened.strip(),
        attention="",
        rest="",
        items=items,
    )


def build_briefing(
    messages: list[SlackMessage],
    *,
    hour: int,
    name: str,
    scope: str,
    away_at: float,
    now_at: float,
) -> Briefing:
    seen = notable(messages)
    meat = _decision_pool(messages)
    if not seen and not meat:
        return fallback_briefing(messages, hour=hour, name=name, scope=scope)
    blob = pack_messages(seen or meat, limit=24, each=180)
    s = get_settings()
    try:
        result, _model = generate_json(
            stage="login-reply",
            model=s.adjudicate_model,
            fallback=s.fallback_adjudicate_model,
            prompt=BRIEF_PROMPT.format(
                daypart=daypart(hour),
                name=for_prompt(name or "teammate", 80),
                scope=for_prompt(scope, 80),
                away_at=int(away_at),
                now_at=int(now_at),
                messages=untrusted(blob, 6200),
            ),
            schema=Briefing,
            thinking="LOW",
        )
        if isinstance(result, Briefing):
            pool = seen or meat
            allowed = {m.permalink for m in pool if m.permalink}
            by_link = {m.permalink: m for m in pool if m.permalink}
            clean = []
            for it in result.items:
                if it.permalink and it.permalink not in allowed:
                    continue
                src = by_link.get(it.permalink)
                if src and src.user_label:
                    it.detail = "@" + src.user_label.lstrip("@")
                if src and not (it.title or "").strip():
                    it.title = _topic(src.text)[:60]
                clean.append(it)
            result.items = clean[:8]
            result.attention = ""
            result.rest = ""
            if not (result.greeting or "").strip():
                result.greeting = default_greeting(hour, name)
            quiet = not (result.happened or "").strip() or "nothing new to catch up" in (
                result.happened or ""
            ).lower()
            unread = _looks_unread(f"{result.happened or ''} {result.greeting or ''}")
            fb = fallback_briefing(messages, hour=hour, name=name, scope=scope)
            if quiet or unread:
                result.happened = fb.happened
            if unread:
                result.greeting = fb.greeting
            if not result.items:
                result.items = fb.items
            return result
    except (GeminiError, Exception):
        pass
    return fallback_briefing(messages, hour=hour, name=name, scope=scope)


def as_items(briefing: Briefing) -> list[BriefItem]:
    out: list[BriefItem] = []
    for it in briefing.items:
        iid = (it.item_id or f"i{len(out)+1}")[:24]
        out.append(
            BriefItem(
                item_id=iid,
                title=(it.title or "Open thread")[:75],
                detail=it.detail or it.title,
                permalink=it.permalink,
                channel_name=it.channel_name,
                urgency=it.urgency or "later",
            )
        )
        it.item_id = iid
    return out
