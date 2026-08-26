from __future__ import annotations

import threading
from datetime import date

from precedent.settings import get_settings

_lock = threading.Lock()
_usd = 0.0
_day = ""
_calls: list[dict] = []


def _roll() -> None:
    global _usd, _day, _calls
    today = date.today().isoformat()
    if _day != today:
        _day = today
        _usd = 0.0
        _calls = []


def estimate_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    s = get_settings()
    if "embed" in model:
        return tokens_in / 1_000_000 * s.embed_in
    if "lite" in model:
        return tokens_in / 1_000_000 * s.lite_in + tokens_out / 1_000_000 * s.lite_out
    return tokens_in / 1_000_000 * s.flash_in + tokens_out / 1_000_000 * s.flash_out


def record(stage: str, model: str, tokens_in: int, tokens_out: int) -> float:
    global _usd
    usd = estimate_usd(model, tokens_in, tokens_out)
    with _lock:
        _roll()
        _usd += usd
        _calls.append(
            {
                "stage": stage,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "usd": round(usd, 8),
            }
        )
        if len(_calls) > 400:
            del _calls[:-200]
    return usd


def spent_today() -> float:
    with _lock:
        _roll()
        return _usd


def budget_ok() -> tuple[bool, str]:
    s = get_settings()
    spent = spent_today()
    if spent >= s.hard_budget_usd:
        return False, f"Hard stop: ${spent:.2f} >= ${s.hard_budget_usd:.0f}"
    if spent >= s.daily_budget_usd:
        return False, f"Daily budget paused: ${spent:.2f} >= ${s.daily_budget_usd:.0f}"
    return True, ""


def snapshot() -> dict:
    s = get_settings()
    with _lock:
        _roll()
        return {
            "day": _day,
            "spent_usd": round(_usd, 6),
            "daily_budget_usd": s.daily_budget_usd,
            "hard_budget_usd": s.hard_budget_usd,
            "remaining_usd": round(max(0.0, s.daily_budget_usd - _usd), 6),
            "calls": list(reversed(_calls[-40:])),
        }
