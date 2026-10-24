# ActionGate

Task-scoped, least-privilege authorization for AI agents. A local Gemma model (via Ollama) can propose actions. A deterministic dispatcher decides whether each action runs, against a synthetic PostgreSQL database with a read-only role.

> Research / demo security prototype. Not production hardened. It does not claim to stop all prompt injection.

## What it does
- Issues server-side, hashed, expiring, revocable capabilities per task template.
- Validates every proposed tool call, enforces scope, quota and policy, then executes or refuses it.
- Requires a digest-bound, single-use human approval before any outbound report is queued.
- Writes a sanitized audit record for every decision.

## Quickstart
```bash
cp .env.example .env            # then replace every change_me / replace_me value
ollama pull gemma3:4b           # optional: needed for live agent chat
docker compose up -d db         # synthetic PostgreSQL on 127.0.0.1:5433
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
streamlit run ui/app.py         # in a second shell
```

## Tests and evaluation
```bash
pytest -q                                   # offline unit and adversarial tests
DATABASE_URL=... pytest -q -m integration   # needs the docker database running
ruff check .
python eval/run_eval.py --mode deterministic
```

Results are written to `eval/results/`. The current numbers are in [docs/EVALUATION.md](docs/EVALUATION.md).

## Documents
- [Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Decisions](docs/DECISIONS.md) · [Security policy](SECURITY.md)
- Implementation roadmap: [ACTIONGATE_CLAUDE_CODE_ROADMAP.md](ACTIONGATE_CLAUDE_CODE_ROADMAP.md)
