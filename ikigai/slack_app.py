from __future__ import annotations

import asyncio
import concurrent.futures
import re
import time
from datetime import datetime
from threading import Lock

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from ikigai import presence, sessions
from ikigai.briefing import as_items, build_briefing, collect_since, default_greeting, farewell
from ikigai.graph import graph
from ikigai.pipeline import run_pipeline
from ikigai.notes import safe_mrkdwn, safe_plain, user_error
from ikigai.prefilter import is_trivial_prompt
from ikigai.schemas import Briefing, Trigger
from ikigai.settings import get_settings
from ikigai.slack_store import slack_store
from ikigai.stances import PersonCheck, check_person, extract_person_query

s = get_settings()
bolt = App(
    token=s.slack_bot_token or "xoxb-not-set",
    signing_secret=s.slack_signing_secret or "not-set",
    # ACK in <3s, then lazy work posts via response_url. Waiting for Gemini
    # here is what Slack surfaces as operation_timeout.
    process_before_response=False,
    token_verification_enabled=False,
)
handler = SlackRequestHandler(bolt)
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
_MENTION = re.compile(r"<@[^>]+>\s*")
_handled: dict[str, float] = {}
_handled_lock = Lock()
_bot_uid = ""
_claim_col = None
_claim_tried = False


SEARCHING = "Searching decision history…"
CATCHING_UP = "Catching you up…"


def _blocks(card) -> list[dict]:
    warn = card.warning == "warning"
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": safe_plain(card.title, 150) or "Ikigai"},
        },
    ]
    lead = (getattr(card, "summary", "") or "").strip()
    if lead:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": safe_mrkdwn(lead, 1800)},
            }
        )
    now = (card.aftermath or card.why or "").strip()
    fields = [
        {"type": "mrkdwn", "text": safe_mrkdwn(f"*Status*\n`{card.status}`", 800)},
    ]
    if card.confidence:
        pct = f"{card.confidence:.0%}"
        fields.append({"type": "mrkdwn", "text": safe_mrkdwn(f"*Confidence*\n{pct}", 800)})
    who = (getattr(card, "who", "") or "").strip().lstrip("@")
    if who:
        fields.append({"type": "mrkdwn", "text": safe_mrkdwn(f"*Who*\n@{who}", 800)})
    if now and now.lower() not in (lead or "").lower():
        fields.append({"type": "mrkdwn", "text": safe_mrkdwn(f"*Now*\n{now}", 1200)})
    for i in range(0, len(fields), 2):
        blocks.append({"type": "section", "fields": fields[i : i + 2]})
    q = (getattr(card, "clarifying_question", "") or "").strip()
    if q:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": safe_mrkdwn(f"*Open question*\n{q}", 1200)},
            }
        )
    if card.permalink:
        where = getattr(card, "channel_name", "") or ""
        thread_line = f"<{card.permalink}|Open thread>"
        if where:
            thread_line = f"#{where} · {thread_line}"
        blocks.append(
        {
            "type": "section",
                "text": {"type": "mrkdwn", "text": thread_line},
            }
        )
    if getattr(card, "decision_id", ""):
        blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not the same decision"},
                    "action_id": "not_same",
                    "value": (card.decision_id or "unknown")[:80],
                },
            ],
            }
        )
    if warn:
        blocks.insert(
            1,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":warning: Following this may recreate a failure the org already paid for.",
                },
            },
        )
    return blocks


def _run(
    text: str,
    path: str,
    channel: str,
    thread: str | None = None,
    permalink: str = "",
    all_channels: bool = False,
):
    coro = run_pipeline(
        Trigger(
            text=text,
            path=path,
            channel_id=channel,
            thread_ts=thread,
            permalink=permalink,
            all_channels=all_channels,
        )
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _pool.submit(asyncio.run, coro).result()


def _event_key(event: dict, body: dict | None = None) -> str:
    """Stable id for one Slack delivery. Retries reuse event_id."""
    body = body or {}
    raw = (
        str(body.get("event_id") or "")
        or str(event.get("client_msg_id") or "")
        or str(event.get("event_ts") or "")
        or f"{event.get('channel') or ''}:{event.get('ts') or ''}"
    )
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)[:200]


