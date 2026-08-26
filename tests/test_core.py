from precedent.prefilter import is_chatter, looks_decisionish, tokenize
from precedent.graph import inspect_record
from precedent.schemas import DerivedDecision


def test_chatter_silent():
    assert is_chatter("thanks!")
    assert is_chatter("+1")
    assert is_chatter("lol")
    assert is_chatter("morning")
    assert is_chatter("https://status.cloud.google.com")


def test_decisionish():
    assert looks_decisionish("Let's rotate tokens every night.")
    assert looks_decisionish("We should pick one company-wide queue.")
    assert not looks_decisionish("anyone want bagels")


def test_tokenize_cross_vocab_gap():
    a = tokenize("Let's rotate tokens every night.")
    b = tokenize("Synchronized credential renewal caused a cascade of 401 errors.")
    # The product's point: keyword overlap is too small to connect these.
    assert len(a & b) <= 1


def test_privacy_schema():
    rec = DerivedDecision(
        decision_id="d-x",
        label="staggered credential renewal",
        concepts=["credential_rotation"],
        status="current",
        confidence=0.9,
        permalink="https://acme.slack.com/archives/C-SECURITY/p1",
        channel_id="C-SECURITY",
        thread_ts="1",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    assert inspect_record(rec.model_dump()) == []
    leaks = inspect_record({**rec.model_dump(), "message_text": "secret", "embedding": [0.1] * 64})
    assert leaks
