"""Synthetic Acme engineering Slack. Runtime never writes this to disk."""

from __future__ import annotations

from copy import deepcopy

from ikigai.schemas import Channel, DerivedDecision, SlackMessage

CHANNELS = [
    Channel(id="C-PLATFORM", name="platform", purpose="Runtime, deploys, shared services"),
    Channel(id="C-SECURITY", name="security", purpose="Auth, secrets, compliance"),
    Channel(id="C-PAYMENTS", name="payments", purpose="Ledger and card processing"),
    Channel(id="C-NOTIFY", name="notifications", purpose="Email, push, SMS fanout"),
    Channel(id="C-INCIDENTS", name="incidents", purpose="Live incident channel"),
    Channel(id="C-RANDOM", name="random", purpose="Watercooler"),
]


def _m(
    channel: str,
    name: str,
    ts: str,
    user: str,
    text: str,
    at: str,
    thread: str | None = None,
) -> SlackMessage:
    thread_ts = thread or ts
    return SlackMessage(
        channel_id=channel,
        channel_name=name,
        ts=ts,
        thread_ts=thread_ts,
        user_label=user,
        text=text,
        permalink=f"https://acme.slack.com/archives/{channel}/p{ts.replace('.', '')}",
        at=at,
    )


# Historical threads. Cross-vocabulary on purpose: later queries do not share keywords.
MESSAGES: list[SlackMessage] = [
    # --- Credential rotation (later reversed) ---
    _m(
        "C-SECURITY",
        "security",
        "1710000000.100",
        "priya",
        "Synchronized credential renewal caused a cascade of 401 errors last night. "
        "Every service hit IAM at 00:00 and the token endpoint melted. "
        "Proposal: stagger renewal per service, and do not run a global nightly rotation job.",
        "2024-03-12T09:14:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1710000060.101",
        "marcus",
        "Agreed. The blast radius is the problem, not rotation itself. "
        "We'll spread renewals across a 6-hour window keyed by service id. "
        "No more synchronized midnight job. That's the decision.",
        "2024-03-12T09:18:00Z",
        "1710000000.100",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1710000120.102",
        "priya",
        "Logged. Staggered per-service renewal is policy as of today.",
        "2024-03-12T09:22:00Z",
        "1710000000.100",
    ),
    # Reversal
    _m(
        "C-SECURITY",
        "security",
        "1737000000.200",
        "aisha",
        "Revisiting credential renewal. Platform shipped a lock-free rotator with jitter "
        "and a dedicated token pool. The 401 cascade cannot recur. "
        "I want to reverse the staggered-only policy and allow a single nightly rotation window again.",
        "2025-01-16T15:02:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1737000120.201",
        "marcus",
        "The original failure mode is gone. Nightly global rotation is allowed again, "
        "provided the lock-free rotator stays in the path. Reversing March 2024 policy.",
        "2025-01-16T15:10:00Z",
        "1737000000.200",
    ),
    # --- Feature flags ---
    _m(
        "C-PLATFORM",
        "platform",
        "1712000000.300",
        "dev",
        "We keep shipping kill switches as environment variables and then forgetting which Cloud Run revision has them. "
        "From now on runtime flags go through LaunchDarkly. Env vars are for boot-time config only.",
        "2024-04-02T11:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1712000200.301",
        "sam",
        "That's the decision. No new feature gates in env. Existing ones migrate by end of quarter.",
        "2024-04-02T11:08:00Z",
        "1712000000.300",
    ),
    # --- Payments queue vs notifications queue (concurrent, not a reversal) ---
    _m(
        "C-PAYMENTS",
        "payments",
        "1714000000.400",
        "lin",
        "Ledger workers need exactly-once and SQL transactions. We will keep using Postgres SKIP LOCKED as the queue. "
        "Not Pub/Sub. Dual-write into a bus would split the transaction boundary.",
        "2024-04-25T16:40:00Z",
    ),
    _m(
        "C-PAYMENTS",
        "payments",
        "1714000300.401",
        "ravi",
        "Decision stands: payments stays on Postgres as the work queue.",
        "2024-04-25T16:51:00Z",
        "1714000000.400",
    ),
    _m(
        "C-NOTIFY",
        "notifications",
        "1714100000.410",
        "june",
        "Fanout is fine being at-least-once. We are standardizing on Pub/Sub plus idempotent handlers. "
        "Postgres as a queue would idle-lock us at peak send.",
        "2024-04-26T10:12:00Z",
    ),
    _m(
        "C-NOTIFY",
        "notifications",
        "1714100180.411",
        "dev",
        "Approved. Notifications: Pub/Sub. This is not a company-wide queue standard.",
        "2024-04-26T10:20:00Z",
        "1714100000.410",
    ),
    # --- SEV policy ---
    _m(
        "C-INCIDENTS",
        "incidents",
        "1718000000.500",
        "oncall",
        "Postmortem from Saturday: we waited 50 minutes to tell customers the checkout button 500'd. "
        "New rule: SEV2 or worse requires an external status update within 30 minutes of declare. "
        "Internal chatter is not a substitute.",
        "2024-06-10T13:00:00Z",
    ),
    _m(
        "C-INCIDENTS",
        "incidents",
        "1718000400.501",
        "sasha",
        "That's policy. Status page first, Slack second. Freeze deploys for SEV1 until commander lifts it.",
        "2024-06-10T13:12:00Z",
        "1718000000.500",
    ),
    # --- AI in auth review ---
    _m(
        "C-SECURITY",
        "security",
        "1720000000.600",
        "priya",
        "Copilot-authored diffs in the session cookie parser slipped past review. "
        "Decision: any change under /auth or /iam needs a second human reviewer who is not the author, "
        "even if an agent wrote the patch. No exceptions for 'small refactors'.",
        "2024-07-03T18:20:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1720000500.601",
        "aisha",
        "Recording that as the review bar for identity code.",
        "2024-07-03T18:31:00Z",
        "1720000000.600",
    ),
    # --- Observability vendor ---
    _m(
        "C-PLATFORM",
        "platform",
        "1722000000.700",
        "sam",
        "Procurement already signed Datadog through 2027. We are not evaluating New Relic or Grafana Cloud "
        "for production APM this year. Use Datadog or you pay from team budget.",
        "2024-07-26T09:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1722000120.701",
        "dev",
        "Clear. Datadog is the production observability standard until the contract ends.",
        "2024-07-26T09:05:00Z",
        "1722000000.700",
    ),
    # --- PII retention ---
    _m(
        "C-SECURITY",
        "security",
        "1725000000.800",
        "legal",
        "Support exports were keeping raw cardholder emails in Cloud Storage for 18 months. "
        "Decision: support artifacts with PII expire at 30 days. Legal hold is the only exception, ticketed.",
        "2024-08-30T14:44:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1725000240.801",
        "priya",
        "I'll put the lifecycle rule on the bucket. 30 days is the number.",
        "2024-08-30T14:50:00Z",
        "1725000000.800",
    ),
    # --- Multi-region ---
    _m(
        "C-PLATFORM",
        "platform",
        "1728000000.900",
        "marcus",
        "We are not going multi-region for checkout this year. Failover is restore-from-backup in us-central1. "
        "Latency to EU is accepted. Do not spin a second Cloud SQL primary.",
        "2024-10-04T12:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1728000360.901",
        "sam",
        "Decision: single-region, us-central1, until Q3 next year review.",
        "2024-10-04T12:08:00Z",
        "1728000000.900",
    ),
    # --- Monorepo ---
    _m(
        "C-PLATFORM",
        "platform",
        "1730000000.110",
        "dev",
        "Splitting payments into its own GitHub org would break our release train. "
        "We stay in the monorepo. Extract a package, not a repository.",
        "2024-10-27T17:30:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1730000180.111",
        "lin",
        "Yes. Monorepo stays. No new service repos without a written exception from platform.",
        "2024-10-27T17:36:00Z",
        "1730000000.110",
    ),
    # Chatter / noise (must stay silent)
    _m("C-RANDOM", "random", "1731000000.001", "june", "lol the coffee machine is a SEV3", "2024-11-08T08:01:00Z"),
    _m("C-RANDOM", "random", "1731000060.002", "ravi", "+1", "2024-11-08T08:02:00Z"),
    _m("C-RANDOM", "random", "1731000120.003", "sam", "thanks!", "2024-11-08T08:03:00Z"),
    _m("C-PLATFORM", "platform", "1731001000.004", "dev", "morning", "2024-11-08T09:00:00Z"),
    _m("C-PLATFORM", "platform", "1731001060.005", "sam", "https://status.cloud.google.com", "2024-11-08T09:01:00Z"),
    _m("C-PAYMENTS", "payments", "1731002000.006", "lin", "shipped the retry metrics dashboard :shipit:", "2024-11-08T10:00:00Z"),
    _m("C-NOTIFY", "notifications", "1731003000.007", "june", "brb lunch", "2024-11-08T12:00:00Z"),
    _m("C-INCIDENTS", "incidents", "1731004000.008", "oncall", "ack", "2024-11-08T13:00:00Z"),
    _m("C-SECURITY", "security", "1731005000.009", "aisha", "nice catch on the screenshot in the doc", "2024-11-08T14:00:00Z"),
    _m("C-RANDOM", "random", "1731006000.010", "marcus", "anyone want bagels", "2024-11-08T15:00:00Z"),
]


