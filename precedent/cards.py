from __future__ import annotations

from precedent.schemas import Card, Verdict


def card_from_verdict(v: Verdict) -> Card:
    if v.status == "reversed":
        title = "This guidance was later reversed"
        share = (
            f"Precedent: this call was reversed. {v.what} See {v.permalink}"
        )
    elif v.status == "concurrent":
        title = "Two live approaches, not a reversal"
        share = f"Precedent: concurrent decisions, not a conflict to flatten. {v.what}"
    else:
        title = "This was already decided"
        share = f"Precedent: {v.what} ({v.permalink})"
    return Card(
        warning=v.warning,
        title=title,
        status=v.status,
        what=v.what,
        why=v.why,
        aftermath=v.aftermath or v.concurrent_note,
        permalink=v.permalink,
        related_permalinks=v.related_permalinks,
        clarifying_question=v.clarifying_question,
        confidence=v.confidence,
        share_text=share,
    )
