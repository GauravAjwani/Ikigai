"""Who made a call, and who agreed or opposed. Gemini paraphrases; permalinks stay live Slack."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ikigai.cards import one_line, topic_line
from ikigai.notes import notable, pack_messages, pack_thread, untrusted, for_prompt
from ikigai.prefilter import is_chatter, is_trivial_prompt, looks_decisionish, tokenize
from ikigai.schemas import SlackMessage
from ikigai.slack_store import SlackStore

AGREE = re.compile(
    r"(\+1\b|:(\+1|thumbsup|white_check_mark):|👍|✅|"
    r"\b(agreed|agree|yes|yeah|yep|correct)\b)",
    re.I,
)
OPPOSE = re.compile(
    r"(-1\b|:(?:-1|thumbsdown):|👎|❌|"
    r"\b(not correct|incorrect|nope)\b)",
    re.I,
)
# "no more / no new" is policy language, not a vote against the thread.
NOISE_NO = re.compile(
    r"\bno[-\s](more|new|longer|one|problem|worries|idea)\b",
    re.I,
)
PLAIN_NO = re.compile(r"\bno\b", re.I)
WHOLE_AGREE = re.compile(
    r"^(yes|yeah|yep|agreed\.?|agree\.?|correct\.?|\+1|"
    r":\+1:|:thumbsup:|👍|✅)\s*[.!]?\s*$",
    re.I,
)
WHOLE_OPPOSE = re.compile(
    r"^(no|nope|incorrect|not correct|-1|"
    r":-1:|:thumbsdown:|👎|❌)\s*[.!]?\s*$",
    re.I,
)
PERSON_LEAD = re.compile(
    r"^(?:\/?check(?:-ikigai)?|what did|decisions? (?:by|from)|"
    r"calls? (?:by|from)|who (?:agreed|opposed) (?:with |on )?)\s+",
    re.I,
)
PERSON_TAIL = re.compile(
    r"\s+(?:decide(?:d)?|decisions?|calls?|proposal)s?\s*\??$",
    re.I,
)
POSSESSIVE = re.compile(
    r"^(.+?)(?:'s)\s+(?:decision|call|proposal)s?\s*$",
    re.I,
)
MENTION = re.compile(r"<@[^>]+>")
MENTION_ID = re.compile(r"<@([A-Z0-9]+)(?:\|([^>]+))?>")
USERNAME_TOKEN = re.compile(r"^@?[A-Za-z0-9._\-]{2,32}$")


@dataclass
class StanceReport:
    name: str
    label: str
    what: str
    channel_id: str
    channel_name: str
    permalink: str
    agreed: list[str] = field(default_factory=list)
    opposed: list[str] = field(default_factory=list)
    gist: str = ""


class _CallView(BaseModel):
    title: str = ""
    gist: str = ""
    permalink: str = ""
    agreed: list[str] = Field(default_factory=list)
    opposed: list[str] = Field(default_factory=list)


class _PersonDigest(BaseModel):
    headline: str = ""
    happened: str = ""
    calls: list[_CallView] = Field(default_factory=list)


@dataclass
class PersonCheck:
    name: str
    scope: str
    reports: list[StanceReport] = field(default_factory=list)
    headline: str = ""
    happened: str = ""

    @property
    def summary(self) -> str:
        if self.headline:
            return self.headline
        if self.happened:
            return self.happened
        n = len(self.reports)
        where = self.scope
        if not n:
            return f"No decisions by @{self.name} found {where}."
        noun = "decision" if n == 1 else "decisions"
        return f"@{self.name} made {n} {noun} {where}."


class _StanceGuess(BaseModel):
    stance: str = "none"


STANCE_PROMPT = """Classify this Slack reply as support or opposition to a teammate's decision.

Support: agreed, yes, yeah, correct, +1
Oppose: no, nope, not correct, incorrect

If they reject the call or say no, stance is oppose — even if they quote the proposal.
If they clearly back it, stance is agree.
If it is unrelated chatter, stance is none.