def _firestore_claims():
    global _claim_col, _claim_tried
    if _claim_tried:
        return _claim_col
    _claim_tried = True
    import os

    if not s.google_cloud_project or not os.environ.get("K_SERVICE"):
        return None
    try:
        from google.cloud import firestore

        _claim_col = firestore.Client(project=s.google_cloud_project).collection(
            "ikigai_event_claims"
        )
    except Exception:
        _claim_col = None
    return _claim_col


def _claim_remote(eid: str) -> bool:
    """True = this instance owns the event. False = another worker already took it."""
    col = _firestore_claims()
    if col is None or not eid:
        return True
    try:
        col.document(eid).create({"at": time.time()})
        return True
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        msg = str(e).lower()
        if name == "AlreadyExists" or "already exists" in msg or "already_exists" in msg:
            return False
        return True


def _claim_event(event: dict, body: dict | None = None) -> bool:
    """Keep Slack retries of the same mention from posting again."""
    eid = _event_key(event, body)
    if not eid:
        return True
    now = time.time()
    with _handled_lock:
        for k, at in list(_handled.items()):
            if now - at > 180:
                _handled.pop(k, None)
        if eid in _handled:
            return False
        _handled[eid] = now
    if not _claim_remote(eid):
        return False
    return True


def _self_id() -> str:
    global _bot_uid
    if _bot_uid:
        return _bot_uid
    token = s.slack_bot_token or ""
    if not token or token.startswith("xoxb-not-set"):
        return ""
    try:
        _bot_uid = str((bolt.client.auth_test() or {}).get("user_id") or "")
    except Exception:
        _bot_uid = ""
    return _bot_uid


def _bot_event(event: dict) -> bool:
    if event.get("bot_id") or event.get("subtype"):
        return True
    uid = event.get("user") or ""
    me = _self_id()
    return bool(me and uid == me)


def _permalink(client, channel: str, ts: str) -> str:
    if not channel or not ts:
        return ""
    try:
        return client.chat_getPermalink(channel=channel, message_ts=ts).get("permalink") or ""
    except Exception:
        return f"https://slack.com/archives/{channel}/p{ts.replace('.', '')}"


def _fallback_text(result) -> str:
    if result and result.card:
        return result.card.summary or result.card.title
    return "Ikigai didn't find a matching prior call in the chats it can read."


def _card_summary(result) -> str:
    if not result or not result.card:
        return _fallback_text(result)
    c = result.card
    lead = c.summary or c.title
    return f"{lead} {c.what} {c.why}".strip()


def _is_dm(channel_id: str = "", channel_name: str = "", channel_type: str = "") -> bool:
    if channel_type == "im":
        return True
    if (channel_name or "").lower() in {"directmessage", "privategroup"} and (
        channel_id or ""
    ).startswith("D"):
        return True
    return (channel_id or "").startswith("D")


def _names(people: list[str]) -> str:
    tagged = []
    seen: set[str] = set()
    for p in people:
        u = (p or "").strip().lstrip("@")
        key = u.lower()
        if not u or key in seen:
            continue
        seen.add(key)
        tagged.append(f"@{u}")
    return ", ".join(tagged) if tagged else "_none_"


