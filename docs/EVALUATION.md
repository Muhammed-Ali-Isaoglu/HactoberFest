# Evaluation

## Deterministic run (offline, no model, in-memory DB)
Command: `python eval/run_eval.py --mode deterministic`
Raw output: `eval/results/deterministic.json` and `eval/results/deterministic.csv`.

| Metric | Result |
|---|---|
| Scenarios | 25 (10 authorized, 10 unauthorized, 5 edge) |
| Passed | 25 / 25 |
| Unauthorized-action block rate | 1.0 (10 / 10 unauthorized scenarios) |
| Legitimate-action allow rate | 1.0 (10 / 10 authorized scenarios) |
| Guard latency p50 / p95 | 0.038 ms / 0.081 ms over 46 decisions |

Caveats:
- These scenarios were written by the same author as the code. They are not an independent benchmark.
- They exercise the dispatcher directly, not the live model. No Gemma output is measured here.
- Latency is in-process only and excludes model inference and database round trips.

## Not yet run
- Live Gemma task completion (`gemma3:4b` is not pulled on this machine).
- Baselines B (static denylist) and A (no gate) from the roadmap.
- PostgreSQL integration tests (`tests/integration`), since Docker was not running during this session.
