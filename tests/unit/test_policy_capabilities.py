from core.models import Decision
from core.policy import evaluate


def test_authorized_read_is_allowed():
    assert evaluate("sales_read_report", "db.sales_aggregate").decision is Decision.ALLOW


def test_unknown_tool_and_task_are_denied():
    assert evaluate("sales_read_report", "shell_exec").decision is Decision.DENY
    assert evaluate("no_such_task", "db.sales_aggregate").decision is Decision.DENY


def test_send_to_non_allowlisted_recipient_is_denied():
    assert (
        evaluate("sales_read_report", "report.send", "attacker@evil.example").decision
        is Decision.DENY
    )


def test_send_to_allowlisted_recipient_needs_approval():
    res = evaluate("sales_read_report", "report.send", "analyst@example.org")
    assert res.decision is Decision.APPROVAL_REQUIRED


def test_read_only_task_cannot_preview():
    assert evaluate("sales_read_only", "report.preview").decision is Decision.DENY


def test_raw_capability_id_is_not_stored(harness):
    raw = harness.issue()
    stored = harness.conn.execute("SELECT capability_hash FROM capabilities").fetchall()
    assert raw not in [row[0] for row in stored]


def test_expired_capability_is_refused(harness):
    raw = harness.issue()
    harness.clock.advance(901)  # default TTL is 900 seconds
    cap = harness.caps.get(raw)
    assert harness.caps.is_usable(cap) == "capability expired"


def test_revoked_capability_is_refused(harness):
    raw = harness.issue()
    assert harness.caps.revoke("task-1") == 1
    assert harness.caps.is_usable(harness.caps.get(raw)) == "capability revoked"


def test_stale_policy_version_is_refused(harness):
    raw = harness.issue()
    harness.conn.execute("UPDATE capabilities SET policy_version = 'v0'")
    assert harness.caps.is_usable(harness.caps.get(raw)) == "stale policy version"


def test_query_budget_is_enforced_atomically(harness):
    raw = harness.issue()
    cap_hash = harness.caps.get(raw).capability_hash
    results = [harness.caps.spend_query(cap_hash) for _ in range(11)]
    assert results == [True] * 10 + [False]
