"""Task capabilities: issued server-side, stored as SHA-256 hashes, with expiry, revocation and quota."""

import hashlib
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing

from core.models import Capability
from core.policy import POLICY_VERSION, TASK_POLICIES

SCHEMA = """
CREATE TABLE IF NOT EXISTS capabilities (
    capability_hash TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    task_type TEXT NOT NULL,
    allowed_tools TEXT NOT NULL,
    resources TEXT NOT NULL,
    recipient_allowlist TEXT NOT NULL,
    max_rows_per_call INTEGER NOT NULL,
    max_queries_total INTEGER NOT NULL,
    queries_used INTEGER NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL,
    policy_version TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
"""


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _split(value: str) -> frozenset[str]:
    return frozenset(v for v in value.split(",") if v)


class CapabilityStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock
        self._conn.executescript(SCHEMA)

    def issue(self, task_id: str, principal: str, task_type: str) -> str:
        """Create a capability from trusted policy. Returns the raw ID once; only its hash is kept."""
        policy = TASK_POLICIES[task_type]
        raw = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO capabilities (capability_hash, task_id, principal, task_type, allowed_tools,"
            " resources, recipient_allowlist, max_rows_per_call, max_queries_total, expires_at,"
            " policy_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hash_secret(raw),
                task_id,
                principal,
                task_type,
                ",".join(sorted(policy.allowed_tools)),
                ",".join(sorted(policy.resources)),
                ",".join(sorted(policy.recipient_allowlist)),
                policy.max_rows_per_call,
                policy.max_queries_total,
                self._clock() + policy.ttl_seconds,
                POLICY_VERSION,
            ),
        )
        self._conn.commit()
        return raw

    def get(self, raw_id: str | None) -> Capability | None:
        if not raw_id:
            return None
        return self.get_by_hash(hash_secret(raw_id))

    def get_by_hash(self, cap_hash: str) -> Capability | None:
        with closing(
            self._conn.execute(
                "SELECT capability_hash, task_id, principal, task_type, allowed_tools, resources,"
                " recipient_allowlist, max_rows_per_call, max_queries_total, queries_used, expires_at,"
                " policy_version, revoked FROM capabilities WHERE capability_hash = ?",
                (cap_hash,),
            )
        ) as cur:
            row = cur.fetchone()
        if row is None:
            return None
        return Capability(
            capability_hash=row[0],
            task_id=row[1],
            principal=row[2],
            task_type=row[3],
            allowed_tools=_split(row[4]),
            resources=_split(row[5]),
            recipient_allowlist=_split(row[6]),
            max_rows_per_call=row[7],
            max_queries_total=row[8],
            queries_used=row[9],
            expires_at=row[10],
            policy_version=row[11],
            revoked=bool(row[12]),
        )

    def is_usable(self, cap: Capability) -> str | None:
        """Return a denial reason if the capability cannot be used now, else None."""
        if cap.revoked:
            return "capability revoked"
        if self._clock() >= cap.expires_at:
            return "capability expired"
        if cap.policy_version != POLICY_VERSION:
            return "stale policy version"
        return None

    def spend_query(self, cap_hash: str) -> bool:
        """Atomically consume one unit of query budget. False if exhausted or unusable."""
        cur = self._conn.execute(
            "UPDATE capabilities SET queries_used = queries_used + 1"
            " WHERE capability_hash = ? AND revoked = 0 AND expires_at > ?"
            " AND queries_used < max_queries_total",
            (cap_hash, self._clock()),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def revoke(self, task_id: str) -> int:
        cur = self._conn.execute(
            "UPDATE capabilities SET revoked = 1 WHERE task_id = ? AND revoked = 0", (task_id,)
        )
        self._conn.commit()
        return cur.rowcount
