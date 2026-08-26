from __future__ import annotations

import asyncio
import json
import os

from slack_bolt import App
from slack_bolt.adapter.fastapi import SlackRequestHandler

from precedent.pipeline import run_pipeline
from precedent.schemas import Trigger
from precedent.settings import get_settings

s = get_settings()
bolt = App(
    token=s.slack_bot_token or "xoxb-not-set",
    signing_secret=s.slack_signing_secret or "not-set",
    process_before_response=True,
)
handler = SlackRequestHandler(bolt)


def _blocks(card) -> list[dict]:
    warn = card.warning == "warning"
    header = card.title
    fields = [
        {"type": "mrkdwn", "text": f"*What*\n{card.what}"},
        {"type": "mrkdwn", "text": f"*Why*\n{card.why}"},
        {"type": "mrkdwn", "text": f"*After*\n{card.aftermath or '—'}"},
        {"type": "mrkdwn", "text": f"*Status*\n`{card.status}` · confidence {card.confidence:.0%}"},
    ]
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        {"type": "section", "fields": fields[:2]},
        {"type": "section", "fields": fields[2:]},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{card.permalink}|Open original thread>"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Share to thread"},
                    "action_id": "share",
                    "value": card.share_text[:180],
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Not the same decision"},
                    "action_id": "not_same",
                },
            ],
        },
    ]
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


def _run(text: str, path: str, channel: str, thread: str | None = None):
    return asyncio.run(
        run_pipeline(
            Trigger(text=text, path=path, channel_id=channel, thread_ts=thread)
        )
    )


@bolt.command("/precedent")
def precedent_cmd(ack, command, respond):
    ack()
    q = (command.get("text") or "").strip()
    if not q:
        respond("Usage: `/precedent <question or proposal>` — private, only you see the result.")
        return
    respond("Searching decision history…")
    try:
        result = _run(q, "search", command.get("channel_id") or "C")
    except Exception as e:  # noqa: BLE001
        respond(f"Precedent hit an error: {e}")
        return
    if result.card:
        respond(blocks=_blocks(result.card), response_type="ephemeral")
    else:
        respond("No prior decision found in the conversations you can access.")


@bolt.command("/check-precedent")
def check_cmd(ack, command, respond, client):
    ack()
    respond("Checking this thread…")
    channel = command.get("channel_id")
    text = command.get("text") or "check this conversation"
    result = _run(text, "check", channel)
    if result.card:
        respond(blocks=_blocks(result.card), response_type="ephemeral")
    else:
        respond("No prior decision found for this thread.")


@bolt.event("message")
def watcher(event, client, logger):
    if event.get("subtype") or event.get("bot_id") or event.get("thread_ts"):
        return
    text = event.get("text") or ""
    channel = event.get("channel")
    user = event.get("user")
    try:
        result = _run(text, "watcher", channel, event.get("ts"))
    except Exception as e:  # noqa: BLE001
        logger.info("watcher silent error %s", e)
        return
    if result.silenced or not result.card:
        return
    client.chat_postEphemeral(
        channel=channel, user=user, blocks=_blocks(result.card), text=result.card.title
    )


@bolt.action("share")
def share(ack, action, respond):
    ack()
    text = (action.get("value") or "")[:500]
    respond(text=text, response_type="in_channel")


@bolt.action("not_same")
def not_same(ack, respond):
    ack()
    respond("Thanks. That match is marked private-only and will be down-ranked.")