def seed_decisions() -> list[DerivedDecision]:
    """Derived labels only — what a watcher would have written. No message text."""
    return [
        DerivedDecision(
            decision_id="d-cred-stagger",
            label="staggered per-service credential renewal; no global nightly rotation",
            concepts=["credential_rotation", "auth_cascade", "secret_management"],
            status="reversed",
            confidence=0.93,
            permalink="https://acme.slack.com/archives/C-SECURITY/p1710000000100",
            channel_id="C-SECURITY",
            thread_ts="1710000000.100",
            created_at="2024-03-12T09:22:00Z",
            updated_at="2025-01-16T15:10:00Z",
            edges=[{"type": "superseded_by", "target_id": "d-cred-nightly"}],
        ),
        DerivedDecision(
            decision_id="d-cred-nightly",
            label="nightly global credential rotation allowed via lock-free rotator",
            concepts=["credential_rotation", "auth_cascade", "secret_management"],
            status="current",
            confidence=0.91,
            permalink="https://acme.slack.com/archives/C-SECURITY/p1737000000200",
            channel_id="C-SECURITY",
            thread_ts="1737000000.200",
            created_at="2025-01-16T15:10:00Z",
            updated_at="2025-01-16T15:10:00Z",
            edges=[{"type": "supersedes", "target_id": "d-cred-stagger"}],
        ),
        DerivedDecision(
            decision_id="d-flags-ld",
            label="runtime feature flags through LaunchDarkly; env vars boot-time only",
            concepts=["feature_flags"],
            status="current",
            confidence=0.9,
            permalink="https://acme.slack.com/archives/C-PLATFORM/p1712000000300",
            channel_id="C-PLATFORM",
            thread_ts="1712000000.300",
            created_at="2024-04-02T11:08:00Z",
            updated_at="2024-04-02T11:08:00Z",
        ),
        DerivedDecision(
            decision_id="d-pay-pg-queue",
            label="payments work queue stays Postgres SKIP LOCKED",
            concepts=["queue_choice"],
            status="concurrent",
            confidence=0.88,
            permalink="https://acme.slack.com/archives/C-PAYMENTS/p1714000000400",
            channel_id="C-PAYMENTS",
            thread_ts="1714000000.400",
            created_at="2024-04-25T16:51:00Z",
            updated_at="2024-04-25T16:51:00Z",
            edges=[{"type": "conflicts", "target_id": "d-notify-pubsub"}],
        ),
        DerivedDecision(
            decision_id="d-notify-pubsub",
            label="notifications fanout on Pub/Sub with idempotent handlers",
            concepts=["queue_choice"],
            status="concurrent",
            confidence=0.88,
            permalink="https://acme.slack.com/archives/C-NOTIFY/p1714100000410",
            channel_id="C-NOTIFY",
            thread_ts="1714100000.410",
            created_at="2024-04-26T10:20:00Z",
            updated_at="2024-04-26T10:20:00Z",
            edges=[{"type": "conflicts", "target_id": "d-pay-pg-queue"}],
        ),
        DerivedDecision(
            decision_id="d-sev2-status",
            label="SEV2+ requires public status update within 30 minutes; SEV1 deploy freeze",
            concepts=["incident_comms", "sev_policy", "deploy_freeze"],
            status="current",
            confidence=0.92,
            permalink="https://acme.slack.com/archives/C-INCIDENTS/p1718000000500",
            channel_id="C-INCIDENTS",
            thread_ts="1718000000.500",
            created_at="2024-06-10T13:12:00Z",
            updated_at="2024-06-10T13:12:00Z",
        ),
        DerivedDecision(
            decision_id="d-auth-review",
            label="auth/iam changes require a second human reviewer even if an agent wrote them",
            concepts=["code_review_policy", "ai_in_auth"],
            status="current",
            confidence=0.9,
            permalink="https://acme.slack.com/archives/C-SECURITY/p1720000000600",
            channel_id="C-SECURITY",
            thread_ts="1720000000.600",
            created_at="2024-07-03T18:31:00Z",
            updated_at="2024-07-03T18:31:00Z",
        ),
        DerivedDecision(
            decision_id="d-datadog",
            label="Datadog is the production APM standard through 2027 contract",
            concepts=["observability_vendor"],
            status="current",
            confidence=0.87,
            permalink="https://acme.slack.com/archives/C-PLATFORM/p1722000000700",
            channel_id="C-PLATFORM",
            thread_ts="1722000000.700",
            created_at="2024-07-26T09:05:00Z",
            updated_at="2024-07-26T09:05:00Z",
        ),
        DerivedDecision(
            decision_id="d-pii-30d",
            label="support artifacts with PII expire at 30 days unless legal hold",
            concepts=["pii_retention"],
            status="current",
            confidence=0.9,
            permalink="https://acme.slack.com/archives/C-SECURITY/p1725000000800",
            channel_id="C-SECURITY",
            thread_ts="1725000000.800",
            created_at="2024-08-30T14:50:00Z",
            updated_at="2024-08-30T14:50:00Z",
        ),
        DerivedDecision(
            decision_id="d-single-region",
            label="checkout stays single-region us-central1 this year; no second Cloud SQL primary",
            concepts=["multi_region", "database_topology"],
            status="current",
            confidence=0.86,
            permalink="https://acme.slack.com/archives/C-PLATFORM/p1728000000900",
            channel_id="C-PLATFORM",
            thread_ts="1728000000.900",
            created_at="2024-10-04T12:08:00Z",
            updated_at="2024-10-04T12:08:00Z",
        ),
        DerivedDecision(
            decision_id="d-monorepo",
            label="stay in the monorepo; extract packages not new service repositories",
            concepts=["monorepo", "ownership"],
            status="current",
            confidence=0.85,
            permalink="https://acme.slack.com/archives/C-PLATFORM/p1730000000110",
            channel_id="C-PLATFORM",
            thread_ts="1730000000.110",
            created_at="2024-10-27T17:36:00Z",
            updated_at="2024-10-27T17:36:00Z",
        ),
    ]


