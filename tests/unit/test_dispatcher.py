import pytest

from core.dispatcher import digest_of
from core.models import ReportSendArgs, ToolCall

SALES = {"group_by": "day", "start_date": "2026-09-01", "end_date": "2026-09-05", "limit": 10}
SEND = {"title": "Weekly", "body": "Totals ok", "recipient": "analyst@example.org"}


def test_authorized_read_executes(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="db.sales_aggregate", arguments=SALES))
    assert res.status == "executed"
    assert len(res.result) == 5


@pytest.mark.parametrize("tool", ["db.delete", "db.update", "db.insert", "shell_exec"])
def test_unregistered_or_write_tools_are_denied_without_side_effects(harness, tool):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool=tool, arguments={}))
    assert res.status == "denied"
    assert harness.db_calls == []


def test_forged_capability_is_denied(harness):
    harness.issue()
    res = harness.dispatcher.dispatch(
        "forged", ToolCall(tool="db.sales_aggregate", arguments=SALES)
    )
    assert res.status == "denied"
    assert harness.db_calls == []


@pytest.mark.parametrize(
    "args",
    [
        {**SALES, "table": "customers_private"},  # client-supplied scope is rejected
        {**SALES, "sql": "DELETE FROM sales"},  # hidden write is rejected
        {**SALES, "limit": 101},  # over row cap
    ],
)
def test_invalid_arguments_are_denied(harness, args):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="db.sales_aggregate", arguments=args))
    assert res.status == "denied"
    assert harness.db_calls == []


def test_quota_exhaustion_denies_eleventh_query(harness):
    raw = harness.issue()
    statuses = [
        harness.dispatcher.dispatch(
            raw, ToolCall(tool="db.sales_aggregate", arguments=SALES)
        ).status
        for _ in range(11)
    ]
    assert statuses == ["executed"] * 10 + ["denied"]


def test_send_waits_for_approval_then_executes_once(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    assert res.status == "pending_approval"
    assert not harness.outbox_path.exists()  # no side effect before approval

    done = harness.dispatcher.approve(res.approval_id, res.digest)
    assert done.status == "executed"
    assert harness.outbox_path.read_text().count("simulated_sent") == 1

    replay = harness.dispatcher.approve(res.approval_id, res.digest)
    assert replay.status == "denied"
    assert harness.outbox_path.read_text().count("simulated_sent") == 1


def test_approval_with_wrong_digest_is_rejected(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    bad = harness.dispatcher.approve(res.approval_id, "0" * 64)
    assert bad.status == "denied"
    assert not harness.outbox_path.exists()


def test_changed_recipient_produces_different_digest():
    a = ReportSendArgs(**SEND)
    b = ReportSendArgs(**{**SEND, "recipient": "other@example.org"})
    assert digest_of("report.send", a) != digest_of("report.send", b)


def test_expired_approval_cannot_execute(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    harness.clock.advance(301)
    assert harness.dispatcher.approve(res.approval_id, res.digest).status == "denied"
    assert not harness.outbox_path.exists()


def test_rejected_approval_cannot_execute(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    assert harness.dispatcher.reject(res.approval_id) is True
    assert harness.dispatcher.approve(res.approval_id, res.digest).status == "denied"


def test_revoked_capability_blocks_pending_approval(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    harness.caps.revoke("task-1")
    assert harness.dispatcher.approve(res.approval_id, res.digest).status == "denied"
    assert not harness.outbox_path.exists()


def test_executor_failure_is_reported_not_faked(tmp_path):
    from tests.conftest import Harness

    class Broken:
        def aggregate(self, args):
            raise ConnectionError("db down")

    h = Harness(tmp_path, executor=Broken())
    raw = h.issue()
    res = h.dispatcher.dispatch(raw, ToolCall(tool="db.sales_aggregate", arguments=SALES))
    assert res.status == "error"
    assert res.result is None
    assert h.audit.for_task("task-1")[-1]["outcome"] == "error:ConnectionError"


def test_digest_mismatch_is_audited(harness):
    raw = harness.issue()
    res = harness.dispatcher.dispatch(raw, ToolCall(tool="report.send", arguments=SEND))
    harness.dispatcher.approve(res.approval_id, "0" * 64)
    last = harness.audit.for_task("task-1")[-1]
    assert last["outcome"] == "refused"
    assert last["reason"] == "digest mismatch"
    assert last["args_digest"] == res.digest


def test_unknown_approval_is_audited(harness):
    res = harness.dispatcher.approve("does-not-exist", "0" * 64)
    assert res.status == "denied"
    assert harness.audit.decision_counts().get("DENY") == 1


def test_grounding_ignores_negated_claims():
    from agent.grounding import check

    assert check("I did not delete anything.", []) == []
    assert check("The sales table has been cleared.", []) != []
    assert check("The report was sent.", []) != []
    assert check("The report was sent.", [{"tool": "report.send", "status": "executed"}]) == []
