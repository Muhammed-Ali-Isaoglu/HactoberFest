# Threat model (MVP)

Research / demo prototype. Not production hardened. Not a substitute for database permissions, network segmentation, or real authentication.

## Assets
Synthetic sales data, synthetic private customer table, the report outbox, the audit log, capability issuance, policy configuration, database credentials.

## Trust boundaries
- **Gemma (via Ollama)**: untrusted planner. Its output is parsed strictly and every action goes through the dispatcher.
- **Tool results and database rows**: untrusted data. They are returned to the model labelled as data only.
- **Policy, capability store, dispatcher, approvals, audit**: trusted computing base.
- **PostgreSQL**: enforces its own permissions for the `actiongate_reader` role.

## Invariants and where they are enforced
| Invariant | Enforcement | Tests |
|---|---|---|
| Fail closed | Unknown task, tool, resource, capability, or policy version => DENY (`core/policy.py`, `CapabilityStore.is_usable`) | `tests/unit/test_policy_capabilities.py` |
| Model cannot grant scope | Arguments are validated with `extra="forbid"`; capabilities come from trusted policy only | `tests/unit/test_dispatcher.py`, `tests/adversarial/test_injection.py` |
| Capability IDs are secrets | Only SHA-256 hashes are stored; raw IDs stay in process memory | `test_raw_capability_id_is_not_stored` |
| Quota is atomic | `UPDATE ... WHERE queries_used < max` in one statement | `test_query_budget_is_enforced_atomically` |
| Approval is exact and single use | Digest over canonical args; `pending -> approved` in one UPDATE; expiry; re-check at execution | `tests/unit/test_dispatcher.py` |
| DB is read-only even if the guard fails | Reader role: SELECT only on `sales_summary_safe`, `default_transaction_read_only`, statement timeout | `tests/integration/test_db_readonly.py` (needs running DB; not yet run) |
| No side effect on denial | Executors are only called after authorization | `db_calls == []` assertions |

## In scope
Out-of-scope SQL (no SQL tool exists; only fixed templates), alternate tools, recipient substitution, forged/expired/revoked/replayed capabilities, prompt injection in data and model output, malformed arguments, budget overrun, executor failures.

## Out of scope
Root/kernel compromise, theft of the policy signing key (none exists in the MVP), real IAM, DLP of free-text results, multi-step covert channels, real email delivery (not implemented; outbox is local and simulated).

## Known gaps
- Demo operator auth is a shared token, not OIDC.
- The capability store lives in SQLite and raw IDs live in API process memory, so a restart invalidates running tasks.
- Gemma's output quality is not measured yet with the live model.
