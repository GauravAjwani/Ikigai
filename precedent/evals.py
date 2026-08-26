from __future__ import annotations

from precedent.fixtures import EVAL_CASES
from precedent.pipeline import run_pipeline
from precedent.prefilter import is_chatter
from precedent.schemas import Trigger


async def run_evals(limit: int = 8) -> dict:
    results = {"cross_vocab": [], "silence": [], "concurrent": []}
    scores = {"cross_vocab_hit": 0, "cross_vocab_n": 0, "silence_ok": 0, "silence_n": 0}

    for case in EVAL_CASES["silence"]:
        scores["silence_n"] += 1
        silent = is_chatter(case["query"])
        if not silent:
            r = await run_pipeline(Trigger(text=case["query"], path="watcher"))
            silent = r.silenced
        ok = silent
        scores["silence_ok"] += int(ok)
        results["silence"].append({"query": case["query"], "ok": ok})

    for case in EVAL_CASES["cross_vocab"][:limit]:
        scores["cross_vocab_n"] += 1
        r = await run_pipeline(
            Trigger(text=case["query"], path=case.get("path", "search"), channel_id="C-PLATFORM")
        )
        permalinks = " ".join(
            [c.permalink for c in r.candidates]
            + ([r.verdict.permalink] if r.verdict else [])
        )
        hit = case.get("permalink_substr", "") in permalinks
        status_ok = True
        if r.verdict and case.get("expect_status"):
            status_ok = r.verdict.status == case["expect_status"] or (
                case["expect_status"] == "reversed" and r.verdict.status in {"reversed", "current"}
            )
        ok = hit and (r.card is not None or r.verdict is not None)
        scores["cross_vocab_hit"] += int(ok)
        results["cross_vocab"].append(
            {
                "id": case["id"],
                "ok": ok,
                "hit": hit,
                "status_ok": status_ok,
                "status": r.verdict.status if r.verdict else None,
                "silenced": r.silenced,
                "cost_usd": r.cost_usd,
            }
        )

    for case in EVAL_CASES["concurrent"]:
        r = await run_pipeline(Trigger(text=case["query"], path="search"))
        ok = bool(r.verdict and r.verdict.status == "concurrent") or any(
            c.graph_status == "concurrent" for c in r.candidates
        )
        results["concurrent"].append({"id": case["id"], "ok": ok, "status": r.verdict.status if r.verdict else None})

    n = max(1, scores["cross_vocab_n"])
    sn = max(1, scores["silence_n"])
    return {
        "recall": round(scores["cross_vocab_hit"] / n, 3),
        "silence_rate": round(scores["silence_ok"] / sn, 3),
        "scores": scores,
        "results": results,
    }
