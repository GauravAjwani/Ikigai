from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable

# Chatter that must never reach a model.
CHATTER = re.compile(
    r"^(\s*|thanks[!.]?|thank you[!.]?|thx|ty|np|lgtm|sgtm|ok|okay|k|cool|nice|"
    r"lol|lmao|haha+|yes|yep|yeah|nope|nah|\+1|:-?\)|:thumbsup:|same|"
    r"this|fyi|bump|ping|hello|hi|hey|gm|gn|wbr|eod|ack)\s*$",
    re.I,
)
EMOJI_ONLY = re.compile(r"^[\s\W_]*$", re.UNICODE)
URL_ONLY = re.compile(r"^\s*https?://\S+\s*$", re.I)

DECISIONISH = re.compile(
    r"\b(let'?s|we should|we need to|we('re| are) going to|decided|decision|"
    r"proposal|propose|recommend|ship|migrate|deprecate|rotate|replace|"
    r"standardize|mandate|policy|from now on|going forward|instead of|"
    r"should we|what if we|why don't we|can we just)\b",
    re.I,
)


def is_chatter(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 8:
        return True
    if CHATTER.match(t):
        return True
    if URL_ONLY.match(t):
        return True
    letters = re.sub(r"[^\w]+", "", t, flags=re.UNICODE)
    if len(letters) < 6:
        return True
    return False


def looks_decisionish(text: str) -> bool:
    return bool(DECISIONISH.search(text or ""))


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}
