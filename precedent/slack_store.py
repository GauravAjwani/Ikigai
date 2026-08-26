from __future__ import annotations

from copy import deepcopy

from precedent.fixtures import clone_channels, clone_messages
from precedent.prefilter import tokenize
from precedent.schemas import Channel, SlackMessage


class SlackStore:
    def channels(self) -> list[Channel]:
        raise NotImplementedError

    def history(self, channel_id: str) -> list[SlackMessage]:
        raise NotImplementedError

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 8) -> list[SlackMessage]:
        raise NotImplementedError

    def post(self, channel_id: str, text: str, user_label: str) -> SlackMessage:
        raise NotImplementedError

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        raise NotImplementedError


class FixtureSlack(SlackStore):
    """In-process Slack. Message bodies live here only, never in the graph."""

    def __init__(self) -> None:
        self._channels = clone_channels()
        self._messages = clone_messages()

    def channels(self) -> list[Channel]:
        return list(self._channels)

    def history(self, channel_id: str) -> list[SlackMessage]:
        rows = [m for m in self._messages if m.channel_id == channel_id]
        return sorted(rows, key=lambda m: m.ts)

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        return [m for m in self._messages if m.channel_id == channel_id and m.thread_ts == thread_ts]

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        for m in self._messages:
            if m.permalink == permalink:
                return m
        return None

    def search(self, query: str, limit: int = 8) -> list[SlackMessage]:
        q = tokenize(query)
        if not q:
            return []
        scored: list[tuple[int, SlackMessage]] = []
        seen: set[str] = set()
        for m in self._messages:
            if m.permalink in seen:
                continue
            overlap = len(q & tokenize(m.text))
            if overlap <= 0:
                continue
            seen.add(m.permalink)
            scored.append((overlap, m))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]

    def post(self, channel_id: str, text: str, user_label: str) -> SlackMessage:
        ch = next((c for c in self._channels if c.id == channel_id), None)
        if not ch:
            raise ValueError("unknown channel")
        n = len(self._messages) + 1
        ts = f"1800000000.{n:03d}"
        msg = SlackMessage(
            channel_id=channel_id,
            channel_name=ch.name,
            ts=ts,
            thread_ts=ts,
            user_label=user_label,
            text=text,
            permalink=f"https://acme.slack.com/archives/{channel_id}/p{ts.replace('.', '')}",
            at="now",
        )
        self._messages.append(msg)
        return msg


class LiveSlack(SlackStore):
    def __init__(self, token: str, action_token: str | None = None) -> None:
        from slack_sdk import WebClient

        self._client = WebClient(token=token)
        self._action_token = action_token
        self._fallback = FixtureSlack()

    def channels(self) -> list[Channel]:
        return self._fallback.channels()

    def history(self, channel_id: str) -> list[SlackMessage]:
        return self._fallback.history(channel_id)

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        try:
            resp = self._client.conversations_replies(channel=channel_id, ts=thread_ts, limit=20)
            out = []
            for m in resp.get("messages", []):
                out.append(
                    SlackMessage(
                        channel_id=channel_id,
                        channel_name=channel_id,
                        ts=m.get("ts", ""),
                        thread_ts=m.get("thread_ts") or m.get("ts", ""),
                        user_label="member",
                        text=m.get("text", ""),
                        permalink="",
                        at="",
                    )
                )
            return out
        except Exception:
            return self._fallback.thread(channel_id, thread_ts)

    def search(self, query: str, limit: int = 8) -> list[SlackMessage]:
        try:
            kwargs = {
                "query": query,
                "content_types": ["messages"],
                "channel_types": ["public_channel", "private_channel"],
                "limit": limit,
                "include_context_messages": True,
            }
            if self._action_token:
                kwargs["action_token"] = self._action_token
            resp = self._client.api_call("assistant.search.context", json=kwargs)
            out: list[SlackMessage] = []
            results = (resp.get("results") or {}).get("messages") or resp.get("messages") or []
            if isinstance(results, dict):
                results = results.get("matches", [])
            for m in results[:limit]:
                out.append(
                    SlackMessage(
                        channel_id=m.get("channel_id") or m.get("channel", {}).get("id", ""),
                        channel_name=m.get("channel_name") or "",
                        ts=m.get("message_ts") or m.get("ts", ""),
                        thread_ts=m.get("thread_ts") or m.get("message_ts") or m.get("ts", ""),
                        user_label="member",
                        text=m.get("content") or m.get("text", ""),
                        permalink=m.get("permalink") or "",
                        at="",
                    )
                )
            if out:
                return out
        except Exception:
            pass
        try:
            resp = self._client.search_messages(query=query, count=limit)
            matches = (resp.get("messages") or {}).get("matches") or []
            out = []
            for m in matches[:limit]:
                ch = m.get("channel") or {}
                out.append(
                    SlackMessage(
                        channel_id=ch.get("id", ""),
                        channel_name=ch.get("name", ""),
                        ts=m.get("ts", ""),
                        thread_ts=m.get("ts", ""),
                        user_label="member",
                        text=m.get("text", ""),
                        permalink=m.get("permalink", ""),
                        at="",
                    )
                )
            return out
        except Exception:
            return self._fallback.search(query, limit)

    def post(self, channel_id: str, text: str, user_label: str) -> SlackMessage:
        return self._fallback.post(channel_id, text, user_label)

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        return self._fallback.by_permalink(permalink)


_store: SlackStore | None = None


def slack_store() -> SlackStore:
    global _store
    if _store is None:
        _store = FixtureSlack()
    return _store


def reset_store() -> SlackStore:
    global _store
    _store = FixtureSlack()
    return _store
