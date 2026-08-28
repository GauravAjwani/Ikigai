from __future__ import annotations

import time
from contextvars import ContextVar

from ikigai.fixtures import clone_channels, clone_messages
from ikigai.prefilter import tokenize
from ikigai.schemas import Channel, SlackMessage

_PLUS_REACT = {
    "+1",
    "thumbsup",
    "thumbs_up",
    "heavy_plus_sign",
    "white_check_mark",
    "ok_hand",
    "clap",
    "raised_hands",
    "fire",
}
_MINUS_REACT = {
    "-1",
    "thumbsdown",
    "thumbs_down",
    "x",
    "heavy_multiplication_x",
    "no_entry",
    "no_entry_sign",
    "put_litter_in_its_place",
}


class SlackStore:
    last_error: str = ""

    def channels(self) -> list[Channel]:
        raise NotImplementedError

    def history(self, channel_id: str, oldest: str | None = None, permalinks: bool = True) -> list[SlackMessage]:
        raise NotImplementedError

    def permalink(self, channel_id: str, ts: str) -> str:
        return ""

    def join_channel(self, channel_id: str) -> bool:
        return True

    def user_hour(self, user_id: str = "") -> int:
        from datetime import datetime

        return datetime.now().hour

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 8, channel_id: str | None = None) -> list[SlackMessage]:
        raise NotImplementedError

    def post(self, channel_id: str, text: str, user_label: str) -> SlackMessage:
        raise NotImplementedError

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        raise NotImplementedError

    def user_labels(self) -> list[str]:
        return []

    def find_user_messages(self, name: str, channel_id: str | None = None) -> list[SlackMessage]:
        return []

    def username(self, user_id: str) -> str:
        return self.display_name(user_id)

    def display_name(self, user_id: str) -> str:
        return user_id or ""