Reply:
{text}

JSON:
- stance: agree | oppose | none
"""


def _has_agree(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if WHOLE_AGREE.match(t):
        return True
    return bool(AGREE.search(t))


def _has_oppose(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if WHOLE_OPPOSE.match(t):
        return True
    if OPPOSE.search(t):
        return True
    stripped = NOISE_NO.sub(" ", t)
    return bool(PLAIN_NO.search(stripped))


def _gemini_stance(text: str) -> str:
    try:
        from ikigai.gemini_client import generate_json
        from ikigai.settings import get_settings

        s = get_settings()
        if not s.gemini_ready():
            return ""
        result, _model = generate_json(
            stage="stance",
            model=s.gate_model,
            fallback=s.fallback_gate_model,
            prompt=STANCE_PROMPT.format(text=untrusted(text or "", 1500)),
            schema=_StanceGuess,
            thinking="MINIMAL",
        )
        if isinstance(result, _StanceGuess):
            v = (result.stance or "").strip().lower()
            if v in {"agree", "oppose"}:
                return v
    except Exception:
        pass
    return ""


def classify_stance(text: str, *, allow_gemini: bool = True) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    oppose = _has_oppose(t)
    agree = _has_agree(t)
    if oppose and not agree:
        return "oppose"
    if agree and not oppose:
        return "agree"
    if not oppose and not agree:
        return ""
    # Both cues (e.g. "yes … no"): ask Gemini. If it cannot decide, oppose wins
    # so a "no" is never filed as Supported.
    if allow_gemini:
        guessed = _gemini_stance(t)
        if guessed:
            return guessed
    return "oppose"


def _clean_name(raw: str) -> str:
    t = MENTION.sub("", raw or "").strip()
    t = t.strip(" \t\"'`.,:;!?")
    t = re.sub(r"^@", "", t)
    return t


def extract_person_query(
    text: str,
    known_names: list[str] | None = None,
    resolve_id=None,
) -> str | None:
    raw = text or ""
    mid = MENTION_ID.search(raw)
    if mid:
        uid = mid.group(1)
        labeled = _clean_name(mid.group(2) or "")
        if resolve_id:
            got = _clean_name(resolve_id(uid) or "")
            if got and got.lower() != "member":
                return got
        if labeled and USERNAME_TOKEN.match(labeled):
            return labeled
        return None
    t = MENTION.sub(" ", raw).strip()
    if not t:
        return None
    m = POSSESSIVE.match(t)
    if m:
        return _clean_name(m.group(1)) or None
    stripped = PERSON_LEAD.sub("", t).strip()
    stripped = PERSON_TAIL.sub("", stripped).strip()
    if stripped and stripped.lower() != t.lower():
        name = _clean_name(stripped)
        if name and USERNAME_TOKEN.match(name) and not looks_decisionish(name):
            return name
    if known_names:
        low = t.lower().lstrip("@")
        for n in sorted({x for x in known_names if x}, key=len, reverse=True):
            key = n.lower().lstrip("@")
            if low == key:
                return n.lstrip("@")
    cleaned = _clean_name(t)
    if (
        cleaned
        and USERNAME_TOKEN.match(cleaned)
        and not looks_decisionish(cleaned)
        and not is_trivial_prompt(cleaned)
    ):
        return cleaned
    return None


def _name_match(label: str, query: str) -> bool:
    a = (label or "").strip().lower().lstrip("@")
    b = (query or "").strip().lower().lstrip("@")
    if not a or not b or a == "member":
        return False
    return a == b


def _uniq(names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        key = n.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


@dataclass
class ThreadBundle:
    root: SlackMessage
    agreed: list[str]
    opposed: list[str]
    notes: str
    thread: list[SlackMessage] = field(default_factory=list)


def check_person(
    store: SlackStore,
    name: str,
    *,
    channel_id: str | None = None,
    all_channels: bool = False,
    limit: int = 6,
    analyze: bool = True,
) -> PersonCheck:
    name = _clean_name(name)
    scope = "across the workspace" if all_channels or not channel_id else "in this channel"
    check = PersonCheck(name=name or "unknown", scope=scope)
    if not name:
        return check

    pools: list[SlackMessage] = []
    if all_channels or not channel_id:
        try:
            labels = store.user_labels()
        except Exception:
            labels = []
        resolved = next((n for n in labels if _name_match(n, name)), name)
        try:
            pools = store.find_user_messages(resolved, channel_id=None)
        except Exception:
            pools = []
        if not pools:
            for ch in store.channels():
                try:
                    pools.extend(store.history(ch.id))
                except Exception:
                    continue
    else:
        try:
            pools = list(store.history(channel_id))
        except Exception:
            pools = []

    extra: list[SlackMessage] = []
    seen_fetch: set[str] = set()
    for m in list(pools)[:8]:
        key = f"{m.channel_id}:{m.thread_ts or m.ts}"
        if key in seen_fetch:
            continue
        seen_fetch.add(key)
        try:
            extra.extend(store.thread(m.channel_id, m.thread_ts or m.ts))
        except Exception:
            continue
    pools.extend(extra)
    pools.sort(key=lambda m: m.ts or "", reverse=True)

    theirs = [m for m in pools if _name_match(m.user_label, name)]
    if not theirs:
        check.headline = (
            f"I didn't find messages from @{name} {scope}. "
            "Try their Slack @username."
        )
        return check

    room = pack_messages(notable(pools), limit=18, each=160)
    bundles = _gather_bundles(
        store, theirs, name, limit=min(limit, 6), room=pools
    )
    for b in bundles:
        if looks_decisionish(b.root.text) and not is_chatter(b.root.text):
            check.reports.append(_report_from(b, name))
            if len(check.reports) >= limit:
                break
    if analyze:
        return analyze_person(
            check,
            "\n\n".join(b.notes for b in bundles),
            room=room,
            bundles=bundles,
        )
    return check


def _in_thread(msg: SlackMessage, decision: SlackMessage) -> bool:
    if msg.channel_id != decision.channel_id:
        return False
    dth = decision.thread_ts or decision.ts
    mth = msg.thread_ts or msg.ts
    return mth == dth or msg.ts == dth or msg.thread_ts == decision.ts


def _ts(msg: SlackMessage) -> float:
    try:
        return float(msg.ts or 0)
    except ValueError:
        return 0.0


def _topical(msg: SlackMessage, decision: SlackMessage) -> int:
    return len(tokenize(decision.text or "") & tokenize(msg.text or ""))


def _nearest_decision(
    vote: SlackMessage, decisions: list[SlackMessage]
) -> SlackMessage | None:
    best: SlackMessage | None = None
    best_ts = -1.0
    vt = _ts(vote)
    for d in decisions:
        if d.channel_id != vote.channel_id:
            continue
        dt = _ts(d)
        if dt <= vt and dt >= best_ts:
            best = d
            best_ts = dt
    return best


def _stance_votes(
    thread: list[SlackMessage],
    subject: str,
    decision: SlackMessage,
    decisions: list[SlackMessage],
    room: list[SlackMessage],
) -> tuple[list[str], list[str]]:
    """Votes from the thread and from other channel messages about this call."""
    votes: dict[str, str] = {}

    def _cast(who: str, stance: str) -> None:
        label = (who or "").strip()
        if not label or _name_match(label, subject):
            return
        if label.lower() in {"ikigai", "member"}:
            return
        lk = label.lower()
        if stance == "oppose":
            votes[lk] = "oppose"
            return
        if stance == "agree" and votes.get(lk) != "oppose":
            votes[lk] = "agree"

    def _count_msg(src: SlackMessage) -> None:
        for who in src.plus or []:
            _cast(who, "agree")
        for who in src.minus or []:
            _cast(who, "oppose")
        if _name_match(src.user_label, subject):
            return
        who = (src.user_label or "").strip()
        stance = classify_stance(src.text, allow_gemini=False)
        if stance:
            _cast(who, stance)

    seen: set[tuple[str, str]] = set()
    for src in thread:
        key = (src.channel_id, src.ts)
        seen.add(key)
        _count_msg(src)

    for src in room:
        key = (src.channel_id, src.ts)
        if key in seen:
            continue
        if _name_match(src.user_label, subject):
            continue
        stance = classify_stance(src.text, allow_gemini=False)
        has_react = bool(src.plus or src.minus)
        if not stance and not has_react:
            continue
        if _in_thread(src, decision):
            seen.add(key)
            _count_msg(src)
            continue
        overlap = _topical(src, decision)
        best_overlap = 0
        best_d: SlackMessage | None = None
        for d in decisions:
            n = _topical(src, d)
            if n > best_overlap:
                best_overlap = n
                best_d = d
        if overlap >= 2 and best_d is decision:
            seen.add(key)
            _count_msg(src)
            continue
        short = bool(WHOLE_AGREE.match((src.text or "").strip()) or WHOLE_OPPOSE.match((src.text or "").strip()))
        if (short or (has_react and not (src.text or "").strip())) and _nearest_decision(
            src, decisions
        ) is decision:
            seen.add(key)
            _count_msg(src)

    agreed = [k for k, v in votes.items() if v == "agree"]
    opposed = [k for k, v in votes.items() if v == "oppose"]
    return _uniq(agreed), _uniq(opposed)


def _gather_bundles(
    store: SlackStore,
    theirs: list[SlackMessage],
    subject: str,
    limit: int = 10,
    room: list[SlackMessage] | None = None,
) -> list[ThreadBundle]:
    out: list[ThreadBundle] = []
    seen: set[str] = set()
    room = room or []
    for m in theirs:
        if is_chatter(m.text):
            continue
        key = f"{m.channel_id}:{m.thread_ts or m.ts}"
        if key in seen:
            continue
        seen.add(key)
        try:
            thread = store.thread(m.channel_id, m.thread_ts or m.ts) or [m]
        except Exception:
            thread = [m]
        out.append(
            ThreadBundle(
                root=m,
                agreed=[],
                opposed=[],
                notes=pack_thread(thread, m.permalink),
                thread=thread,
            )
        )
        if len(out) >= limit:
            break
    roots = [b.root for b in out]
    for b in out:
        b.agreed, b.opposed = _stance_votes(b.thread, subject, b.root, roots, room)
    return out


def _report_from(
    bundle: ThreadBundle,
    name: str,
    *,
    title: str = "",
    gist: str = "",
    agreed: list[str] | None = None,
    opposed: list[str] | None = None,
) -> StanceReport:
    what = (bundle.root.text or "").strip()
    gist = (gist or topic_line(what, 90)).strip()
    label = (title or gist or one_line(what, 80)).strip()
    people_for = _uniq([x.lstrip("@") for x in (agreed if agreed is not None else bundle.agreed)])
    people_against = _uniq(
        [x.lstrip("@") for x in (opposed if opposed is not None else bundle.opposed)]
    )
    overlap = {x.lower() for x in people_for} & {x.lower() for x in people_against}
    if overlap:
        people_for = [x for x in people_for if x.lower() not in overlap]
    return StanceReport(
        name=bundle.root.user_label or name,
        label=label[:80],
        what=what,
        channel_id=bundle.root.channel_id,
        channel_name=bundle.root.channel_name,
        permalink=bundle.root.permalink,
        agreed=people_for,
        opposed=people_against,
        gist=gist[:240],
    )


REPLY_PROMPT = """You are Ikigai. Read the notes. Fill JSON about @{name}.
Warm, like a teammate filling someone in. Name people. Not a story. Not stiff.
Prefer later messages when they reverse or state what still stands.
Paraphrase. Never quote Slack. Never invent permalinks.
Never say you could not read messages.

