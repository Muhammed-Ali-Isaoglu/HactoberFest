"""The only execution path for tools. Every call is canonicalized, authorized, then executed or refused."""

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from core import policy
from core.approvals import ApprovalStore
from core.audit import AuditLog
from core.capabilities import CapabilityStore
from core.models import (
    Capability,
    Decision,
    ReportPreviewArgs,
    ReportSendArgs,
    SalesAggregateArgs,
    ToolCall,
)

ARG_MODELS: dict[str, type[BaseModel]] = {
    "db.sales_aggregate": SalesAggregateArgs,
    "report.preview": ReportPreviewArgs,
    "report.send": ReportSendArgs,
}


@dataclass(frozen=True)
class DispatchResult:
    status: str  # executed | denied | pending_approval | error
    decision: Decision
    reason: str
    result: Any = None
    approval_id: str | None = None
    digest: str | None = None


def digest_of(tool: str, args: BaseModel) -> str:
    canonical = json.dumps({"tool": tool, "args": args.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Dispatcher:
    def __init__(
        self,
        caps: CapabilityStore,
        approvals: ApprovalStore,
        audit: AuditLog,
        executors: dict[str, Callable[[BaseModel], Any]],
    ) -> None:
        self._caps = caps
        self._approvals = approvals
        self._audit = audit
        self._executors = executors
        self._lock = threading.Lock()

    # Public entry points -------------------------------------------------

    def dispatch(self, raw_capability: str | None, call: ToolCall) -> DispatchResult:
        with self._lock:
            cap = self._caps.get(raw_capability)
            if cap is None:
                return self._refuse(None, call.tool, "invalid capability", None)
            spec = policy.TOOLS.get(call.tool)
            if spec is None:
                return self._refuse(cap, call.tool, "tool not registered", None)
            try:
                args = ARG_MODELS[call.tool].model_validate(call.arguments)
            except ValidationError:
                return self._refuse(cap, call.tool, "invalid arguments", None)

            digest = digest_of(call.tool, args)
            verdict = self._authorize(cap, call.tool, args)
            if verdict.decision is Decision.DENY:
                return self._refuse(cap, call.tool, verdict.reason, digest)
            if verdict.decision is Decision.APPROVAL_REQUIRED:
                approval_id = self._approvals.create(
                    capability_hash=cap.capability_hash,
                    task_id=cap.task_id,
                    tool=call.tool,
                    args_json=args.model_dump_json(),
                    digest=digest,
                )
                self._record(cap, call.tool, verdict, digest, "pending_approval")
                return DispatchResult(
                    "pending_approval",
                    Decision.APPROVAL_REQUIRED,
                    verdict.reason,
                    approval_id=approval_id,
                    digest=digest,
                )
            return self._execute(cap, call.tool, args, digest, verdict)

    def approve(self, approval_id: str, digest: str) -> DispatchResult:
        """Execute a pending action only if the approver's digest matches the stored action exactly."""
        with self._lock:
            appr = self._approvals.get(approval_id)
            if appr is None:
                self._audit_unknown_approval("approval unknown", digest)
                return DispatchResult("denied", Decision.DENY, "approval not pending")
            cap = self._caps.get_by_hash(appr.capability_hash)
            if appr.status != "pending":
                return self._refuse_approval(cap, appr, "approval not pending", digest)
            if digest != appr.digest:
                return self._refuse_approval(cap, appr, "digest mismatch", digest)
            if cap is None:
                return self._refuse_approval(None, appr, "capability unknown", digest)
            args = ARG_MODELS[appr.tool].model_validate_json(appr.args_json)
            if digest_of(appr.tool, args) != appr.digest:
                return self._refuse(cap, appr.tool, "stored action tampered", appr.digest)
            verdict = self._authorize(cap, appr.tool, args)  # re-check at execution time
            if verdict.decision is not Decision.APPROVAL_REQUIRED:
                return self._refuse(cap, appr.tool, verdict.reason, appr.digest)
            if not self._approvals.consume(approval_id):
                return self._refuse(cap, appr.tool, "approval expired or already used", appr.digest)
            return self._execute(cap, appr.tool, args, appr.digest, verdict)

    def reject(self, approval_id: str) -> bool:
        with self._lock:
            appr = self._approvals.get(approval_id)
            ok = self._approvals.reject(approval_id)
            if ok and appr is not None:
                self._audit.record(
                    task_id=appr.task_id,
                    principal=None,
                    tool=appr.tool,
                    resource=policy.TOOLS[appr.tool].resource,
                    decision=Decision.DENY,
                    policy_version=policy.POLICY_VERSION,
                    reason="rejected by human",
                    args_digest=appr.digest,
                    outcome="rejected",
                )
            return ok

    # Internals -------------------------------------------------------------

    def _authorize(self, cap: Capability, tool: str, args: BaseModel) -> policy.PolicyResult:
        reason = self._caps.is_usable(cap)
        if reason:
            return policy.PolicyResult(Decision.DENY, reason)
        if tool not in cap.allowed_tools:
            return policy.PolicyResult(Decision.DENY, "tool outside capability")
        if policy.TOOLS[tool].resource not in cap.resources:
            return policy.PolicyResult(Decision.DENY, "resource outside capability")
        recipient = getattr(args, "recipient", None)
        if recipient is not None and recipient not in cap.recipient_allowlist:
            return policy.PolicyResult(Decision.DENY, "recipient outside capability")
        if isinstance(args, SalesAggregateArgs) and args.limit > cap.max_rows_per_call:
            return policy.PolicyResult(Decision.DENY, "row limit exceeds capability")
        return policy.evaluate(cap.task_type, tool, recipient)

    def _execute(
        self, cap: Capability, tool: str, args: BaseModel, digest: str, verdict: policy.PolicyResult
    ) -> DispatchResult:
        if not self._caps.spend_query(cap.capability_hash):
            return self._refuse(cap, tool, "query budget exhausted or capability unusable", digest)
        try:
            result = self._executors[tool](args)
        except Exception as exc:  # noqa: BLE001 - no fallback path: report the failure, never invent a result
            self._record(cap, tool, verdict, digest, f"error:{type(exc).__name__}")
            return DispatchResult("error", Decision.ALLOW, "tool execution failed", digest=digest)
        self._record(cap, tool, verdict, digest, "executed")
        return DispatchResult(
            "executed", Decision.ALLOW, verdict.reason, result=result, digest=digest
        )

    def _audit_unknown_approval(self, reason: str, digest: str | None) -> None:
        self._audit.record(
            task_id=None,
            principal=None,
            tool=None,
            resource=None,
            decision=Decision.DENY,
            policy_version=None,
            reason=reason,
            args_digest=digest,
            outcome="refused",
        )

    def _refuse_approval(
        self, cap: Capability | None, appr, reason: str, submitted_digest: str
    ) -> DispatchResult:
        """Refuse an approve attempt and audit it under the approval's own task and action digest."""
        verdict = policy.PolicyResult(Decision.DENY, reason)
        if cap is not None:
            self._record(cap, appr.tool, verdict, appr.digest, "refused")
        else:
            self._audit.record(
                task_id=appr.task_id,
                principal=None,
                tool=appr.tool,
                resource=policy.TOOLS[appr.tool].resource,
                decision=Decision.DENY,
                policy_version=policy.POLICY_VERSION,
                reason=reason,
                args_digest=appr.digest,
                outcome="refused",
            )
        return DispatchResult("denied", Decision.DENY, reason, digest=appr.digest)

    def _refuse(
        self, cap: Capability | None, tool: str, reason: str, digest: str | None
    ) -> DispatchResult:
        verdict = policy.PolicyResult(Decision.DENY, reason)
        if cap is None:
            self._audit.record(
                task_id=None,
                principal=None,
                tool=tool,
                resource=None,
                decision=Decision.DENY,
                policy_version=None,
                reason=reason,
                args_digest=digest,
                outcome="refused",
            )
        else:
            self._record(cap, tool, verdict, digest, "refused")
        return DispatchResult("denied", Decision.DENY, reason, digest=digest)

    def _record(
        self,
        cap: Capability,
        tool: str,
        verdict: policy.PolicyResult,
        digest: str | None,
        outcome: str,
    ) -> None:
        spec = policy.TOOLS.get(tool)
        self._audit.record(
            task_id=cap.task_id,
            principal=cap.principal,
            tool=tool,
            resource=spec.resource if spec else None,
            decision=verdict.decision,
            policy_version=verdict.policy_version,
            reason=verdict.reason,
            args_digest=digest,
            outcome=outcome,
        )
