# ActionGate

Task-scoped, least-privilege authorization for AI agents. A local Gemma model (via Ollama) can propose actions. A deterministic dispatcher decides whether each action runs, against a synthetic PostgreSQL database with a read-only role.

> Research / demo security prototype. Not production hardened. It does not claim to stop all prompt injection.

## What it does
- Issues server-side, hashed, expiring, revocable capabilities per task template.
- Validates every proposed tool call, enforces scope, quota and policy, then executes or refuses it.
- Requires a digest-bound, single-use human approval before any outbound report is queued.
- Writes a sanitized audit record for every decision.

## Quick start (for judges)

Requirements: Docker. Nothing else. No model download, no database setup.

```bash
docker compose up --build
```

Open http://localhost:8501. Click an example, or type your own request.

Each result shows three things: what the agent asked for, whether ActionGate allowed or blocked it and why, and the answer. Requests to send a report wait for your Approve or Deny.

The public demo uses a rule-based planner, not a language model, so it runs anywhere. It shows the guard and its decisions. It does not show a model reasoning. Synthetic sales data only; emails are simulated.

## Optional: run the full stack with Gemma

Needs Ollama with `gemma3:4b` and a machine that can run it (a GPU is strongly recommended). Set `PLANNER=ollama` and `SALES_BACKEND=postgres` in `.env`, then:

```bash
docker compose --profile full up --build
```

## Run locally without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
uvicorn api.main:app --host 127.0.0.1 --port 8000   # terminal 1
streamlit run ui/app.py                              # terminal 2
```

## Tests and evaluation
```bash
pytest -q                                   # offline unit and adversarial tests
DATABASE_URL=... pytest -q -m integration   # needs the database (port 5433) running
ruff check .
python eval/run_eval.py --mode deterministic   # offline, no model or database needed
```

Results are written to `eval/results/`. The current numbers are in [docs/EVALUATION.md](docs/EVALUATION.md).

## Documents
- [Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Decisions](docs/DECISIONS.md) · [Security policy](SECURITY.md)
- Implementation roadmap: [ACTIONGATE_CLAUDE_CODE_ROADMAP.md](ACTIONGATE_CLAUDE_CODE_ROADMAP.md)
