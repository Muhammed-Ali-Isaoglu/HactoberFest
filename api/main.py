"""FastAPI service. Operator auth is a demo shared token (fail closed when unset). Not production auth."""

import hmac
import secrets
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent.gemma_client import GemmaClient
from agent.loop import run_task
from core.approvals import ApprovalStore
from core.audit import AuditLog
from core.capabilities import CapabilityStore
from core.config import Settings, get_settings
from core.dispatcher import Dispatcher
from core.policy import TASK_POLICIES
from tools.db import PostgresSalesExecutor
from tools.report import LocalOutbox, preview

DEMO_PRINCIPAL = "demo-analyst"  # trusted server-side selection; not a user-chosen role


@dataclass
class Services:
    caps: CapabilityStore
    approvals: ApprovalStore
    audit: AuditLog
    dispatcher: Dispatcher
    llm: GemmaClient
    max_steps: int
    operator_token: str
    # Raw capability IDs stay in process memory only; the database holds hashes.
    task_caps: dict[str, str] = field(default_factory=dict)


def build_services(settings: Settings) -> Services:
    settings.actiongate_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.actiongate_db_path, check_same_thread=False)
    audit = AuditLog(conn)
    caps = CapabilityStore(conn)
    approvals = ApprovalStore(conn)
    sales = PostgresSalesExecutor(settings.database_url) if settings.database_url else None

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
    return Services(
        caps=caps,
        approvals=approvals,
        audit=audit,
        dispatcher=dispatcher,
        llm=GemmaClient(settings.ollama_base_url, settings.ollama_model),
        max_steps=settings.max_agent_steps,
        operator_token=settings.demo_operator_token,
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
    return {
        "api": "ok",
        "llm": services.llm.health(),
        "database": "configured" if get_settings().database_url else "not_configured",
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