def _person_blocks(check: PersonCheck) -> list[dict]:
    uname = (check.name or "user").lstrip("@")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"@{uname}"[:150]},
        },
    ]
    headline = (check.headline or "").strip()
    story = (check.happened or "").strip()
    if headline:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": safe_mrkdwn(headline, 1800)},
            }
        )
    if story and story.lower() != headline.lower():
        if headline and story.lower().startswith(headline.lower()):
            story = story[len(headline) :].lstrip(" \n.")
        if story:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": safe_mrkdwn(f"*What happened*\n{story}", 2800),
                    },
                }
            )
    elif not headline:
        story = (check.summary or "").strip()
        if story:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": safe_mrkdwn(f"*What happened*\n{story}", 2800),
                    },
                }
            )
    if not check.reports:
        return blocks[:50]
    for i, r in enumerate(check.reports, 1):
        did = (r.gist or r.label or "A decision").replace("\n", " ").strip()
        if r.permalink:
            title = f"*{i}. <{r.permalink}|{did}>*"
        else:
            title = f"*{i}. {did}*"
        blocks.append({"type": "divider"})
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": safe_mrkdwn(title, 2900)}}
        )
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": safe_mrkdwn(f"*Supported*\n{_names(r.agreed)}", 1800),
                    },
                    {
                        "type": "mrkdwn",
                        "text": safe_mrkdwn(f"*Opposed*\n{_names(r.opposed)}", 1800),
                    },
                ],
            }
        )
    return blocks[:50]


def _safe_respond(respond, *, text: str, blocks: list | None = None, replace: bool = False) -> None:
    payload = {
        "text": text or user_error(),
        "response_type": "ephemeral",
        "unfurl_links": False,
        "unfurl_media": False,
        "replace_original": bool(replace),
    }
    try:
        if blocks:
            respond(blocks=blocks, **payload)
        else:
            respond(**payload)
    except Exception as e:  # noqa: BLE001
        print(f"ikigai respond failed: {e}", flush=True)
        try:
            respond(text=text or user_error(), response_type="ephemeral")
        except Exception:
            pass


def _reply_person(respond, check: PersonCheck) -> None:
    _safe_respond(respond, text=check.summary, blocks=_person_blocks(check), replace=True)


def _reply_private(respond, result) -> None:
    """Slash replies stay ephemeral: only the person who ran the command sees them."""
    if result.card:
        _safe_respond(
            respond, text=_fallback_text(result), blocks=_blocks(result.card), replace=True
        )
    else:
        _safe_respond(respond, text=_fallback_text(result), replace=True)


def _say_public(say, result, thread_ts: str | None = None) -> None:
    kwargs = {}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    try:
        if result.card:
            say(blocks=_blocks(result.card), text=_fallback_text(result), **kwargs)
        else:
            say(text=_fallback_text(result), **kwargs)
    except Exception as e:  # noqa: BLE001
        print(f"ikigai say failed: {e}", flush=True)
        try:
            say(text=_fallback_text(result), **kwargs)
        except Exception:
            pass


def _expand_mentions(text: str) -> str:
    store = slack_store()

    def _repl(m):
        label = store.display_name(m.group(1))
        return label if label and label != "member" else m.group(0)

    return re.sub(r"<@([A-Z0-9]+)>", _repl, text or "")


def _strip_mention(text: str) -> str:
    return _MENTION.sub("", text or "").strip()


def _query_from_channel(channel: str, fallback: str) -> str:
    history = slack_store().history(channel)
    joined = "\n".join(m.text for m in history[-12:] if m.text)
    return joined or fallback


def _public_key(channel: str, thread: str) -> str:
    return f"pub:{channel}:{thread}"


def _private_key(user_id: str) -> str:
    return f"im:{user_id}"


def _briefing_blocks(briefing: Briefing) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{safe_mrkdwn(briefing.greeting or 'Welcome back.', 400)}*",
            },
        }
    ]
    summary = (briefing.happened or "").strip()
    if summary:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": safe_mrkdwn(f"*What happened*\n{summary}", 2800),
                },
            }
        )
    lines = ["*Decisions*"]
    if briefing.items:
        for it in briefing.items[:8]:
            title = (it.title or "Decision").replace("\n", " ").strip()
            who = (it.detail or "").strip()
            if who and title:
                label = f"{who} — {title}"
            else:
                label = who or title
            if it.permalink:
                lines.append(f"• <{it.permalink}|{label}>")
            else:
                lines.append(f"• {label}")
    elif not summary:
        lines.append("No decisions while you were away.")
    if len(lines) > 1:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": safe_mrkdwn("\n".join(lines), 2900)},
            }
        )
    return blocks[:50]


