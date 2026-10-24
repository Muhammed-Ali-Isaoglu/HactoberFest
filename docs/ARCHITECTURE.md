# Architecture

```text
Streamlit UI (ui/app.py)  --HTTP-->  FastAPI (api/main.py)
                                       |
                              agent/loop.py  <--->  Ollama /api/chat (agent/gemma_client.py)
                                       |   proposes ToolCall JSON only
                                       v
                              core/dispatcher.py  (the ONLY execution path)
                               1. capability lookup (hashed)      core/capabilities.py
                               2. tool registered + args validated core/models.py
                               3. capability scope + expiry + revoke + policy version
                               4. static policy                   core/policy.py
                               5. ALLOW -> spend quota -> executor
                                  APPROVAL_REQUIRED -> approvals.py (digest-bound)
                                  DENY -> audit only
                                       |
                 +---------------------+---------------------+
                 |                                           |
        tools/db.py (fixed SQL templates,           tools/report.py (local JSONL outbox,
        reader role, read-only session)             status "simulated_sent")
                                       |
                                 core/audit.py (SQLite, digests only)
```

Files: `core/` security core, `tools/` executors, `agent/` model integration, `api/` HTTP, `ui/` demo, `db/init/` synthetic PostgreSQL, `eval/` deterministic evaluation, `tests/` unit, adversarial, and integration tests.
