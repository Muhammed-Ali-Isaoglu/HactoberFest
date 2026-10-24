# ActionGate — Implementation Roadmap for Claude Code

**Project:** ActionGate — Task-Scoped Authorization for AI Agents  
**Target:** Hacktoberfest 2026 (open-source demonstration; obey the specific local Fest's rules independently)  
**Model:** Google Gemma 3 through local Ollama (`gemma3:4b` by default)  
**Last updated:** 2026-10-24  
**Instruction priority:** Security correctness > testability > useful demo > appearance.

> **Claude Code: Treat this document as a project execution specification. Implement the project in the current repository, working phase-by-phase. Do not merely summarize the plan.** First inspect the repository and environment, then execute the next incomplete phase. Keep a checklist and a `PROGRESS.md` of work completed, commands/tests/results, blockers, and security caveats. Do not claim a security property or test result that has not been demonstrated. Do not install OS-level services, delete existing data, publish code, or contact external services without clear user permission. Prefer project-local dependencies and synthetic data. Never expose secrets in logs or commits.

## 0. Product in one paragraph

ActionGate is an enforcement layer for AI agents that grants narrowly scoped capabilities for a user-approved task, evaluates each proposed tool action before execution, and executes permitted actions with real least-privilege credentials. A Gemma-powered local agent can interpret the task and propose tool actions or safe alternatives, **but it never grants itself rights or overrides the policy engine**. The first vertical slice is an analytics assistant for a synthetic sales database and an outbound report tool. The demo demonstrates allowed read queries, blocked writes, blocked sensitive reads, blocked external recipients, and optionally explicit approval for sending a report.

### Non-goals and honesty

- Do **not** market this as the first agent firewall, the first pre-tool-call guardrail, or a comprehensive prompt-injection solution. Compare against existing guardrails and native least-privilege controls.
- It is **not** a general-purpose agent that can run arbitrary shell commands. No shell execution or generic file-write tools in the MVP.
- It is **not** a replacement for database permissions, network segmentation, authentication, or container isolation.
- Do **not** interpret user text, retrieved documents, or model output as proof of a user's identity or authorization.
- No NVIDIA model, Nebius services, NVIDIA hackathon conditions, cloud inference requirements, or vendor-dependent features.
- Do not imply that Hacktoberfest has one universal hackathon deadline/award scheme: a local Fest or DEV Challenge has its own rules.

## 1. User stories and acceptance criteria

1. As a user, I can ask the local Gemma agent to compute sales aggregates; authorized reads succeed and the answer includes an evidence-based result.
2. As a defender/operator, I configure **server-side** who may use what tool/resource and when; the AI cannot authoritatively change its permissions.
3. A task receives a short-lived, server-issued, revocable capability whose allowed table(s), operation(s), recipient(s), maximum row count, and expiry are defined by trusted policy and/or explicit authorized approval.
4. A proposed SQL `DELETE`, `UPDATE`, `INSERT`, `DROP`, unauthorized table access, or unauthorized outbound email is denied **before any side effect**.
5. The actual PostgreSQL connection is **read-only**, even if policy checking is bypassed due to an implementation bug. The demo must prove this with a negative integration test.
6. Send-report operations are always subject to a configured recipient allowlist; approval-required operations pause and require an explicit human action associated with the exact immutable request digest.
7. Every decision produces an audit record (timestamp, user/task ID, tool, canonical resource, decision, policy version, reason, sanitized arguments digest, outcome), without copying secrets or personal data.
8. A Streamlit interface demonstrates policy decisions and actual execution results without fake or hardcoded “AI” output.
9. Automated tests prove legitimate operations work, unauthorized operations are blocked, expired/revoked capabilities fail, and tool paths cannot bypass the guard.
10. Everything can run on one developer machine with Ollama, Python, Docker/PostgreSQL, and no paid model API.

**Definition of done:** Clean setup succeeds; `pytest` runs offline without Ollama; an optional Ollama integration smoke test works with the real model; DB integration tests pass when PostgreSQL is running; at least 20 labeled scenarios are executed; results are saved as JSON/CSV and quoted accurately in README/demo.

## 2. Threat model (write `docs/THREAT_MODEL.md` before implementation)

### Assets
- Sales data, other protected DB tables, verified report recipient, audit trail, capability issuance authority, policy configuration, database credentials.

### Actors and trust boundaries
- Authenticated human: may request tasks but cannot exceed assigned RBAC permissions.
- Gemma model: **untrusted planner** even if running locally; prompt injection and poor reasoning are possible.
- Untrusted strings: user-provided content, query rows, document text, tool results.
- API/policy/capability service: trusted computing base (TCB); requires validation and access controls.
- PostgreSQL executor: trusted code using constrained DB role; SQL execution obeys DB-level permissions.
- Outbound email/report adapter: trusted tool wrapper; in MVP simulate sending through local outbox, never send real mail by default.

### In-scope attacks
- Out-of-scope SQL operation or relation, including joins, CTEs, comment tricks and attempts to hide mutations.
- Model-proposed attempts to use alternate tools or recipient addresses to bypass task constraints.
- Tampered or expired capability, cross-task token replay, approvals for a different tool call.
- Prompt-injection text inside data attempting to override the system policy.
- Several individually permitted actions that exceed a task's overall row/request quota (basic cumulative budget).
- Malformed tool arguments or unexpected tool errors.

### Out of scope for the MVP
- Kernel compromise, admin/root attacker, attacker with policy signing key, all possible database covert channels, realistic enterprise IAM, arbitrary web browsing, end-to-end DLP of unstructured results, perfect prevention of multi-step attacks.

### Security invariants
- **Fail closed**: missing policy, invalid token, exceptions, unknown tool/resource => DENY.
- **No independent agent credentials**: agent environment cannot access PostgreSQL connection secrets or privileged tool endpoints directly.
- **Authorization is external to the model**: no `if llm_says_safe` checks as enforcement.
- **Server-side policy**: model text can request permissions, but cannot issue or grant them.
- **Use exact action binding**: human approval valid only for matching task, resource, canonical arguments digest, and TTL; consume once.
- **Enforcement at execution**: policy check happens on canonical typed actions within the trusted executor; avoid a separate check/execute race when possible.
- **Real DB restriction**: read-only PostgreSQL role on a dedicated permitted view/schema, read-only transaction and statement timeout. No superuser access.
- **No secret leakage**: sanitize audit logs and model prompts; store credentials only in untracked env files.

## 3. Architecture

```text
User + Demo UI (Streamlit)
        |
        v
FastAPI Auth/Task API ---------> Task capability issuer (trusted, policy-based)
        |                                  |
        v                                  v
Gemma3 via Ollama  ---> proposed typed ToolAction JSON
        |                                  |
        +---------------------> ActionGate guarded dispatcher
                                         |      |
                              canonicalize    verify task / user /
                              + validate       capability / expiry /
                                               quotas / operation
                                         |
                                  ALLOW / DENY / APPROVAL_REQUIRED
                                         |
                      +------------------+-------------------+
                      |                                      |
               constrained SQL                     report-outbox adapter
               executor with                           (mock by default)
               read-only DB role
                      |                                      |
                      +------------------+-------------------+
                                         |
                                 audit log + metrics
```

### Proposed components
- `api/main.py`: FastAPI endpoints.
- `core/models.py`: Pydantic action, capability, decision and audit schemas.
- `core/policy.py`: deterministic rule engine.
- `core/capabilities.py`: issuance, expiration, revocation, quota, task binding.
- `core/dispatcher.py`: the **only** execution path for tools, with request canonicalization and enforcement in-process.
- `core/sql_guard.py`: SELECT-only parser/checker for demo supported dialect; use `sqlglot` with PostgreSQL dialect **plus** read-only DB role; parser is defense-in-depth, not the final security boundary.
- `tools/db.py`: scoped PostgreSQL query executor; no arbitrary database name/hostname argument, no raw connection access in the agent.
- `tools/report.py`: local outbox adapter with explicit recipient constraints (real email sending optional, off by default).
- `agent/gemma_client.py`: Ollama chat integration and JSON schema output (validate all parsed output).
- `agent/loop.py`: bounded planning loop; route only schema-valid known tools, no direct arbitrary execution.
- `ui/app.py`: Streamlit demo.
- `tests/`: unit, integration, adversarial and evaluation tests.
- `docs/`: threat model, architecture, demo script, alternatives, decision log.

### API design (MVP)
- `GET /health` — readiness of API; report Ollama and DB statuses separately without leaking credentials.
- `POST /tasks` — authenticated operator requests a specific template (e.g. `sales_read_report`); server issues short-lived scoped capability based on static trusted policy; never simply accept client-supplied full permissions.
- `POST /tasks/{task_id}/chat` — user message => Gemma proposes typed tool calls => guard dispatches => returns answer, decisions, tool outcomes.
- `GET /tasks/{task_id}/audits` — sanitized audit trail; task owner or operator only.
- `GET /tasks/{task_id}/pending-approvals` — pending requests visible to authorized user.
- `POST /approvals/{approval_id}` — approve/deny by authorized operator; binds to immutable action digest and expires quickly; **never** re-executes a modified call.
- `GET /metrics` — labeled evaluation counters and performance timing, no personal records.

For the hackathon demo, a seeded demo identity with trusted server-side selection is acceptable if clearly labeled "demo only". Do not present a user-selected role dropdown as secure authentication. Implement a configurable token-based demo operator auth and explain production OIDC would be needed later.

## 4. Gemma + Ollama installation and setup

**Recommended model:** `gemma3:4b` (~3.4 GB model download according to Ollama library; runtime RAM requirements vary). Select this as a pragmatic, available baseline, not as a benchmark winner. If local resources permit, also test `gemma3:12b` (~8.2 GB download); otherwise keep 4B. Small/older machines may need `gemma3:1b` (~806 MB download), but expect weaker reasoning. We cannot assume the development computer has sufficient memory. Use model tags rather than a floating `latest`.

Install Ollama from **https://ollama.com/download** (macOS/Windows installer) or official Linux installation instructions. The user's OS/platform must be determined from current machine before installing.

```bash
# Once Ollama is installed and its local service is running:
ollama --version
ollama pull gemma3:4b
ollama list
ollama run gemma3:4b "Return a one-sentence greeting."

# Test local API; never expose Ollama on a public host:
curl http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma3:4b","messages":[{"role":"user","content":"Respond with the word READY"}],"stream":false}'
```

If Ollama isn't running, use the platform's official startup instructions; on Linux CLI installations `ollama serve` may be appropriate. Avoid automatically creating system services without permission.

```bash
python3 -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install fastapi 'uvicorn[standard]' pydantic pydantic-settings httpx \
  psycopg[binary] sqlglot streamlit pytest pytest-asyncio ruff
```

Pin versions in `pyproject.toml` / lock file after a successful install. Avoid unbounded dependency versions in the final project. Use a local `httpx.AsyncClient` or `ollama` Python library. For greater portability use Ollama's HTTP `/api/chat` API. Prefer JSON schema/structured output if supported by installed Ollama and chosen model; retry boundedly on schema errors. Do **not** assume native function/tool calling is guaranteed by Gemma 3. A constrained structured-action JSON loop is acceptable. Tool action validation and authorization are mandatory even for well-formed JSON.

`.env.example`:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:4b
DATABASE_URL=postgresql://actiongate_reader:change_me@127.0.0.1:5433/actiongate_demo
DEMO_OPERATOR_TOKEN=replace_me_locally
TASK_TTL_SECONDS=900
MAX_AGENT_STEPS=6
MAX_TASK_QUERIES=10
MAX_ROWS_PER_QUERY=100
OUTBOX_MODE=local
```

Keep `.env` out of version control; avoid embedding `DATABASE_URL`, token or report content in prompts or output. Do not require cloud access after Ollama/model download.

## 5. Data and execution isolation

Use `docker compose` for local PostgreSQL **only**. Provide `docker-compose.yml`, `db/init/001_schema.sql` and synthetic seed data, e.g. `sales` with 50–200 rows, `customers_private` with fabricated values (clearly synthetic), `sales_summary_safe` view. Container DB port bound to `127.0.0.1:5433` (do not expose network-wide); sensible resource limits. The database admin password is injected via local env and not committed.

- Create `actiongate_reader` with SELECT on only `sales_summary_safe` (or an explicit allowlisted table). No INSERT/UPDATE/DELETE/TRUNCATE/CREATE/EXECUTE on other schemas, no superuser, no bypass RLS.
- Revoke default PUBLIC privileges in demo schema as appropriate; avoid leakage through functions.
- Set `default_transaction_read_only=on` for reader role, `statement_timeout`, restrictive `search_path` and per-query row cap enforced by executor.
- Validate queries using `sqlglot` SELECT grammar and explicit allowed relation + column names. Reject query statements with writes, multiple statements, administrative commands, restricted functions, or unsupported grammar. Do not trust this parser as the security boundary.
- If robust arbitrary SELECT validation is too complex in the time budget, switch to **predefined typed analytics operations** (e.g. `aggregate_sales_by_day`, `top_products`) with parameterized SQL instead. This is the preferred secure fallback and probably best MVP. Avoid promising arbitrary SQL safety.
- Egress/report: store generated report in a local file or SQLite outbox and mark `simulated_sent`; do not send real emails during tests. Enforce recipients on server side.

## 6. Policy and capability design

A policy may specify `principal`, `task_type`, `allowed_tool`, `allowed_resource`, `operation`, `recipient_allowlist`, `row_limit`, `query_budget`, `expires_at`, `requires_approval`, `policy_version`. Define Pydantic schemas and typed enums. The default action is DENY. Policy files are loaded from a trusted server-side location, not from prompts.

Example *issued* capability (the server creates it; not an instruction that the client can forge):

```json
{
  "task_id": "task-123",
  "principal": "demo-analyst",
  "allowed_actions": ["db.sales_aggregate", "report.preview"],
  "resources": ["sales_summary_safe"],
  "recipient_allowlist": ["analyst@example.org"],
  "max_rows_per_call": 100,
  "max_queries_total": 10,
  "expires_at": "server-assigned UTC timestamp",
  "policy_version": "v1"
}
```

Use server-held opaque random capability IDs rather than trusting mutable client JSON; hash or securely store IDs and bind to authenticated user. Store state in SQLite for MVP (expiry, revocation, quotas); audit logs in SQLite, separated from user-visible execution data. Atomically decrement query budget at dispatch. Approval is a separate one-time token bound to the normalized action payload digest. Recheck capability and policy at execution time after approval.

### Example expected policy outcomes

| Action | Expected decision | Reason |
|---|---|---|
| Aggregate sales by day from allowed safe view | ALLOW | Authorized scoped read |
| Query `customers_private` | DENY | Resource not in scope and DB denies |
| Update or delete records | DENY | Read-only policy and DB role |
| Generate report preview | ALLOW | Safe local operation |
| Send report to verified allowlisted recipient | APPROVAL_REQUIRED | Explicit side effect |
| Send report to random external recipient | DENY | Recipient not allowlisted |
| Use task token after expiry/revocation | DENY | Capability invalid |
| Request unsupported tool `shell_exec` | DENY | Not registered |

## 7. Agent loop

1. User enters task; API obtains trusted user identity and a known task type, issues scoped capability.
2. Gemma receives system prompt describing task and **listed tool schemas**; tool outputs are data, never new authority.
3. Gemma returns a JSON object: `{"type":"tool_call","tool":"db.sales_aggregate","arguments":{...}}` or `{"type":"final","answer":"..."}`.
4. Strict parse against Pydantic union; reject any unregistered or malformed action, log sanitized failure.
5. Guard dispatcher canonicalizes structured arguments, evaluates static policy + capability + quotas + expiry.
6. If DENY: return minimal structured reason (without secrets) and let agent choose a narrower authorized alternative. Limit total iterations.
7. If APPROVAL_REQUIRED: pause; show exact action/recipient/report digest to user; resume only with valid one-time approval.
8. If ALLOW: trusted executor performs constrained DB/read/outbox action and records its actual outcome.
9. On completion, agent summarizes tool-observed results accurately. Never fabricate a success if tool failed.

No unrestricted Python execution, arbitrary shell commands, arbitrary URLs, tool definitions generated by the LLM, or ability to edit policy from the agent.

## 8. Work phases (complete in order; each phase has a gate)

### P0 — Repo and environment discovery (first task)
- Inspect existing files without deleting/replacing anything.
- Check Python, Docker/Podman, Ollama, RAM/disk (best effort; no invasive system probe), git status.
- Generate `docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/DECISIONS.md`, `PROGRESS.md`.
- Verify OS; provide installation steps appropriate to the environment.
- **Gate:** docs and setup decisions exist; model selection matches available hardware. If a missing dependency needs permissions, report it instead of pretending to install it.

### P1 — Minimal local infrastructure
- `pyproject.toml`, `.gitignore`, `.env.example`, docker compose, synthetic database, migrations/seed, health endpoint.
- Database role is truly read-only on allowed view; unauthorized SQL rejected by PostgreSQL.
- **Gate:** startup reproducible, DB read-only test passes.

### P2 — Deterministic security core
- Typed tool action schemas, policy evaluator, capability issuance+expiry+revocation+quota, guarded dispatcher, mock report outbox, audit trail.
- Unit tests for grants, denials, expired tokens, unknown tools, approval digest mismatch, quotas.
- **Gate:** all protected operations can only be called via trusted dispatcher in the demo, and denied operations cause no side effects.

### P3 — Real Gemma integration
- Integrate Ollama with timeout handling, retries and model availability diagnostics.
- Agent produces structured actions; invalid JSON is safely rejected with bounded retry.
- Demonstrate allowed analytics question and malicious/unapproved action prompt.
- **Gate:** a real Gemma call completes an authorized task; policy remains deterministic without model use.

### P4 — UI and approval UX
- Streamlit task panel; visible scope/TTL; live timeline of proposed tool actions and allow/deny/approval; human approval screen, read-only audit table, local report preview, reset demo.
- Include warning banner “research/demo security prototype — not production hardened.”
- **Gate:** demo works for allow, deny and approval scenarios and uses live backend, not hardcoded simulation.

### P5 — Evaluation and hardening
- Build labeled scenario set >=20, ideally 30–50, with categories in Section 9.
- Run offline policies deterministically; separately run live Gemma tasks when available.
- Compare: (A) baseline agent, same constrained resources but **no task-scoped gate** in an isolated synthetic environment, (B) static generic command/tool denylist, (C) ActionGate. **Never run baseline against real/private databases.**
- Collect metrics and limitations, check no sensitive log output and no bypass of approved execution paths.
- **Gate:** transparent reproducible results and no known bypass of the defined MVP trust boundary.

### P6 — Docs, demo, Hacktoberfest handoff
- README (problem, threat boundary, prerequisites, quickstart, commands, architecture, actual benchmarks, explicit limitations).
- `CONTRIBUTING.md`, `LICENSE` after user agrees to license choice, `SECURITY.md` vulnerability reporting, `docs/DEMO.md` 2–3 minute script, `docs/EVALUATION.md` with raw results.
- Open source workflow: issues marked `good first issue` / `hacktoberfest`, tests in CI (offline tests), no unapproved public repo upload. Check specific Hacktoberfest event page before claiming eligibility/prizes.
- **Gate:** another developer can follow setup on a clean machine; all real claims have sources/test output.

## 9. Required tests (at least these)

**Authorization:** authorized aggregate; unauthorized table; unknown tool; expired capability; revoked capability; cross-user/task token; client-supplied forged scope; missing policy; stale policy version; quota exhausted; recipient not allowlisted.

**Execution:** DB role cannot mutate schema/data even when query is executed directly; read from private table fails; parser rejects multi-statement/comment-smuggled write and unsupported SQL; limits and timeouts apply; tool errors do not cause unsafe fallback.

**Human approval:** no approval => no send; approval for different digest rejected; token replay rejected; approval expiration; approval revoked; changing recipient after approval rejected.

**Prompt injection:** synthetic rows with instructions to run a destructive command; prompt attempting to alter user identity; model claiming system privilege; tool output containing fake system directive; conflicting agent explanation. Confirm policy results remain unchanged.

**System:** Ollama down => fail gracefully; malformed model JSON; concurrent quota decrement; audit contains no connection string/token; healthy setup; no network mail sent.

**Failure expectations:** Define all scenario expected results in a checked-in fixture before running them. Do not overfit after seeing outputs; record any failures honestly.

### Metrics and formulas
- Unauthorized-action block rate = correctly denied unauthorized attempts / all unauthorized attempts.
- Legitimate-action allow rate = correctly allowed legitimate actions / all legitimate attempts.
- False-positive block rate = blocked legitimate actions / all legitimate attempts.
- Task completion = fully completed authorized tasks / all attempted authorized tasks.
- Extra guard latency: p50/p95 milliseconds over >=100 policy decisions; measure separately from Ollama inference.
- Report overhead and user-approval prompts per successful task.
- Security statement must be bound to tested tools/scenarios: never claim "100% secure".

### Suggested labeled scenarios
- 10 authorized cases: daily sum, product ranking, filtered aggregation, preview, approved delivery, valid pagination, scoped date intervals, two consecutive reads in quota, partial report, valid role.
- 10 unauthorized cases: DELETE, UPDATE, private relation, rogue recipient, unknown tool, forged capability, expired token, cross-task replay, hidden write attempt, injected instruction in tool output.
- 5 edge cases: quota exactly exceeded, approval token replay, malformed JSON, Ollama unavailable, DB timeout.

## 10. Suggested repository layout

```text
actiongate/
├── README.md
├── PROGRESS.md
├── LICENSE                    # only after user chooses license
├── CONTRIBUTING.md
├── SECURITY.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── docker-compose.yml
├── db/
│   └── init/
│       ├── 001_schema.sql
│       └── 002_seed.sql
├── api/
│   ├── __init__.py
│   └── main.py
├── core/
│   ├── __init__.py
│   ├── models.py
│   ├── policy.py
│   ├── capabilities.py
│   ├── dispatcher.py
│   ├── sql_guard.py
│   └── audit.py
├── agent/
│   ├── __init__.py
│   ├── gemma_client.py
│   ├── prompts.py
│   └── loop.py
├── tools/
│   ├── __init__.py
│   ├── db.py
│   └── report.py
├── ui/
│   └── app.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── adversarial/
│   └── fixtures/
├── eval/
│   ├── run_eval.py
│   ├── scenarios.json
│   └── results/                 # factual test output only
└── docs/
    ├── ARCHITECTURE.md
    ├── THREAT_MODEL.md
    ├── DECISIONS.md
    ├── EVALUATION.md
    ├── DEMO.md
    └── SOURCES.md
```

## 11. Local developer commands (target ergonomics)

```bash
# Check software / pull model (after installing Ollama)
ollama --version
ollama pull gemma3:4b

# Start synthetic PostgreSQL
cp .env.example .env  # replace demo credentials locally
docker compose up -d db

# Install and run
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
# In a second shell:
streamlit run ui/app.py

# Test
pytest -q
ruff check .
python eval/run_eval.py --mode deterministic
# Optional when model and DB are running:
python eval/run_eval.py --mode live
```

Claude Code should ensure these match the real implementation; if a command is unsupported, fix the code or documentation. Never leave a README with fabricated success outputs.

## 12. Competitor comparison and differentiation

Research/describe: NVIDIA NeMo Guardrails action-rail request #2001, GoPlus AgentGuard, conventional RBAC/OPA, NeMo tool middleware. We are **not** claiming novelty for pre-tool interception. State the targeted differentiation as `task-scoped, verifiable least-privilege enforcement with explicit resource/recipient bindings and reproducible policy tests`, and evaluate it rather than assert superiority.

## 13. Public sources for context and presentation (verify before publication)

1. OWASP Top 10 for Agentic Applications: https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/ — agent goal hijacking, tool misuse, identity/privilege abuse are recognized risks. The list has 10 categories, **not** a 10% risk statistic.
2. IBM 2025 Cost of a Data Breach (press release): https://newsroom.ibm.com/2025-07-30-ibm-report-13-of-organizations-reported-breaches-of-ai-models-or-applications%2C-97-of-which-reported-lacking-proper-ai-access-controls — 13% of surveyed organizations reported breaches of AI models/applications; among these, 97% lacked proper AI access controls. Global mean breach cost $4.44M in the study. These are **not** ActionGate results, not agent-specific causal estimates, and must not be presented as current-year 2026 figures.
3. NVIDIA NeMo Guardrails feature request #2001 (2026-06-06): https://github.com/NVIDIA-NeMo/Guardrails/issues/2001 — documented community request for pre-execution tool call inspection; does not establish that NVIDIA lacks all middleware enforcement mechanisms today.
4. Ollama Gemma 3 model page: https://ollama.com/library/gemma3 — sizes/tags: `gemma3:4b` ~3.4 GB download; `gemma3:12b` ~8.2 GB; `gemma3:1b` ~806 MB. Verify currently displayed tags.
5. Hacktoberfest FAQ: https://hacktoberfest.com/questions — 2026 focus and event-specific project rules; regular PRs no longer qualify for participant rewards on their own.

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Gemma not strong at structured tool calls | JSON/Pydantic validation, short schema, retry bound, deterministic scripted demo fallback explicitly labeled |
| Model too slow on laptop | 4B model, shorten prompts/context, reduce loop length; 1B for smoke tests only |
| Arbitrary SQL parsing incomplete | Use typed query templates instead; DB readonly permissions always enforced |
| Approval race/replay | Immutable action digest, TTL, single-use transactional approval, re-check policy |
| UI deceptively implies protection | Expose actual backend decisions and tests, display prototype limitations |
| Competitor already has similar product | Benchmark specific task-scoped policies against baseline, no first-ever claims |
| Risk of leaking synthetic or real secrets | Demo uses synthetic data, env not committed, logs redacted, no outbound mail |
| Time budget | Finish P0–P3 and security tests before advanced UI or frameworks |

## 15. Claude Code execution protocol

**Do this now when this file is provided to you:**

1. Read this complete file and inspect repo (`pwd`, files, git status) without changing unrelated files.
2. Report environment assumptions and top 3 technical risks in `PROGRESS.md`.
3. Create a prioritized checklist mapping P0–P6 to deliverables with `TODO/IN PROGRESS/DONE/BLOCKED`.
4. Implement P0, then P1, then P2, validating with commands/tests at each gate. Continue through later phases where possible in this execution session; do not stop merely to restate the plan.
5. If a dependency/install requires elevated permission or external download, give exact commands and proceed with non-blocked work; do not claim the installation completed until verified.
6. Prefer small coherent commits, but **do not push** or publish without explicit authorization. Don't overwrite user work.
7. On every phase completion update `PROGRESS.md` with observed test counts, commands, failures, decisions, remaining work. If tests fail, correct root cause and rerun before continuing.
8. End with a concise status: implemented modules, test outputs, security limits, files changed, exact commands to run/demo, and next unresolved items.

**Success criterion:** This project is a demonstrably working task-scoped authorization prototype, not a prompt-based safety classifier and not a UI mockup.