class FixtureSlack(SlackStore):
    """In-process Slack. Message bodies live here only, never in the graph."""

    def __init__(self) -> None:
        self._channels = clone_channels()
        self._messages = clone_messages()

    def channels(self) -> list[Channel]:
        return list(self._channels)

    def history(self, channel_id: str, oldest: str | None = None, permalinks: bool = True) -> list[SlackMessage]:
        rows = [m for m in self._messages if m.channel_id == channel_id]
        if oldest:
            try:
                cut = float(oldest)
                rows = [m for m in rows if float(m.ts or 0) > cut]
            except ValueError:
                pass
        return sorted(rows, key=lambda m: m.ts)

    def permalink(self, channel_id: str, ts: str) -> str:
        for m in self._messages:
            if m.channel_id == channel_id and m.ts == ts:
                return m.permalink
        return ""

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        return [m for m in self._messages if m.channel_id == channel_id and m.thread_ts == thread_ts]

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        for m in self._messages:
            if m.permalink == permalink:
                return m
        return None

    def user_labels(self) -> list[str]:
        return sorted({m.user_label for m in self._messages if m.user_label})

    def find_user_messages(self, name: str, channel_id: str | None = None) -> list[SlackMessage]:
        q = (name or "").strip().lower().lstrip("@")
        if not q:
            return []
        out: list[SlackMessage] = []
        for m in self._messages:
            if channel_id and m.channel_id != channel_id:
                continue
            if (m.user_label or "").lower().lstrip("@") == q:
                out.append(m)
        return out

    def display_name(self, user_id: str) -> str:
        return user_id or ""

    def search(self, query: str, limit: int = 8, channel_id: str | None = None) -> list[SlackMessage]:
        q = tokenize(query)
        if not q:
            return []
        scored: list[tuple[int, SlackMessage]] = []
        seen: set[str] = set()
        for m in self._messages:
            if channel_id and m.channel_id != channel_id:
                continue
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
    """Real Slack workspace. Never falls back to the Acme fixture corpus."""

    def __init__(self, token: str, user_token: str | None = None) -> None:
        from slack_sdk import WebClient

        self._client = WebClient(token=token)
        self._search_client = WebClient(token=user_token) if user_token else self._client
        self._user_token = user_token
        self._index: list[SlackMessage] = []
        self._index_at = 0.0
        self._channel_names: dict[str, str] = {}
        self._users: dict[str, str] = {}
        self._display: dict[str, str] = {}
        self._user_tz: dict[str, int] = {}
        self.last_error = ""

    def _name(self, channel_id: str) -> str:
        return self._channel_names.get(channel_id, channel_id)

    def _load_users(self) -> dict[str, str]:
        if self._users:
            return self._users
        cursor = None
        try:
            while True:
                kwargs: dict = {"limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.users_list(**kwargs)
                for u in resp.get("members") or []:
                    if u.get("deleted") or u.get("is_bot"):
                        continue
                    uid = u.get("id") or ""
                    if not uid:
                        continue
                    profile = u.get("profile") or {}
                    uname = (u.get("name") or "").strip()
                    display = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or uname
                        or uid
                    ).strip()
                    self._users[uid] = uname or display
                    self._display[uid] = display
                    try:
                        self._user_tz[uid] = int(u.get("tz_offset") or 0)
                    except (TypeError, ValueError):
                        self._user_tz[uid] = 0
                cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
        except Exception:
            pass
        return self._users

    def _label(self, uid: str, username: str = "") -> str:
        if not uid:
            return "member"
        self._load_users()
        return self._users.get(uid) or (username or "").strip() or "member"

    def user_hour(self, user_id: str = "") -> int:
        from datetime import datetime, timedelta, timezone

        self._load_users()
        offset = self._user_tz.get(user_id or "", 0)
        now = datetime.now(timezone.utc) + timedelta(seconds=offset)
        return now.hour

    def _permalink(self, channel_id: str, ts: str) -> str:
        if not channel_id or not ts:
            return ""
        try:
            resp = self._client.chat_getPermalink(channel=channel_id, message_ts=ts)
            return resp.get("permalink") or ""
        except Exception:
            return f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

    def _votes(self, m: dict) -> tuple[list[str], list[str]]:
        plus: list[str] = []
        minus: list[str] = []
        for r in m.get("reactions") or []:
            name = str(r.get("name") or "").lower().split("::")[0]
            labels = []
            for uid in r.get("users") or []:
                label = self._label(uid)
                if label and label != "member":
                    labels.append(label)
            if name in _PLUS_REACT:
                plus.extend(labels)
            elif name in _MINUS_REACT:
                minus.extend(labels)
        return plus, minus

    def _to_msg(self, channel_id: str, m: dict, channel_name: str = "") -> SlackMessage:
        ts = m.get("ts", "")
        plus, minus = self._votes(m)
        return SlackMessage(
            channel_id=channel_id,
            channel_name=channel_name or self._name(channel_id),
            ts=ts,
            thread_ts=m.get("thread_ts") or ts,
            user_label=self._label(m.get("user") or "", m.get("username") or ""),
            text=self._slack_text(m),
            permalink=m.get("permalink") or "",
            at=m.get("ts", ""),
            plus=plus,
            minus=minus,
        )

    def channels(self) -> list[Channel]:
        out: list[Channel] = []
        cursor = None
        try:
            while True:
                kwargs = {
                    "types": "public_channel,private_channel",
                    "exclude_archived": True,
                    "limit": 200,
                }
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.users_conversations(**kwargs)
                for c in resp.get("channels") or []:
                    cid = c.get("id") or ""
                    name = c.get("name") or cid
                    self._channel_names[cid] = name
                    out.append(
                        Channel(
                            id=cid,
                            name=name,
                            purpose=(c.get("purpose") or {}).get("value") or "",
                        )
                    )
                cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
        except Exception:
            return out
        return out

    def permalink(self, channel_id: str, ts: str) -> str:
        return self._permalink(channel_id, ts)

    def join_channel(self, channel_id: str) -> bool:
        if not channel_id or channel_id.startswith(("D", "U")):
            return True
        try:
            self._client.conversations_join(channel=channel_id)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"ikigai join {channel_id}: {e}")
            return False

    def _channel_label(self, channel_id: str) -> str:
        name = self._name(channel_id)
        if name and name != channel_id:
            return name
        try:
            info = self._client.conversations_info(channel=channel_id)
            ch = info.get("channel") or {}
            name = ch.get("name") or channel_id
            self._channel_names[channel_id] = name
            return name
        except Exception:
            return channel_id

    def _fetch_history_pages(self, channel_id: str, pages: int) -> tuple[list[dict], str]:
        from slack_sdk.errors import SlackApiError

        raw: list[dict] = []
        cursor = None
        err = ""
        for i in range(max(1, pages)):
            kwargs: dict = {"channel": channel_id, "limit": 100}
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = self._client.conversations_history(**kwargs)
            except SlackApiError as e:
                err = ((e.response or {}).get("error") if e.response else "") or str(e)
                if i == 0 and err in {"not_in_channel", "channel_not_found"}:
                    self.join_channel(channel_id)
                    time.sleep(0.4)
                    try:
                        resp = self._client.conversations_history(**kwargs)
                        err = ""
                    except SlackApiError as e2:
                        err = ((e2.response or {}).get("error") if e2.response else "") or str(e2)
                        return [], err
                else:
                    return raw, err
            raw.extend(resp.get("messages") or [])
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        return raw, err

    def history(self, channel_id: str, oldest: str | None = None, permalinks: bool = True) -> list[SlackMessage]:
        self.last_error = ""
        if not channel_id:
            return []
        try:
            self.join_channel(channel_id)
            pages = 1 if permalinks else 3
            raw, err = self._fetch_history_pages(channel_id, pages)
            if err and not raw:
                self.last_error = err
                print(f"ikigai history error {channel_id}: {err}")
                return []
            name = self._channel_label(channel_id)
            rows: list[SlackMessage] = []
            skip_sub = {
                "message_deleted",
                "message_changed",
                "channel_join",
                "channel_leave",
                "channel_topic",
                "channel_purpose",
                "bot_add",
                "bot_remove",
            }
            for m in raw:
                if m.get("bot_id"):
                    continue
                if m.get("subtype") in skip_sub:
                    continue
                text = self._slack_text(m)
                if not text:
                    continue
                if (
                    text.startswith("Checking decision")
                    or "searching decision history" in text.lower()
                    or "didn't find a prior decision" in text
                ):
                    continue
                row = self._to_msg(channel_id, m, name)
                row.text = text
                if permalinks and not row.permalink:
                    row.permalink = self._permalink(channel_id, row.ts)
                rows.append(row)
            rows.reverse()
            if oldest:
                try:
                    cut = float(oldest)
                    filtered = [r for r in rows if float(r.ts or 0) > cut]
                    if filtered:
                        rows = filtered
                except ValueError:
                    pass
            print(f"ikigai history {channel_id} n={len(rows)} err={err or '-'}")
            return rows
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            print(f"ikigai history failed {channel_id}: {e}")
            return []

    def thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        try:
            resp = self._client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=40
            )
            name = self._name(channel_id)
            return [self._to_msg(channel_id, m, name) for m in resp.get("messages") or []]
        except Exception:
            return []

    def _refresh_index(self) -> None:
        now = time.time()
        if self._index and now - self._index_at < 90:
            return
        msgs: list[SlackMessage] = []
        for ch in self.channels()[:12]:
            try:
                resp = self._client.conversations_history(channel=ch.id, limit=40)
                for m in resp.get("messages") or []:
                    text = m.get("text") or ""
                    if not text or m.get("subtype") or m.get("bot_id"):
                        continue
                    row = self._to_msg(ch.id, m, ch.name)
                    if not row.permalink:
                        row.permalink = self._permalink(ch.id, row.ts)
                    msgs.append(row)
            except Exception:
                continue
        self._index = msgs
        self._index_at = now

    def _search_api(self, query: str, limit: int) -> list[SlackMessage]:
        if not self._user_token:
            return []
        resp = self._search_client.search_messages(query=query, count=limit)
        matches = (resp.get("messages") or {}).get("matches") or []
        out: list[SlackMessage] = []
        for m in matches[:limit]:
            ch = m.get("channel") or {}
            out.append(
                SlackMessage(
                    channel_id=ch.get("id", ""),
                    channel_name=ch.get("name", ""),
                    ts=m.get("ts", ""),
                    thread_ts=m.get("ts", ""),
                    user_label=self._label(m.get("user") or "", m.get("username") or ""),
                    text=m.get("text", ""),
                    permalink=m.get("permalink", ""),
                    at=m.get("ts", ""),
                )
            )
        return out

    def search(self, query: str, limit: int = 8, channel_id: str | None = None) -> list[SlackMessage]:
        try:
            found = self._search_api(query, limit)
            if channel_id:
                found = [m for m in found if m.channel_id == channel_id]
            if found:
                return found[:limit]
        except Exception:
            pass
        self._refresh_index()
        q = tokenize(query)
        pool = [m for m in self._index if not channel_id or m.channel_id == channel_id]
        if not q:
            return pool[:limit]
        scored: list[tuple[int, SlackMessage]] = []
        seen: set[str] = set()
        for m in pool:
            key = m.permalink or m.ts
            if key in seen:
                continue
            overlap = len(q & tokenize(m.text))
            if overlap <= 0:
                continue
            seen.add(key)
            scored.append((overlap, m))
        scored.sort(key=lambda x: -x[0])
        if scored:
            return [m for _, m in scored[:limit]]
        return pool[:limit]

    def post(self, channel_id: str, text: str, user_label: str) -> SlackMessage:
        resp = self._client.chat_postMessage(channel=channel_id, text=text)
        ts = (resp.get("ts") or "") if isinstance(resp, dict) else ""
        return SlackMessage(
            channel_id=channel_id,
            channel_name=self._name(channel_id),
            ts=ts,
            thread_ts=ts,
            user_label=user_label,
            text=text,
            permalink=self._permalink(channel_id, ts),
            at="now",
        )

    def by_permalink(self, permalink: str) -> SlackMessage | None:
        for m in self._index:
            if m.permalink == permalink:
                return m
        return None

    def user_labels(self) -> list[str]:
        names = sorted({n for n in self._load_users().values() if n and n != "member"})
        if names:
            return names
        return sorted({m.user_label for m in self._index if m.user_label and m.user_label != "member"})

    def find_user_messages(self, name: str, channel_id: str | None = None) -> list[SlackMessage]:
        q = (name or "").strip().lower().lstrip("@")
        if not q:
            return []
        if channel_id:
            return [
                m
                for m in self.history(channel_id)
                if (m.user_label or "").lower().lstrip("@") == q
            ]
        out: list[SlackMessage] = []
        for ch in self.channels()[:20]:
            try:
                for m in self.history(ch.id):
                    if (m.user_label or "").lower().lstrip("@") == q:
                        out.append(m)
            except Exception:
                continue
        return out

    def username(self, user_id: str) -> str:
        uid = user_id or ""
        if not uid:
            return ""
        self._load_users()
        cached = self._users.get(uid)
        if cached and cached != "member":
            return cached
        try:
            u = self._client.users_info(user=uid).get("user") or {}
            if u.get("deleted") or u.get("is_bot"):
                return ""
            uname = (u.get("name") or "").strip()
            profile = u.get("profile") or {}
            display = (
                profile.get("display_name")
                or profile.get("real_name")
                or uname
                or ""
            ).strip()
            if uname:
                self._users[uid] = uname
            if display:
                self._display[uid] = display
            try:
                self._user_tz[uid] = int(u.get("tz_offset") or 0)
            except (TypeError, ValueError):
                self._user_tz[uid] = 0
            return uname
        except Exception:
            return cached or ""

    def display_name(self, user_id: str) -> str:
        uid = user_id or ""
        if not uid:
            return ""
        self._load_users()
        shown = self._display.get(uid)
        if shown:
            return shown
        uname = self.username(uid)
        return self._display.get(uid) or uname

    def _slack_text(self, m: dict) -> str:
        text = (m.get("text") or "").strip()
        if text:
            return text
        bits: list[str] = []
        for b in m.get("blocks") or []:
            t = b.get("text") if isinstance(b, dict) else None
            if isinstance(t, dict) and t.get("text"):
                bits.append(str(t["text"]))
            for el in (b.get("elements") or []) if isinstance(b, dict) else []:
                if not isinstance(el, dict):
                    continue
                inner = el.get("text")
                if isinstance(inner, str) and inner.strip():
                    bits.append(inner)
                elif isinstance(inner, dict) and inner.get("text"):
                    bits.append(str(inner["text"]))
        if bits:
            return " ".join(bits).strip()
        files = m.get("files") or []
        names = [str(f.get("title") or f.get("name") or "") for f in files if isinstance(f, dict)]
        names = [n for n in names if n]
        return " ".join(names).strip()


_store: SlackStore | None = None
_demo: FixtureSlack | None = None
_override: ContextVar[SlackStore | None] = ContextVar("ikigai_store", default=None)


def demo_store() -> FixtureSlack:
    global _demo
    if _demo is None:
        _demo = FixtureSlack()
    return _demo


def reset_demo_store() -> FixtureSlack:
    global _demo
    _demo = FixtureSlack()
    return _demo


def bind_demo_store():
    return _override.set(demo_store())


def unbind_store(token) -> None:
    _override.reset(token)


def slack_store() -> SlackStore:
    ov = _override.get()
    if ov is not None:
        return ov
    global _store
    if _store is None:
        from ikigai.settings import get_settings

        s = get_settings()
        if s.slack_bot_token:
            _store = LiveSlack(s.slack_bot_token, user_token=s.slack_user_token or None)
        else:
            _store = FixtureSlack()
    return _store


def reset_store() -> SlackStore:
    global _store
    _store = FixtureSlack()
    return _store
