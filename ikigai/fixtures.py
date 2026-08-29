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
    Channel(
        id="G-CORE",
        name="core-leads",
        purpose="Private group · hiring and headcount",
        kind="group",
    ),
    Channel(
        id="G-ONCALL",
        name="oncall-leads",
        purpose="Private group · pager coverage",
        kind="group",
    ),
    Channel(
        id="G-GROWTH",
        name="growth-leads",
        purpose="Private group · activation before spend",
        kind="group",
    ),
    Channel(id="D-IKIGAI", name="ikigai", purpose="Direct message with Ikigai", kind="dm"),
    Channel(id="D-PRIYA", name="priya", purpose="1:1 with Priya", kind="dm"),
    Channel(id="D-MARCUS", name="marcus", purpose="1:1 with Marcus", kind="dm"),
    Channel(id="D-AISHA", name="aisha", purpose="1:1 with Aisha", kind="dm"),
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
        "ugh last night every service hit IAM at midnight and the token endpoint just died, cascade of 401s. "
        "can we stagger renewal per service? i don't want a global nightly rotation job, that's what melted us.",
        "2024-03-12T09:14:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1710000060.101",
        "marcus",
        "yeah the blast radius is the problem, not rotating itself. "
        "we'll spread renewals across a 6-hour window keyed by service id. no more synchronized midnight job.",
        "2024-03-12T09:18:00Z",
        "1710000000.100",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1710000120.102",
        "priya",
        "ok cool, from now on we stagger per service. i'll drop a note in the runbook.",
        "2024-03-12T09:22:00Z",
        "1710000000.100",
    ),
    # Reversal
    _m(
        "C-SECURITY",
        "security",
        "1737000000.200",
        "aisha",
        "hey circling back on credential renewal — platform shipped a lock-free rotator with jitter "
        "and a dedicated token pool so that 401 pileup shouldn't happen again. "
        "can we go back to one nightly window? the stagger-only thing feels like leftover caution.",
        "2025-01-16T15:02:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1737000120.201",
        "marcus",
        "yeah the original failure mode is gone. nightly global rotation is fine again "
        "as long as the lock-free rotator stays in the path. going forward that's how we do it.",
        "2025-01-16T15:10:00Z",
        "1737000000.200",
    ),
    # --- Feature flags ---
    _m(
        "C-PLATFORM",
        "platform",
        "1712000000.300",
        "dev",
        "we keep shipping kill switches as env vars and then nobody remembers which Cloud Run revision has them. "
        "from now on runtime flags go through LaunchDarkly. env vars are just for boot-time config.",
        "2024-04-02T11:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1712000200.301",
        "sam",
        "yeah let's do that. no new feature gates in env. existing ones we migrate by end of quarter.",
        "2024-04-02T11:08:00Z",
        "1712000000.300",
    ),
    # --- Payments queue vs notifications queue (concurrent, not a reversal) ---
    _m(
        "C-PAYMENTS",
        "payments",
        "1714000000.400",
        "lin",
        "ledger workers need exactly-once and actual SQL transactions so we will keep using Postgres SKIP LOCKED as the queue. "
        "not Pub/Sub — dual-write into a bus would split the transaction boundary and i'm not doing that.",
        "2024-04-25T16:40:00Z",
    ),
    _m(
        "C-PAYMENTS",
        "payments",
        "1714000300.401",
        "ravi",
        "sounds good, payments stays on postgres for the work queue.",
        "2024-04-25T16:51:00Z",
        "1714000000.400",
    ),
    _m(
        "C-NOTIFY",
        "notifications",
        "1714100000.410",
        "june",
        "fanout is fine being at-least-once. we should standardize on Pub/Sub plus idempotent handlers. "
        "postgres as a queue would idle-lock us at peak send.",
        "2024-04-26T10:12:00Z",
    ),
    _m(
        "C-NOTIFY",
        "notifications",
        "1714100180.411",
        "dev",
        "yep notifications on Pub/Sub. this isn't a company-wide queue thing, just us.",
        "2024-04-26T10:20:00Z",
        "1714100000.410",
    ),
    # --- SEV policy ---
    _m(
        "C-INCIDENTS",
        "incidents",
        "1718000000.500",
        "oncall",
        "postmortem from saturday — we sat 50 minutes before telling customers the checkout button 500'd. "
        "from now on SEV2 or worse, status page within 30 minutes of declare. slack is not a substitute.",
        "2024-06-10T13:00:00Z",
    ),
    _m(
        "C-INCIDENTS",
        "incidents",
        "1718000400.501",
        "sasha",
        "yeah status page first, slack second. freeze deploys for SEV1 until the commander lifts it.",
        "2024-06-10T13:12:00Z",
        "1718000000.500",
    ),
    # --- AI in auth review ---
    _m(
        "C-SECURITY",
        "security",
        "1720000000.600",
        "priya",
        "copilot diffs in the session cookie parser slipped past review. "
        "going forward anything under /auth or /iam needs a second human who isn't the author, "
        "even if an agent wrote the patch. no 'it's a small refactor' exceptions.",
        "2024-07-03T18:20:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1720000500.601",
        "aisha",
        "yep that's the bar for identity code.",
        "2024-07-03T18:31:00Z",
        "1720000000.600",
    ),
    # --- Observability vendor ---
    _m(
        "C-PLATFORM",
        "platform",
        "1722000000.700",
        "sam",
        "procurement already signed Datadog through 2027. we are not evaluating New Relic or Grafana Cloud "
        "for production APM this year. use Datadog or it comes out of your team budget.",
        "2024-07-26T09:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1722000120.701",
        "dev",
        "got it, Datadog until the contract ends.",
        "2024-07-26T09:05:00Z",
        "1722000000.700",
    ),
    # --- PII retention ---
    _m(
        "C-SECURITY",
        "security",
        "1725000000.800",
        "legal",
        "support exports have been sitting on raw cardholder emails in Cloud Storage for 18 months. "
        "from now on those PII artifacts go away after 30 days. legal hold is the only exception, and it has to be ticketed.",
        "2024-08-30T14:44:00Z",
    ),
    _m(
        "C-SECURITY",
        "security",
        "1725000240.801",
        "priya",
        "i'll put the lifecycle rule on the bucket. 30 days.",
        "2024-08-30T14:50:00Z",
        "1725000000.800",
    ),
    # --- Multi-region ---
    _m(
        "C-PLATFORM",
        "platform",
        "1728000000.900",
        "marcus",
        "we're not going multi-region for checkout this year. failover is restore-from-backup in us-central1. "
        "latency to EU we just live with. please don't spin up a second Cloud SQL primary.",
        "2024-10-04T12:00:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1728000360.901",
        "sam",
        "ok, single-region us-central1 until we look at it again Q3 next year.",
        "2024-10-04T12:08:00Z",
        "1728000000.900",
    ),
    # --- Monorepo ---
    _m(
        "C-PLATFORM",
        "platform",
        "1730000000.110",
        "dev",
        "if we split payments into its own GitHub org the release train falls over. "
        "we stay in the monorepo. extract a package, not a repo.",
        "2024-10-27T17:30:00Z",
    ),
    _m(
        "C-PLATFORM",
        "platform",
        "1730000180.111",
        "lin",
        "yeah monorepo stays. no new service repos unless platform actually writes an exception.",
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
    # --- Direct messages and a private group (distinct from the public channels) ---
    _m(
        "G-CORE",
        "core-leads",
        "1732000000.501",
        "priya",
        "hiring freeze stays. only exception is one SRE for the pager, not a general backfill.",
        "2024-11-19T10:00:00Z",
    ),
    _m(
        "G-CORE",
        "core-leads",
        "1732000120.502",
        "marcus",
        "agreed. one SRE seat, no other reqs until Q2. i'll tell recruiting today.",
        "2024-11-19T10:04:00Z",
        "1732000000.501",
    ),
    _m(
        "G-CORE",
        "core-leads",
        "1732000240.503",
        "aisha",
        "ok freeze holds, just the one SRE.",
        "2024-11-19T10:08:00Z",
        "1732000000.501",
    ),
    _m(
        "D-PRIYA",
        "priya",
        "1732100000.601",
        "priya",
        "on that vendor SOC2 exception — we're not waiving it. they can sit as subprocessors-only until the report is done.",
        "2024-11-20T16:12:00Z",
    ),
    _m(
        "D-PRIYA",
        "priya",
        "1732100200.602",
        "you",
        "got it. no production data in that tool until SOC2 is on file.",
        "2024-11-20T16:18:00Z",
        "1732100000.601",
    ),
    _m(
        "D-MARCUS",
        "marcus",
        "1732200000.701",
        "marcus",
        "weekend pager — we keep the existing rotation. no dedicated weekend-only oncall. swap internally if someone needs the saturday.",
        "2024-11-21T09:02:00Z",
    ),
    _m(
        "D-MARCUS",
        "marcus",
        "1732200300.702",
        "you",
        "fine by me. i'll cover this saturday so maya can be at the wedding.",
        "2024-11-21T09:10:00Z",
        "1732200000.701",
    ),
    _m(
        "D-IKIGAI",
        "ikigai",
        "1732300000.801",
        "you",
        "are we still not doing a weekend-only oncall?",
        "2024-11-22T11:00:00Z",
    ),
    _m(
        "G-ONCALL",
        "oncall-leads",
        "1732400000.901",
        "marcus",
        "follow-the-sun is off the table this year. US hours only. EMEA waits for the morning handoff, no extra region seat.",
        "2024-11-25T14:20:00Z",
    ),
    _m(
        "G-ONCALL",
        "oncall-leads",
        "1732400180.902",
        "aisha",
        "yeah no APAC pager hire. i'll put the handoff in the runbook.",
        "2024-11-25T14:28:00Z",
        "1732400000.901",
    ),
    _m(
        "G-GROWTH",
        "growth-leads",
        "1732500000.911",
        "aisha",
        "no paid ads until week-1 activation is at 40%. spend isn't going to paper over the onboarding hole.",
        "2024-11-27T11:05:00Z",
    ),
    _m(
        "G-GROWTH",
        "growth-leads",
        "1732500240.912",
        "priya",
        "agreed, pause the ads rec. activation first, then we reopen budget.",
        "2024-11-27T11:12:00Z",
        "1732500000.911",
    ),
    _m(
        "D-AISHA",
        "aisha",
        "1732600000.921",
        "aisha",
        "LaunchDarkly stays. i don't want a second flag vendor for growth experiments. reuse the platform project.",
        "2024-11-28T18:40:00Z",
    ),
    _m(
        "D-AISHA",
        "aisha",
        "1732600300.922",
        "you",
        "understood. growth experiments go in the existing LaunchDarkly project, not Split.",
        "2024-11-28T18:46:00Z",
        "1732600000.921",
    ),
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
