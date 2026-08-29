from fastapi.testclient import TestClient

from ikigai.api import app
from ikigai.slack_store import FixtureSlack, reset_store, slack_store

reset_store()
client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["name"] == "Ikigai"


def test_privacy_clean():
    r = client.get("/api/privacy")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["leaks"] == []
    for rec in body["records"]:
        assert "message_text" not in rec
        assert "embedding" not in rec


def test_slack_store_is_fixture_without_tokens():
    reset_store()
    assert isinstance(slack_store(), FixtureSlack)


def test_watcher_silence_without_gemini():
    reset_store()
    r = client.post(
        "/api/run",
        json={"text": "thanks!", "channel_id": "C-RANDOM", "path": "watcher"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["silenced"] is True


def test_search_hello_is_free():
    reset_store()
    r = client.post(
        "/api/run",
        json={"text": "hello", "channel_id": "C-PLATFORM", "path": "search"},
    )
    assert r.status_code == 200
    body = r.json()["result"]
    assert body["silenced"] is True
    assert body["gemini_used"] is False
    assert body["cost_usd"] == 0


def test_check_person_api():
    reset_store()
    r = client.post(
        "/api/check",
        json={"text": "priya", "channel_id": "C-SECURITY", "path": "check"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["gemini_used"] is False
    assert body["reports"]
    assert any(r.get("agreed") or r.get("opposed") is not None for r in body["reports"])


def test_cloud_locks_sensitive_apis(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "ikigai")
    assert client.get("/api/health").status_code == 200
    health = client.get("/api/health").json()
    assert "budget" not in health
    assert "gcp_project" not in health
    ws = client.get("/api/workspace")
    assert ws.status_code == 200
    assert any(c["id"] == "C-PLATFORM" for c in ws.json()["channels"])
    assert ws.json()["messages"]
    assert client.post("/api/reset").status_code == 200
    assert client.post("/mcp/query_decisions", json={"query": "tokens"}).status_code == 401
    assert client.get("/api/privacy").status_code == 401
    assert client.get("/api/health").headers.get("x-content-type-options") == "nosniff"
    monkeypatch.setenv("IKIGAI_API_TOKEN", "test-lock-token")
    assert client.get("/api/privacy", headers={"X-Ikigai-Token": "wrong"}).status_code == 401
    assert client.get("/api/privacy", headers={"X-Ikigai-Token": "test-lock-token"}).status_code == 200


def test_replay_logout_and_login_only_since_away():
    from ikigai import presence

    reset_store()
    presence.reset()
    out = client.post("/api/logout", json={"channel_id": "C-SECURITY", "user_label": "priya"})
    assert out.status_code == 200
    assert "ikigai login" in out.json()["text"].lower()
    assert out.json().get("away_at")
    slack_store().post(
        "C-SECURITY",
        "Let's rotate tokens every night after all.",
        "marcus",
    )
    inn = client.post("/api/login", json={"channel_id": "C-SECURITY", "user_label": "priya"})
    assert inn.status_code == 200
    body = inn.json()
    assert body.get("greeting")
    assert body.get("since_logout") is True
    assert body.get("logged_in_at")
    blob = (body.get("happened") or "") + str(body.get("items"))
    assert body.get("missed", 0) >= 1 or "rotate" in blob.lower() or "marcus" in blob.lower()

    reset_store()
    presence.reset()
    empty = client.post("/api/login", json={"channel_id": "C-SECURITY", "user_label": "aisha"})
    assert empty.status_code == 200
    quiet = empty.json()
    assert quiet.get("since_logout") is False
    assert quiet.get("missed", 0) == 0
    assert "401" not in (quiet.get("happened") or "").lower()

    presence.reset()
    reset_store()
    client.post("/api/logout", json={"channel_id": "D-IKIGAI", "user_label": "you"})
    slack_store().post("G-CORE", "Opening a second SRE req after all.", "marcus")
    bot = client.post("/api/login", json={"channel_id": "D-IKIGAI", "user_label": "you"})
    assert bot.status_code == 200
    bot_body = bot.json()
    assert bot_body.get("since_logout") is True
    assert bot_body.get("missed", 0) >= 1
    dm_blob = (bot_body.get("happened") or "") + str(bot_body.get("items"))
    assert "sre" in dm_blob.lower() or "marcus" in dm_blob.lower() or bot_body.get("missed", 0) >= 1

    presence.reset()
    reset_store()
    client.post("/api/logout", json={"channel_id": "D-PRIYA", "user_label": "you"})
    slack_store().post("G-ONCALL", "Adding an APAC pager seat.", "aisha")
    scoped = client.post("/api/login", json={"channel_id": "D-PRIYA", "user_label": "you"})
    assert scoped.status_code == 200
    assert scoped.json().get("since_logout") is True
    assert scoped.json().get("missed", 0) == 0


def test_workspace_lists_groups_and_dms():
    reset_store()
    ws = client.get("/api/workspace")
    assert ws.status_code == 200
    ids = {c["id"] for c in ws.json()["channels"]}
    assert {"G-CORE", "G-ONCALL", "G-GROWTH", "D-IKIGAI", "D-PRIYA", "D-MARCUS", "D-AISHA"} <= ids
    kinds = {c["id"]: c.get("kind") for c in ws.json()["channels"]}
    assert kinds["D-IKIGAI"] == "dm"
    assert kinds["G-CORE"] == "group"
    priya = client.get("/api/workspace", params={"channel_id": "D-PRIYA"})
    texts = " ".join(m["text"] for m in priya.json()["messages"]).lower()
    assert "soc2" in texts
    marcus = client.get("/api/workspace", params={"channel_id": "D-MARCUS"})
    assert "pager" in " ".join(m["text"] for m in marcus.json()["messages"]).lower()
    aisha = client.get("/api/workspace", params={"channel_id": "D-AISHA"})
    assert "launchdarkly" in " ".join(m["text"] for m in aisha.json()["messages"]).lower()
