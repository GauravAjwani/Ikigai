from __future__ import annotations

import re

# Chatter that must never reach a model.
CHATTER = re.compile(
    r"^(\s*|thanks[!.]?|thank you[!.]?|thx|ty|np|lgtm|sgtm|ok|okay|k|cool|nice|"
    r"lol|lmao|haha+|yes|yep|yeah|nope|nah|\+1|:-?\)|:thumbsup:|same|"
    r"this|fyi|bump|ping|hello|hi|hey|gm|gn|wbr|eod|ack|morning)\s*$",
    re.I,
)
# @Ikigai / /ikigai greetings: skip with no model call (~100% of that request's cost).
GREETING = re.compile(
    r"^(hey( there| team| folks| all| everyone)?|hi( there| team| everyone| all)?|"
    r"hello( there| team| everyone| world| folks)?|howdy|yo|sup|"
    r"thanks( a lot| so much| everyone| team| folks)?( anyway)?|"
    r"thank you( so much| everyone| team)?|"
    r"thx|ty|cheers|ta|np|no problem|got it|sounds good|appreciate it|"
    r"good (morning|afternoon|evening|night)|gm|gn|morning|"
    r"how('s| is) it going|what'?s up|"
    r"🙏+|👍+|❤️+|🎉+|😂+)[\s!.🙏👍❤️🎉😂]*$",
    re.I,
)
BOT_NAME = re.compile(r"\b(@?ikigai)\b", re.I)
MENTION = re.compile(r"<@[^>]+>")
GREETING_LEAD = re.compile(
    r"^((hey|hi|hello|howdy|yo|sup|thanks|thank you|thx|ty|cheers|ta|"
    r"good (morning|afternoon|evening|night)|gm|gn|morning|"
    r"ok(ay)?|cool|nice|got it|sounds good|appreciate( it)?|"
    r"please|pls)[\s,!.]*)+",
    re.I,
)
POLITE_TAIL = re.compile(
    r"^(for (the )?(help|update|that|this|everything|info|heads.?up)|"
    r"a lot|so much|everyone|all|man|bro|fam|anyway)?[\s!.🙏👍❤️]*$",
    re.I,
)
EMOJI_ONLY = re.compile(r"^[\s\W_]*$", re.UNICODE)
SLACK_EMOJI_ONLY = re.compile(r"^(:[a-z0-9_+-]+:|\s)+$", re.I)
URL_ONLY = re.compile(r"^\s*https?://\S+\s*$", re.I)

DECISIONISH = re.compile(
    r"\b(let'?s|we should|we need to|we('re| are) going to|decided|decision|"
    r"proposal|propose|recommend|ship|migrate|deprecate|rotate|replace|"
    r"standardize|mandate|policy|from now on|going forward|instead of|"
    r"should we|what if we|why don't we|can we just|that's the (call|decision)|"
    r"no new |freeze|focus the next)\b",
    re.I,
)
# Stronger than DECISIONISH: the speaker is making a call, not chatting about shipping.
DECISION_CALL = re.compile(
    r"\b(decided|decision|that's the (call|decision)|that's policy|"
    r"proposal:?|propose:?|from now on|going forward|policy as of|"
    r"we will|we('re| are) going to|"
    r"no new |mandate|standardize on)\b",
    re.I,
)


def is_chatter(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 8:
        return True
    if CHATTER.match(t) or GREETING.match(t):
        return True
    if URL_ONLY.match(t) or SLACK_EMOJI_ONLY.match(t):
        return True
    letters = re.sub(r"[^\w]+", "", t, flags=re.UNICODE)
    if len(letters) < 6:
        return True
    return False


def _bare_prompt(text: str) -> str:
    t = MENTION.sub(" ", text or "")
    t = BOT_NAME.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip(" \t.,!?;")


def is_trivial_prompt(text: str) -> bool:
    """Hello / thanks / emoji-only. Used on @Ikigai and /ikigai so greetings never hit Gemini."""
    raw = (text or "").strip()
    if not raw:
        return True
    if URL_ONLY.match(raw) or SLACK_EMOJI_ONLY.match(raw):
        return True
    t = _bare_prompt(text)
    if not t:
        return True
    if CHATTER.match(t) or GREETING.match(t):
        return True
    if URL_ONLY.match(t) or SLACK_EMOJI_ONLY.match(t):
        return True
    peeled = t
    for _ in range(4):
        nxt = GREETING_LEAD.sub("", peeled).strip(" \t.,!?;")
        if nxt == peeled:
            break
        peeled = nxt
    if not peeled or POLITE_TAIL.match(peeled) or CHATTER.match(peeled) or GREETING.match(peeled):
        return True
    if URL_ONLY.match(peeled) or SLACK_EMOJI_ONLY.match(peeled):
        return True
    letters = re.sub(r"[^\w]+", "", peeled, flags=re.UNICODE)
    if not letters:
        return True
    return False


def looks_decisionish(text: str) -> bool:
    return bool(DECISIONISH.search(text or ""))


def is_decision_call(text: str) -> bool:
    """True when this message itself is a decision, not merely related chatter."""
    t = (text or "").strip()
    if not t or is_chatter(t):
        return False
    if DECISION_CALL.search(t):
        return True
    return looks_decisionish(t) and len(t) >= 80


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}
