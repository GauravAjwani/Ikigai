from fastapi.testclient import TestClient

from precedent.api import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_privacy_clean():
    r = client.get("/api/privacy")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["leaks"] == []
    for rec in body["records"]:
        assert "message_text" not in rec
        assert "embedding" not in rec


def test_watcher_silence_without_gemini():
    r = client.post(
        "/api/run",
        json={"text": "thanks!", "channel_id": "C-RANDOM", "path": "watcher"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["silenced"] is True
