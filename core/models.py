"""Typed schemas for tool actions, decisions and capabilities."""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class Operation(str, Enum):
    READ = "read"
    PREVIEW = "preview"
    SEND = "send"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SalesAggregateArgs(StrictModel):
    group_by: Literal["day", "product"] = "day"
    start_date: date
    end_date: date
    limit: int = Field(default=100, ge=1, le=100)


class ReportPreviewArgs(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class ReportSendArgs(ReportPreviewArgs):
    recipient: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ToolCall(StrictModel):
    """A model-proposed action. The model is an untrusted planner; this is only a request."""

    tool: str = Field(max_length=64)
    arguments: dict = Field(default_factory=dict)


class Capability(StrictModel):
    """Server-side view of an issued capability. Its raw ID is never stored."""

    capability_hash: str
    task_id: str
    principal: str
    task_type: str
    allowed_tools: frozenset[str]
    resources: frozenset[str]
    recipient_allowlist: frozenset[str]
    max_rows_per_call: int
    max_queries_total: int
    queries_used: int
    expires_at: float
    policy_version: str
    revoked: bool
