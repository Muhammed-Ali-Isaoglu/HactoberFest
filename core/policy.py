"""Deterministic, server-side policy. Default is DENY. The model never reads or edits this."""

from dataclasses import dataclass

from core.models import Decision, Operation

POLICY_VERSION = "v1"


@dataclass(frozen=True)
class TaskPolicy:
    task_type: str
    allowed_tools: frozenset[str]
    resources: frozenset[str]
    recipient_allowlist: frozenset[str]
    max_rows_per_call: int = 100
    max_queries_total: int = 10
    ttl_seconds: int = 900


@dataclass(frozen=True)
class ToolSpec:
    name: str
    resource: str
    operation: Operation
    description: str


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    policy_version: str = POLICY_VERSION


TOOLS: dict[str, ToolSpec] = {
    "db.sales_aggregate": ToolSpec(
        name="db.sales_aggregate",
        resource="sales_summary_safe",
        operation=Operation.READ,
        description="Aggregate sales by day or by product for a date range. Read-only.",
    ),
    "report.preview": ToolSpec(
        name="report.preview",
        resource="report_outbox",
        operation=Operation.PREVIEW,
        description="Render a local report preview. No external effect.",
    ),
    "report.send": ToolSpec(
        name="report.send",
        resource="report_outbox",
        operation=Operation.SEND,
        description="Queue a report for an allowlisted recipient. Requires human approval.",
    ),
}

TASK_POLICIES: dict[str, TaskPolicy] = {
    "sales_read_report": TaskPolicy(
        task_type="sales_read_report",
        allowed_tools=frozenset({"db.sales_aggregate", "report.preview", "report.send"}),
        resources=frozenset({"sales_summary_safe", "report_outbox"}),
        recipient_allowlist=frozenset({"analyst@example.org"}),
    ),
    "sales_read_only": TaskPolicy(
        task_type="sales_read_only",
        allowed_tools=frozenset({"db.sales_aggregate"}),
        resources=frozenset({"sales_summary_safe"}),
        recipient_allowlist=frozenset(),
    ),
}


def evaluate(task_type: str, tool_name: str, recipient: str | None = None) -> PolicyResult:
    """Static policy check for one proposed action. Anything unknown is DENY."""
    task = TASK_POLICIES.get(task_type)
    if task is None:
        return PolicyResult(Decision.DENY, "unknown task type")
    spec = TOOLS.get(tool_name)
    if spec is None:
        return PolicyResult(Decision.DENY, "tool not registered")
    if tool_name not in task.allowed_tools:
        return PolicyResult(Decision.DENY, "tool not allowed for task type")
    if spec.resource not in task.resources:
        return PolicyResult(Decision.DENY, "resource not in task scope")
    if spec.operation is Operation.SEND:
        if recipient is None or recipient not in task.recipient_allowlist:
            return PolicyResult(Decision.DENY, "recipient not allowlisted")
        return PolicyResult(Decision.APPROVAL_REQUIRED, "outbound report needs explicit approval")
    return PolicyResult(Decision.ALLOW, "authorized scoped operation")
