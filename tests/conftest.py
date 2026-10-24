import sqlite3
from datetime import date

import pytest

from core.approvals import ApprovalStore
from core.audit import AuditLog
from core.capabilities import CapabilityStore
from core.dispatcher import Dispatcher
from tools.db import StaticSalesExecutor
from tools.report import LocalOutbox, preview


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


SAMPLE_ROWS = [
    {
        "sale_date": date(2026, 9, d),
        "product": p,
        "region": "North",
        "quantity": 2,
        "amount": 10.0 * d,
    }
    for d in range(1, 11)
    for p in ("Widget", "Gadget")
]


class Harness:
    def __init__(self, tmp_path, executor=None):
        self.clock = FakeClock()
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.audit = AuditLog(self.conn)
        self.caps = CapabilityStore(self.conn, clock=self.clock)
        self.approvals = ApprovalStore(self.conn, clock=self.clock)
        self.db_calls: list = []
        sales = executor or StaticSalesExecutor(SAMPLE_ROWS)
        outbox = LocalOutbox(tmp_path / "outbox.jsonl")

        def aggregate(args):
            self.db_calls.append(args)
            return sales.aggregate(args)

        self.outbox_path = tmp_path / "outbox.jsonl"
        self.dispatcher = Dispatcher(
            self.caps,
            self.approvals,
            self.audit,
            executors={
                "db.sales_aggregate": aggregate,
                "report.preview": preview,
                "report.send": outbox.queue,
            },
        )

    def issue(self, task_type: str = "sales_read_report", task_id: str = "task-1") -> str:
        return self.caps.issue(task_id, "demo-analyst", task_type)


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path)