def _run_login(user_id: str, channel: str, user_label: str, dm: bool) -> Briefing:
    store = slack_store()
    hour = store.user_hour(user_id)
    name = user_label or store.display_name(user_id)
    if name in {"", "member"}:
        name = "there"
    rec = presence.get_away(user_id)
    now = time.time()
    if rec:
        oldest = rec.at
        presence.clear_away(user_id)
    else:
        oldest = now - 16 * 3600
    try:
        store.join_channel(channel)
    except Exception:
        pass
    scope = "in this channel" if channel and not dm else "across the chats you can access"
    messages = collect_since(
        store,
        channel_id=channel,
        oldest=oldest,
        all_channels=bool(dm or not channel),
    )
    if not messages and channel:
        messages = collect_since(
            store,
            channel_id=channel,
            oldest=0,
            all_channels=False,
        )
    briefing = build_briefing(
        messages,
        hour=hour,
        name=name,
        scope=scope,
        away_at=oldest,
        now_at=now,
    )
    err = (getattr(store, "last_error", "") or "").strip()
    if not messages:
        if err in {"not_in_channel", "channel_not_found", "method_not_supported_for_channel_type"}:
            briefing.happened = (
                "Invite @Ikigai to this channel first (`/invite @Ikigai`), "
                "then run `/ikigai login` again."
            )
            briefing.attention = ""
            briefing.rest = ""
            briefing.items = []
        elif err:
            briefing.happened = (
                f"Slack blocked channel history ({err}). "
                "Invite @Ikigai here and try `/ikigai login` again."
            )
            briefing.attention = ""
            briefing.rest = ""
            briefing.items = []
    if not (briefing.greeting or "").strip():
        briefing.greeting = default_greeting(hour, name)
    presence.save_items(user_id, as_items(briefing))
    return briefing


_USAGE = (
    "`/ikigai <question>` — private lookup\n"
    "`/ikigai logout` — goodbye, I'll catch you up later\n"
    "`/ikigai login` — welcome back + what you missed\n"
    "`/check-ikigai @username` — that person's decisions in this chat"
)
_LOGIN_CMD = re.compile(r"^(login|back|i'?m back|im back)$", re.I)
_LOGOUT_CMD = re.compile(r"^(logout|out|eod|leaving|done for (the )?day)$", re.I)


def _hour() -> int:
    return datetime.now().hour


def _ikigai_mode(text: str, command_name: str = "") -> str:
    name = (command_name or "").strip()
    if name in {"/ikigai-logout", "/ikigai_logout"}:
        return "logout"
    if name in {"/ikigai-login", "/ikigai_login"}:
        return "login"
    t = (text or "").strip()
    if _LOGOUT_CMD.match(t):
        return "logout"
    if _LOGIN_CMD.match(t):
        return "login"
    return "search"


def _logout_work(command, respond):
    user = command.get("user_id") or ""
    channel = command.get("channel_id") or ""
    store = slack_store()
    try:
        label = store.display_name(user)
        hour = store.user_hour(user)
    except Exception:
        label, hour = "", _hour()
    presence.logout(user, channel, user_label=label)
    _safe_respond(respond, text=farewell(hour or _hour()))


