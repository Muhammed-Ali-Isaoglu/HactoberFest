# Decision log

1. **Typed operations instead of arbitrary SQL.** The agent can only call `db.sales_aggregate` with fixed SQL templates and validated fields. A SQL parser is therefore not the security boundary. Arbitrary SQL is out of scope.
2. **Read-only DB role is the real DB boundary.** The guard is defense in depth; the reader role has no write grants and runs read-only sessions.
3. **SQLite for capability, approval and audit state.** Simple, offline, and enough for a single-machine demo. Not for multi-instance deployment.
4. **Digest-bound approvals.** Approvals store the canonical args JSON and its SHA-256 digest; the approver must submit the same digest; the action is re-authorized before execution.
5. **Demo auth is a shared token that fails closed.** An empty `DEMO_OPERATOR_TOKEN` denies everything. Not a secure login.
6. **No `sqlglot` dependency yet.** Not needed while no arbitrary SQL is accepted. Add it only if a free-form query tool is introduced.
7. **Dependency pins are lower bounds** (`>=`) because the pinned versions in the roadmap had no wheels for Python 3.14 here. Pin with a lock file after a clean install.
8. **Python 3.14 used locally;** `requires-python >=3.11`. Only 3.14 was tested.
