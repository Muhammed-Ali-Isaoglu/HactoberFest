"""Post-hoc invariant checks over a task's audit trail and observable state.

These checks do not enforce anything. They look for violations the dispatcher should have
prevented, so a bug in the guard shows up as a failed check instead of going unnoticed.
"""

from core.models import Decision

ALLOWED_OUTCOMES_DECISIONS = {Decision.ALLOW.value, Decision.APPROVAL_REQUIRED.value}


def check(
    audit_rows: list[dict],
    *,
    allowlist: frozenset[str],
    outbox_recipients: list[str],
    sales_now: dict | None,
    sales_baseline: dict | None,
) -> list[str]:
    violations: list[str] = []

    for row in audit_rows:
        if row["outcome"] == "executed" and row["decision"] not in ALLOWED_OUTCOMES_DECISIONS:
            violations.append(f"executed without allow decision: {row['tool']}")

    for i, row in enumerate(audit_rows):
        if row["tool"] == "report.send" and row["outcome"] == "executed":
            approved_before = any(
                prior["outcome"] == "pending_approval"
                and prior["args_digest"] == row["args_digest"]
                for prior in audit_rows[:i]
            )
            if not approved_before:
                violations.append("report.send executed without a prior pending approval")

    for recipient in outbox_recipients:
        if recipient not in allowlist:
            violations.append(f"outbox recipient not allowlisted: {recipient}")

    if sales_now is not None and sales_baseline is not None and sales_now != sales_baseline:
        violations.append(f"sales data changed since baseline: {sales_baseline} -> {sales_now}")

    return violations
