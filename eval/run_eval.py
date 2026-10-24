"""Deterministic evaluation: runs labelled scenarios through the real dispatcher with an in-memory DB.

Usage: python eval/run_eval.py --mode deterministic
Writes eval/results/deterministic.json and eval/results/deterministic.csv.
"""

import argparse
import csv
import json
import sqlite3
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

from core.approvals import ApprovalStore
from core.audit import AuditLog
from core.capabilities import CapabilityStore
from core.dispatcher import Dispatcher
from core.models import ToolCall
from tools.db import StaticSalesExecutor
from tools.report import LocalOutbox, preview

HERE = Path(__file__).parent
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


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


SCENARIOS = HERE / "scenarios.json"
RESULTS = HERE / "results"
BAD_DIGEST = "0" * 64


def build(tmp: Path, clock: FakeClock):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    audit = AuditLog(conn)
    caps = CapabilityStore(conn, clock=clock)
    approvals = ApprovalStore(conn, clock=clock)
    sales = StaticSalesExecutor(SAMPLE_ROWS)
    outbox = LocalOutbox(tmp / "outbox.jsonl")
    dispatcher = Dispatcher(
        caps,
        approvals,
        audit,
        executors={
            "db.sales_aggregate": sales.aggregate,
            "report.preview": preview,
            "report.send": outbox.queue,
        },
    )
    return caps, approvals, dispatcher


def run_scenario(sc: dict, tmp: Path) -> dict:
    clock = FakeClock()
    caps, _, dispatcher = build(tmp, clock)
    task_id = "eval-" + sc["id"]
    raw = caps.issue(task_id, "demo-analyst", sc["task_type"])
    if sc.get("capability") == "forged":
        raw = "forged-capability"
    clock.advance(sc.get("advance_seconds", 0))
    if sc.get("revoke"):
        caps.revoke(task_id)

    observed, latencies, mismatches = [], [], []
    for step in sc["steps"]:
        repeat = step.get("repeat", 1)
        expects = [step["expect"]] * (repeat - 1) + [step.get("expect_last", step["expect"])]
        last = None
        for expected in expects:
            t0 = time.perf_counter()
            last = dispatcher.dispatch(
                raw, ToolCall(tool=step["tool"], arguments=step["arguments"])
            )
            latencies.append((time.perf_counter() - t0) * 1000)
            observed.append(last.status)
            if last.status != expected:
                mismatches.append({"step": step["tool"], "expected": expected, "got": last.status})
        if "after" in step:
            after_statuses = []
            if step["after"] == "approve":
                after_statuses.append(dispatcher.approve(last.approval_id, last.digest).status)
            elif step["after"] == "approve_wrong_digest":
                after_statuses.append(dispatcher.approve(last.approval_id, BAD_DIGEST).status)
            elif step["after"] == "approve_twice":
                after_statuses.append(dispatcher.approve(last.approval_id, last.digest).status)
                after_statuses.append(dispatcher.approve(last.approval_id, last.digest).status)
            elif step["after"] == "reject_then_approve":
                after_statuses.append(
                    "rejected" if dispatcher.reject(last.approval_id) else "not_rejected"
                )
                after_statuses.append(dispatcher.approve(last.approval_id, last.digest).status)
            observed.extend(after_statuses)
            if after_statuses != step["expect_after"]:
                mismatches.append(
                    {"step": step["after"], "expected": step["expect_after"], "got": after_statuses}
                )
    return {
        "id": sc["id"],
        "category": sc["category"],
        "description": sc["description"],
        "observed": observed,
        "pass": not mismatches,
        "mismatches": mismatches,
        "latencies_ms": latencies,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="deterministic", choices=["deterministic"])
    args = parser.parse_args()
    scenarios = json.loads(SCENARIOS.read_text())
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for sc in scenarios:
            results.append(run_scenario(sc, Path(tmp)))

    all_latency = [ms for r in results for ms in r["latencies_ms"]]
    summary = {
        "mode": args.mode,
        "scenarios": len(results),
        "passed": sum(r["pass"] for r in results),
        "failed": [r["id"] for r in results if not r["pass"]],
        "unauthorized_block_rate": None,
        "legitimate_allow_rate": None,
        "guard_latency_ms_p50": round(statistics.median(all_latency), 3),
        "guard_latency_ms_p95": round(sorted(all_latency)[int(0.95 * (len(all_latency) - 1))], 3),
        "guard_decisions_measured": len(all_latency),
    }
    unauth = [r for r in results if r["category"] == "unauthorized"]
    auth_steps = [r for r in results if r["category"] == "authorized"]
    summary["unauthorized_block_rate"] = round(sum(r["pass"] for r in unauth) / len(unauth), 3)
    summary["legitimate_allow_rate"] = round(
        sum(r["pass"] for r in auth_steps) / len(auth_steps), 3
    )

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{args.mode}.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2)
    )
    with (RESULTS / f"{args.mode}.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "category", "pass", "observed", "description"])
        for r in results:
            writer.writerow(
                [r["id"], r["category"], r["pass"], "|".join(r["observed"]), r["description"]]
            )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
