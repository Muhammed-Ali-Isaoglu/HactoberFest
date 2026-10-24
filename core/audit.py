"""Sanitized, append-only audit log in SQLite. Stores digests, never raw arguments or capability IDs."""

import sqlite3
import time
from contextlib import closing

from core.models import Decision

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    task_id TEXT,
    principal TEXT,
    tool TEXT,
    resource TEXT,
    decision TEXT NOT NULL,
    policy_version TEXT,
    reason TEXT NOT NULL,
    args_digest TEXT,
    outcome TEXT NOT NULL
);
"""


class AuditLog:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(SCHEMA)

    def record(
        self,
        *,
        task_id: str | None,
        principal: str | None,
        tool: str | None,
        resource: str | None,
        decision: Decision,
        policy_version: str | None,
        reason: str,
        args_digest: str | None,
        outcome: str,
        now: float | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit (ts, task_id, principal, tool, resource, decision, policy_version,"
            " reason, args_digest, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now if now is not None else time.time(),
                task_id,
                principal,
                tool,
                resource,
                decision.value,
                policy_version,
                reason,
                args_digest,
                outcome,
            ),
        )
        self._conn.commit()

    def for_task(self, task_id: str) -> list[dict]:
        with closing(
            self._conn.execute(
                "SELECT ts, tool, resource, decision, policy_version, reason, args_digest, outcome"
                " FROM audit WHERE task_id = ? ORDER BY id",
                (task_id,),
            )
        ) as cur:
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def decision_counts(self) -> dict[str, int]:
        with closing(
            self._conn.execute("SELECT decision, COUNT(*) FROM audit GROUP BY decision")
        ) as cur:
            return {row[0]: row[1] for row in cur.fetchall()}