Person: @{name}
Scope: {scope}

What the channel was talking about:
{room}

This person's threads (permalinks are ground truth — copy them exactly):
{notes}

JSON:
- headline: one-line summary of their calls, including that @{name} made them
- happened: short catch-up (newlines): what they proposed, who backed or blocked, what still stands
- calls: 0-8 of THEIR decisions only
  - title: max 12 words
  - gist: one short clause
  - permalink: copied exactly
  - agreed: usernames who backed it anywhere in the chat (agreed, yes, yeah, correct, +1)
  - opposed: usernames who blocked it anywhere in the chat (no, nope, not correct, incorrect)
"""


def analyze_person(
    check: PersonCheck,
    notes: str = "",
    *,
    room: str = "",
    bundles: list[ThreadBundle] | None = None,
) -> PersonCheck:
    """One Gemini pass: facts about this person. Safe if Gemini is down."""
    for r in check.reports:
        if not r.gist:
            r.gist = topic_line(r.what, 90)
            r.label = r.gist or r.label
    packed = (notes or "").strip()
    if not packed:
        packed = "\n".join(
            f"- #{r.channel_name or 'chat'} permalink={r.permalink} text={r.what[:280]}"
            for r in check.reports
        )
    if not packed and not check.reports:
        return check

    by_link: dict[str, ThreadBundle] = {}
    if bundles:
        by_link = {b.root.permalink: b for b in bundles if b.root.permalink}

    try:
        from ikigai.gemini_client import generate_json
        from ikigai.settings import get_settings

        s = get_settings()
        if not s.gemini_ready():
            return check

        result, _model = generate_json(
            stage="person-reply",
            model=s.adjudicate_model,
            fallback=s.fallback_adjudicate_model,
            prompt=REPLY_PROMPT.format(
                name=for_prompt(check.name, 80),
                scope=for_prompt(check.scope, 80),
                room=untrusted(room or "(none)", 4000),
                notes=untrusted(packed, 5000),
            ),
            schema=_PersonDigest,
            thinking="LOW",
        )
        if not isinstance(result, _PersonDigest):
            return check

        happened = (result.happened or "").strip()
        if happened:
            check.happened = happened
        if (result.headline or "").strip():
            check.headline = result.headline.strip()
        elif check.happened:
            check.headline = check.happened.split(".")[0].strip()[:180]

        merged: list[StanceReport] = []
        seen_links: set[str] = set()
        calls = list(result.calls)
        if not calls:
            calls = [_CallView(permalink=r.permalink) for r in check.reports if r.permalink]
        reports_by_link = {r.permalink: r for r in check.reports if r.permalink}

        for d in calls:
            link = (d.permalink or "").strip()
            if not link or link in seen_links:
                continue
            bundle = by_link.get(link)
            src = reports_by_link.get(link)
            if bundle is not None:
                merged.append(
                    _report_from(
                        bundle,
                        check.name,
                        title=(d.title or "").strip(),
                        gist=(d.gist or "").strip(),
                        agreed=_uniq(list(bundle.agreed) + [x.lstrip("@") for x in d.agreed]),
                        opposed=_uniq(list(bundle.opposed) + [x.lstrip("@") for x in d.opposed]),
                    )
                )
                seen_links.add(link)
                continue
            if src is None:
                continue
            title = (d.title or "").strip()
            gist = (d.gist or "").strip()
            if title:
                src.label = title[:80]
            if gist:
                src.gist = gist[:240]
                if not title:
                    src.label = topic_line(gist, 80)
            if d.agreed:
                src.agreed = _uniq(list(src.agreed) + [x.lstrip("@") for x in d.agreed])
            if d.opposed:
                src.opposed = _uniq(list(src.opposed) + [x.lstrip("@") for x in d.opposed])
            overlap = {x.lower() for x in src.agreed} & {x.lower() for x in src.opposed}
            if overlap:
                src.agreed = [x for x in src.agreed if x.lower() not in overlap]
            merged.append(src)
            seen_links.add(link)
        if merged:
            check.reports = merged[:8]
    except Exception:
        pass
    return check


def digest_person(check: PersonCheck) -> PersonCheck:
    return analyze_person(check)