def _login_work(command, respond):
    user = command.get("user_id") or ""
    channel = command.get("channel_id") or ""
    dm = _is_dm(channel, command.get("channel_name") or "")
    store = slack_store()
    try:
        label = store.display_name(user)
        hour = store.user_hour(user)
    except Exception:
        label, hour = "", _hour()
    try:
        briefing = _run_login(user, channel, label, dm)
        if not (briefing.greeting or "").strip():
            briefing.greeting = default_greeting(hour, label)
        _safe_respond(
            respond,
            text=briefing.greeting or "Welcome back.",
            blocks=_briefing_blocks(briefing),
            replace=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ikigai login failed: {e}", flush=True)
        _safe_respond(respond, text=user_error(), replace=True)


def _stay_quiet(text: str = "", result=None) -> bool:
    if text and is_trivial_prompt(text):
        return True
    if result is None:
        return False
    if result.silenced and (result.silence_reason or "") in {
        "trivial",
        "chatter",
        "not decision-like",
    }:
        return True
    return False


def _ikigai_ack(ack, command):
    q = (command.get("text") or "").strip()
    mode = _ikigai_mode(q, command.get("command") or "")
    if mode == "logout":
        ack()
        return
    if mode == "login":
        ack({"response_type": "ephemeral", "text": CATCHING_UP})
        return
    if not q:
        ack(_USAGE)
        return
    if is_trivial_prompt(q):
        ack()
        return
    ack({"response_type": "ephemeral", "text": SEARCHING})


def _ikigai_work(command, respond):
    q = (command.get("text") or "").strip()
    mode = _ikigai_mode(q, command.get("command") or "")
    if mode == "logout":
        _logout_work(command, respond)
        return
    if mode == "login":
        _login_work(command, respond)
        return
    if not q or is_trivial_prompt(q):
        return
    channel = command.get("channel_id") or ""
    dm = _is_dm(channel, command.get("channel_name") or "")
    try:
        result = _run(q, "search", "" if dm else channel, all_channels=dm)
    except Exception as e:  # noqa: BLE001
        print(f"ikigai search failed: {e}", flush=True)
        _safe_respond(respond, text=user_error(), replace=True)
        return
    if _stay_quiet(q, result):
        return
    _reply_private(respond, result)


bolt.command("/ikigai")(ack=_ikigai_ack, lazy=[_ikigai_work])


def _check_ack(ack, command):
    text = (command.get("text") or "").strip()
    if not text:
        ack("Usage: `/check-ikigai @username` — Slack username only.")
        return
    if is_trivial_prompt(text):
        ack()
        return
    ack({"response_type": "ephemeral", "text": SEARCHING})


def _check_work(command, respond):
    channel = command.get("channel_id") or ""
    text = (command.get("text") or "").strip()
    if not text or is_trivial_prompt(text):
        return
    dm = _is_dm(channel, command.get("channel_name") or "")
    store = slack_store()
    try:
        known = store.user_labels()
    except Exception:
        known = []
    name = extract_person_query(text, known, resolve_id=store.username)
    if not name:
        name = extract_person_query(text, known, resolve_id=store.display_name)
    if not name:
        _safe_respond(
            respond,
            text="Usage: `/check-ikigai @username` — Slack username only, not a display name.",
            replace=True,
        )
        return
    try:
        result = check_person(
            store,
            name,
            channel_id=None if dm else channel,
            all_channels=dm,
            analyze=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ikigai check failed: {e}", flush=True)
        _safe_respond(respond, text=user_error(), replace=True)
        return
    _reply_person(respond, result)


bolt.command("/check-ikigai")(ack=_check_ack, lazy=[_check_work])


# Leftover Slack commands from older installs: same behavior, no errors.
bolt.command("/ikigai-logout")(ack=_ikigai_ack, lazy=[_ikigai_work])
bolt.command("/ikigai-login")(ack=_ikigai_ack, lazy=[_ikigai_work])


def _post_searching(say, *, thread_ts: str | None = None):
    kwargs = {"text": SEARCHING}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    try:
        return say(**kwargs) or {}
    except Exception:
        return {}


def _clear_pending(client, channel: str, pending) -> None:
    ts = (pending or {}).get("ts")
    if not ts or not channel:
        return
    try:
        client.chat_delete(channel=channel, ts=ts)
    except Exception:
        pass


def _finish_say(client, say, channel, pending, *, text: str, blocks=None, thread_ts=None) -> None:
    ts = (pending or {}).get("ts")
    if ts and channel:
        try:
            payload = {"channel": channel, "ts": ts, "text": text or user_error()}
            if blocks:
                payload["blocks"] = blocks
            client.chat_update(**payload)
            return
        except Exception as e:  # noqa: BLE001
            print(f"ikigai chat.update failed: {e}", flush=True)
    kwargs = {"text": text or user_error()}
    if blocks:
        kwargs["blocks"] = blocks
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    try:
        say(**kwargs)
    except Exception:
        pass


def _mention_ack(ack):
    ack()


def _mention_work(body, event, say, client, logger):
    """Public mode: @Ikigai in a channel replies in that thread once."""
    if _bot_event(event) or not _claim_event(event, body):
        return
    channel = event.get("channel")
    ts = event.get("ts")
    thread = event.get("thread_ts") or ts
    text = _strip_mention(event.get("text") or "")
    if not text or is_trivial_prompt(text):
        return
    key = _public_key(channel, thread)
    if not sessions.get(key):
        sessions.start(key, source_channel=channel, source_permalink=_permalink(client, channel, ts))
    sessions.append(key, "user", text)
    prompt = sessions.prompt_with_history(key, text)
    pending = _post_searching(say, thread_ts=thread)
    try:
        result = _run(
            prompt,
            "search",
            channel,
            thread,
            permalink=_permalink(client, channel, ts),
            all_channels=False,
        )
    except Exception as e:  # noqa: BLE001
        logger.info("mention error %s", type(e).__name__)
        _finish_say(client, say, channel, pending, text=user_error(), thread_ts=thread)
        return
    if _stay_quiet(text, result):
        _clear_pending(client, channel, pending)
        return
    sessions.append(key, "assistant", _card_summary(result))
    _finish_say(
        client,
        say,
        channel,
        pending,
        text=_fallback_text(result),
        blocks=_blocks(result.card) if result.card else None,
        thread_ts=thread,
    )


bolt.event("app_mention")(ack=_mention_ack, lazy=[_mention_work])


def _dm_ack(ack):
    ack()


def _dm_work(body, event, say, client, logger):
    if _bot_event(event) or not _claim_event(event, body):
        return
    text = event.get("text") or ""
    if "<@" in text:
        return
    if event.get("channel_type") != "im":
        return
    channel = event.get("channel")
    ts = event.get("ts")
    user = event.get("user")
    query = _expand_mentions(text.strip())
    if not query or is_trivial_prompt(query):
        return
    try:
        known = slack_store().user_labels()
    except Exception:
        known = []
    name = extract_person_query(query, known)
    pending = _post_searching(say)
    if name:
        try:
            result = check_person(
                slack_store(), name, channel_id=None, all_channels=True, analyze=True
            )
        except Exception as e:  # noqa: BLE001
            _finish_say(client, say, channel, pending, text=user_error())
            return
        _finish_say(
            client,
            say,
            channel,
            pending,
            text=result.summary,
            blocks=_person_blocks(result),
        )
        return
    key = _private_key(user or channel)
    if not sessions.get(key):
        sessions.start(key, source_channel="", source_permalink="")
    sessions.append(key, "user", query)
    prompt = sessions.prompt_with_history(key, query)
    try:
        result = _run(prompt, "search", "", ts, all_channels=True)
    except Exception as e:  # noqa: BLE001
        _finish_say(client, say, channel, pending, text=user_error())
        return
    if _stay_quiet(query, result):
        _clear_pending(client, channel, pending)
        return
    sessions.append(key, "assistant", _card_summary(result))
    _finish_say(
        client,
        say,
        channel,
        pending,
        text=_fallback_text(result),
        blocks=_blocks(result.card) if result.card else None,
    )


bolt.event("message")(ack=_dm_ack, lazy=[_dm_work])


@bolt.action(re.compile(r"^brief_open_"))
def brief_open(ack):
    ack()


@bolt.action("not_same")
def not_same(ack, action, respond):
    ack()
    did = (action.get("value") or "").strip()
    if did and did != "unknown":
        graph().add_negative(did, "not_same")
    respond("Thanks. That match will be down-ranked.")