EVAL_CASES = {
    "cross_vocab": [
        {
            "id": "tokens-nightly",
            "query": "Let's rotate tokens every night.",
            "path": "watcher",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1737000000200",
        },
        {
            "id": "401-memory",
            "query": "We shouldn't do a global rotation job, remember the 401s.",
            "path": "search",
            "expect_surface": True,
            "expect_status": "reversed",
            "permalink_substr": "p1710000000100",
        },
        {
            "id": "kill-switch-env",
            "query": "Can we just put the checkout kill switch in an env var on Cloud Run?",
            "path": "watcher",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1712000000300",
        },
        {
            "id": "newrelic",
            "query": "Grafana Cloud looks cheaper, should we move APM off the current vendor?",
            "path": "search",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1722000000700",
        },
        {
            "id": "auth-bot-pr",
            "query": "The agent wrote a one-line fix in the session cookie parser, I'll merge it.",
            "path": "watcher",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1720000000600",
        },
        {
            "id": "split-repo",
            "query": "Payments should live in its own GitHub org so we can ship faster.",
            "path": "watcher",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1730000000110",
        },
        {
            "id": "eu-region",
            "query": "Let's stand up a second primary database in europe-west1 for checkout.",
            "path": "watcher",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1728000000900",
        },
        {
            "id": "keep-exports",
            "query": "Support wants to keep customer emails in the bucket for a year for quality review.",
            "path": "search",
            "expect_surface": True,
            "expect_status": "current",
            "permalink_substr": "p1725000000800",
        },
    ],
    "concurrent": [
        {
            "id": "queue-standard",
            "query": "We should pick one company-wide queue. Everything on Postgres.",
            "path": "search",
            "expect_surface": True,
            "expect_status": "concurrent",
        }
    ],
    "silence": [
        {"query": "thanks!", "path": "watcher"},
        {"query": "+1", "path": "watcher"},
        {"query": "lol the coffee machine is a SEV3", "path": "watcher"},
        {"query": "morning", "path": "watcher"},
        {"query": "brb lunch", "path": "watcher"},
        {"query": "anyone want bagels", "path": "watcher"},
        {"query": "https://status.cloud.google.com", "path": "watcher"},
        {"query": "shipped the retry metrics dashboard :shipit:", "path": "watcher"},
    ],
}


def clone_messages() -> list[SlackMessage]:
    return deepcopy(MESSAGES)


def clone_channels() -> list[Channel]:
    return deepcopy(CHANNELS)
