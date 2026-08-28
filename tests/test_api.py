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
