from core.invariants import check

ALLOW = {
    "tool": "db.sales_aggregate",
    "decision": "ALLOW",
    "outcome": "executed",
    "args_digest": "a",
}
DENY = {"tool": "db.delete", "decision": "DENY", "outcome": "refused", "args_digest": "b"}
PENDING = {
    "tool": "report.send",
    "decision": "APPROVAL_REQUIRED",
    "outcome": "pending_approval",
    "args_digest": "c",
}
SEND = {
    "tool": "report.send",
    "decision": "APPROVAL_REQUIRED",
    "outcome": "executed",
    "args_digest": "c",
}
ALLOWLIST = frozenset({"analyst@example.org"})


BASE = {"rows": 150, "total": "41025.00", "checksum": "abc"}


def run(rows, recipients=(), now=BASE):
    return check(
        rows,
        allowlist=ALLOWLIST,
        outbox_recipients=list(recipients),
        sales_now=now,
        sales_baseline=BASE,
    )


def test_clean_trail_has_no_violations():
    assert run([ALLOW, DENY, PENDING, SEND], ["analyst@example.org"]) == []


def test_executed_denial_is_a_violation():
    bad = {**DENY, "outcome": "executed"}
    assert any("without allow" in v for v in run([bad]))


def test_send_without_prior_approval_is_a_violation():
    assert any("without a prior pending approval" in v for v in run([SEND]))


def test_send_with_different_digest_is_a_violation():
    other = {**PENDING, "args_digest": "zzz"}
    assert any("without a prior pending approval" in v for v in run([other, SEND]))


def test_rogue_outbox_recipient_is_a_violation():
    assert any("not allowlisted" in v for v in run([], ["attacker@evil.example"]))


def test_changed_values_are_a_violation_even_with_same_row_count():
    changed = {**BASE, "checksum": "def"}
    assert any("sales data changed" in v for v in run([], now=changed))


def test_unknown_snapshot_is_not_a_violation():
    assert run([], now=None) == []
