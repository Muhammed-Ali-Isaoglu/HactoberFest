"""FastAPI service. Operator auth is a demo shared token (fail closed when unset). Not production auth."""

import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent.gemma_client import GemmaClient
from agent.loop import run_task
from agent.scripted import ScriptedPlanner
from core.approvals import ApprovalStore
from core.audit import AuditLog
from core.capabilities import CapabilityStore
from core.config import Settings, get_settings
from core.dispatcher import Dispatcher
from core.invariants import check as check_invariants
from core.policy import TASK_POLICIES
from tools.db import PostgresSalesExecutor, StaticSalesExecutor, synthetic_rows
from tools.report import LocalOutbox, preview

DEMO_PRINCIPAL = "demo-analyst"  # trusted server-side selection; not a user-chosen role


@dataclass
class Services:
    caps: CapabilityStore
    approvals: ApprovalStore
    audit: AuditLog
    dispatcher: Dispatcher
    llm: GemmaClient | ScriptedPlanner
    max_steps: int
    sales: PostgresSalesExecutor | StaticSalesExecutor | None
    outbox_path: Path
    # Taken when the service first starts; the invariant check compares later state to it.
    sales_baseline: dict | None
    operator_token: str
    # Raw capability IDs stay in process memory only; the database holds hashes.
    task_caps: dict[str, str] = field(default_factory=dict)


def build_services(settings: Settings) -> Services:
    settings.actiongate_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.actiongate_db_path, check_same_thread=False)
    audit = AuditLog(conn)
    caps = CapabilityStore(conn)
    approvals = ApprovalStore(conn)
    if settings.sales_backend == "postgres" and settings.database_url:
        sales = PostgresSalesExecutor(settings.database_url)
    else:
        sales = StaticSalesExecutor(synthetic_rows())
    if settings.planner == "ollama":
        planner = GemmaClient(
            settings.ollama_base_url,
            settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
        )
    else:
        planner = ScriptedPlanner()

    def aggregate(args):
        if sales is None:
            raise RuntimeError("database not configured")
        return sales.aggregate(args)

    outbox = LocalOutbox(settings.outbox_path)
    dispatcher = Dispatcher(
        caps,
        approvals,
        audit,
        executors={
            "db.sales_aggregate": aggregate,
            "report.preview": preview,
            "report.send": outbox.queue,
        },
    )
    baseline = None
    if sales is not None:
        try:
            baseline = sales.snapshot()
        except Exception:  # noqa: BLE001 - no baseline means the data check is skipped
            baseline = None
    return Services(
        caps=caps,
        approvals=approvals,
        audit=audit,
        dispatcher=dispatcher,
        llm=planner,
        max_steps=settings.max_agent_steps,
        operator_token=settings.demo_operator_token,
        sales=sales,
        outbox_path=settings.outbox_path,
        sales_baseline=baseline,
    )


@lru_cache
def get_services() -> Services:
    return build_services(get_settings())


def require_operator(
    services: Services = Depends(get_services),
    x_operator_token: str | None = Header(default=None),
) -> None:
    # Fail closed: an empty configured token denies everyone.
    if not services.operator_token or not x_operator_token:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not hmac.compare_digest(x_operator_token, services.operator_token):
        raise HTTPException(status_code=401, detail="unauthorized")


class CreateTask(BaseModel):
    task_type: str = Field(max_length=64)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    digest: str = Field(min_length=64, max_length=64)


app = FastAPI(
    title="ActionGate", version="0.1.0", description="Research prototype. Not production hardened."
)


@app.get("/health")
def health(services: Services = Depends(get_services)) -> dict:
    settings = get_settings()
    llm = (
        services.llm.health() if isinstance(services.llm, GemmaClient) else {"planner": "scripted"}
    )
    return {
        "api": "ok",
        "llm": llm,
        "sales_data": "postgres" if settings.sales_backend == "postgres" else "synthetic in-memory",
    }


@app.post("/tasks", dependencies=[Depends(require_operator)])
def create_task(body: CreateTask, services: Services = Depends(get_services)) -> dict:
    if body.task_type not in TASK_POLICIES:
        raise HTTPException(status_code=400, detail="unknown task type")
    task_id = "task-" + secrets.token_hex(8)
    raw = services.caps.issue(task_id, DEMO_PRINCIPAL, body.task_type)
    services.task_caps[task_id] = raw
    return {"task_id": task_id, "task_type": body.task_type, "principal": DEMO_PRINCIPAL}


def _raw_for(task_id: str, services: Services) -> str:
    raw = services.task_caps.get(task_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="unknown task")
    return raw


@app.post("/tasks/{task_id}/chat", dependencies=[Depends(require_operator)])
def chat(task_id: str, body: ChatRequest, services: Services = Depends(get_services)) -> dict:
    raw = _raw_for(task_id, services)
    return run_task(
        raw_capability=raw,
        user_message=body.message,
        dispatcher=services.dispatcher,
        llm=services.llm,
        max_steps=services.max_steps,
    )


@app.post("/tasks/{task_id}/revoke", dependencies=[Depends(require_operator)])
def revoke(task_id: str, services: Services = Depends(get_services)) -> dict:
    _raw_for(task_id, services)
    return {"revoked": services.caps.revoke(task_id)}


@app.get("/tasks/{task_id}/audits", dependencies=[Depends(require_operator)])
def audits(task_id: str, services: Services = Depends(get_services)) -> list[dict]:
    return services.audit.for_task(task_id)


@app.get("/tasks/{task_id}/invariants", dependencies=[Depends(require_operator)])
def invariants(task_id: str, services: Services = Depends(get_services)) -> dict:
    """Check the audit trail and observable state for violations. Read-only."""
    rows = services.audit.for_task(task_id)
    recipients = []
    if services.outbox_path.exists():
        for line in services.outbox_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recipients.append(json.loads(line)["recipient"])
    now = None
    if services.sales is not None:
        try:
            now = services.sales.snapshot()
        except Exception:  # noqa: BLE001 - report unknown rather than crash the check
            now = None
    violations = check_invariants(
        rows,
        allowlist=TASK_POLICIES["sales_read_report"].recipient_allowlist,
        outbox_recipients=recipients,
        sales_now=now,
        sales_baseline=services.sales_baseline,
    )
    return {
        "ok": not violations,
        "violations": violations,
        "checked_actions": len(rows),
        "sales_snapshot": now,
    }


@app.get("/tasks/{task_id}/pending-approvals", dependencies=[Depends(require_operator)])
def pending(task_id: str, services: Services = Depends(get_services)) -> list[dict]:
    return services.approvals.pending_for_task(task_id)


@app.post("/approvals/{approval_id}", dependencies=[Depends(require_operator)])
def decide(
    approval_id: str, body: ApprovalDecision, services: Services = Depends(get_services)
) -> dict:
    if body.decision == "reject":
        return {"rejected": services.dispatcher.reject(approval_id)}
    result = services.dispatcher.approve(approval_id, body.digest)
    return {"status": result.status, "reason": result.reason, "result": result.result}


@app.get("/metrics", dependencies=[Depends(require_operator)])
def metrics(services: Services = Depends(get_services)) -> dict:
    return {"decisions": services.audit.decision_counts()}
