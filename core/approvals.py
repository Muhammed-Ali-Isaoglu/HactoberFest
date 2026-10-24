"""One-time human approvals bound to the exact canonical action digest."""

import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    capability_hash TEXT NOT NULL,
    task_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    digest TEXT NOT NULL,
    status TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""
APPROVAL_TTL_SECONDS = 300


@dataclass(frozen=True)
class Approval:
    approval_id: str
    capability_hash: str
    task_id: str
    tool: str
    args_json: str
    digest: str
    status: str
    expires_at: float


class ApprovalStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock
        self._conn.executescript(SCHEMA)

    def create(
        self, *, capability_hash: str, task_id: str, tool: str, args_json: str, digest: str
    ) -> str:
        approval_id = secrets.token_urlsafe(16)
        self._conn.execute(
            "INSERT INTO approvals (approval_id, capability_hash, task_id, tool, args_json, digest,"
            " status, expires_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                approval_id,
                capability_hash,
                task_id,
                tool,
                args_json,
                digest,
                self._clock() + APPROVAL_TTL_SECONDS,
            ),
        )
        self._conn.commit()
        return approval_id

    def get(self, approval_id: str) -> Approval | None:
        with closing(
            self._conn.execute(
                "SELECT approval_id, capability_hash, task_id, tool, args_json, digest, status, expires_at"
                " FROM approvals WHERE approval_id = ?",
                (approval_id,),
            )
        ) as cur:
            row = cur.fetchone()
        return Approval(*row) if row else None

    def pending_for_task(self, task_id: str) -> list[dict]:
        with closing(
            self._conn.execute(
                "SELECT approval_id, tool, args_json, digest, expires_at FROM approvals"
                " WHERE task_id = ? AND status = 'pending' AND expires_at > ?",
                (task_id, self._clock()),
            )
        ) as cur:
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def consume(self, approval_id: str) -> bool:
        """Move pending -> approved exactly once. A replay or a race returns False."""
        cur = self._conn.execute(
            "UPDATE approvals SET status = 'approved' WHERE approval_id = ? AND status = 'pending'"
            " AND expires_at > ?",
            (approval_id, self._clock()),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def reject(self, approval_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE approvals SET status = 'rejected' WHERE approval_id = ? AND status = 'pending'",
            (approval_id,),
        )
        self._conn.commit()
        return cur.rowcount == 1
