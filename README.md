# Incident Investigator

AI-assisted incident investigator that answers one question: **"Why is this service failing?"**

It combines live incident evidence (exposed through MCP servers), durable engineering knowledge (RAG over runbooks and postmortems), and LLM reasoning into ranked, evidence-cited root-cause hypotheses.

```text
collect relevant evidence
        ↓
retrieve related operational knowledge
        ↓
correlate both
        ↓
produce an evidence-backed root-cause hypothesis
```

## Architecture

```text
                    ┌───────────────────┐
                    │       User        │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   FastAPI App     │
                    │ + Orchestrator    │
                    └───────┬───────────┘
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
     ┌────────────────┐ ┌──────────────┐ ┌────────────────┐
     │ Observability  │ │ Kubernetes   │ │ RAG Retriever  │
     │ MCP Server     │ │ MCP Server   │ │                │
     └───────┬────────┘ └──────┬───────┘ └───────┬────────┘
             │                 │                 │
             ▼                 ▼                 ▼
     deterministic         local `kind`      PostgreSQL
     metric/log data       cluster           + pgvector
     (mock provider)       demo workload
```

- **Observability MCP server** ([`mcp_observability/`](mcp_observability/)) — bounded, read-only tools (`get_service_error_rate`, `get_service_latency`, `get_recent_deployments`, `get_error_log_summary`, `search_logs`, `get_incident_snapshot`) over deterministic incident scenario data. The mock provider sits behind an `ObservabilityProvider` abstraction, so a real Prometheus/Loki adapter can replace it later without changing tool contracts.
- **Kubernetes MCP server** ([`mcp_kubernetes/`](mcp_kubernetes/)) — small read-only integration against a real local `kind` cluster running a demo `checkout-api` workload: `get_workload_summary`, `get_pod_status`, `get_recent_deployments`. Uses a dedicated read-only ServiceAccount scoped to the `demo` namespace — no Secrets, no exec, no writes, no generic `run_kubectl`.
- **RAG layer** ([`app/rag/`](app/rag/)) — markdown-aware chunking (heading-preserving, 400–800 token target), local `sentence-transformers` embeddings (384-dim, zero API cost), pgvector cosine retrieval with service/document-type filters.
- **LLM synthesis** ([`app/llm.py`](app/llm.py)) — OpenRouter (OpenAI-compatible) behind an internal `LLMProvider` adapter. Output must conform to a strict JSON contract; every factual claim must cite collected evidence IDs, and unsupported IDs are rejected ([`app/citations.py`](app/citations.py)).

## The investigation flow

1. Receive question, validate bounded time window (max 6h)
2. Collect metric/log evidence through the observability MCP server (concurrent, per-tool timeouts)
3. Collect workload/pod/deployment evidence through the Kubernetes MCP server
4. Normalize all MCP results into `Evidence` rows (deterministic summaries)
5. Extract dominant symptoms (top log signatures, metric deltas, deployment↔metric-change correlation)
6. Build a focused RAG query, retrieve runbook/postmortem chunks, add as evidence
7. Build a deterministic timeline (ordering from timestamps only — never the LLM)
8. LLM synthesis over the redacted evidence bundle
9. Validate citations — unknown evidence IDs are rejected
10. Persist and return the structured result

One failed tool never fails the investigation: failures are recorded as unavailable sources and the flow continues with partial results.

## Quickstart

```bash
# 1. Environment (Python 3.12+)
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env        # set OPENROUTER_API_KEY

# 2. Database (PostgreSQL + pgvector)
docker compose up -d postgres
alembic upgrade head

# 3. Seed the RAG index
python scripts/seed_docs.py

# 4. Local kind cluster for the demo workload (requires kind + kubectl + Docker Desktop)
kind create cluster --config deploy/kind/cluster.yaml
kubectl apply -f deploy/kind/namespace.yaml -f deploy/kind/checkout-deployment.yaml -f deploy/kind/rbac.yaml

# 5. Run the API
uvicorn app.main:app --reload
# Swagger UI: http://127.0.0.1:8000/docs
```

Run an investigation:

```json
POST /api/v1/investigations
{
  "question": "Why is checkout-api returning 5xx errors?",
  "service": "checkout-api",
  "time_range": { "start": "2026-09-22T13:30:00Z", "end": "2026-09-22T14:30:00Z" }
}
```

The response contains `summary`, `findings`, `hypotheses` (with confidence + supporting/contradicting evidence IDs), `recommendations`, `missing_information`, a deterministic `timeline`, the full `evidence` list, `unavailable_sources`, and `rejected_evidence_ids`. `GET /api/v1/investigations/{id}` returns a stored result.

## Evaluation

```bash
python -m evals.run_evals --retrieval     # Recall@1/3/5 (no LLM needed)
python -m evals.run_evals --investigation # root-cause accuracy (needs OPENROUTER_API_KEY)
python -m evals.run_evals --all           # both; exit code 0 only if all pass
```

Current results on the three seeded scenarios:

| Metric | Result |
|---|---|
| Retrieval Recall@1 / @3 / @5 | 1.00 / 1.00 / 1.00 |
| Root-cause top-1 / top-3 accuracy | 1.00 / 1.00 |
| Tool-selection rate | 1.00 |
| Evidence coverage | 1.00 |
| Unsupported-claim rate | 0.00 |
| Avg investigation latency | ~17–29 s |

Tests: `python -m pytest tests` — 28 tests covering chunking, MCP contracts, citation validation, redaction, timeline determinism, partial failure, and prompt-injection resistance.

## Safety model

- Read-only investigation; no remediation actions.
- All MCP tools are bounded and read-only — no shell, SQL, arbitrary URL, PromQL, or LogQL access (enforced by tests).
- Kubernetes access is a dedicated read-only ServiceAccount, demo namespace only; no Secret reads, no exec, no writes.
- Log/document contents are treated as untrusted; injected instructions never change tool permissions (tested).
- Obvious tokens/secrets are redacted before evidence is sent to the external model ([`app/redaction.py`](app/redaction.py)).
- The model may reason about production, but it must not invent production state: unsupported evidence IDs are rejected and reported.

## Design tradeoffs

- **Why MCP instead of calling integrations directly?** Explicit, bounded tool contracts at a process boundary. The model never gets arbitrary access; the orchestrator controls exactly which tools exist, and the same contracts survive the mock → Prometheus/Loki swap.
- **Why is RAG separate from live evidence?** Different lifetimes and trust models: runbooks are curated durable knowledge; metrics/logs are volatile live state. Mixing them would make retrieval quality unmeasurable.
- **Why is the timeline deterministic?** Event ordering is a timestamp sort over evidence, so the LLM never decides causality by reordering events.
- **Why is Kubernetes real while metrics/logs are mocked?** Real cluster state exercises the full MCP/RBAC/degradation path authentically, without standing up a monitoring stack.
- **Bounded plan, not an autonomous loop:** a fixed step list keeps latency predictable (~20 s), cost bounded, and behavior reproducible for evaluation.
- **Sync SQLAlchemy + async MCP:** DB work is short and transactional; concurrency lives in MCP tool calls where it pays off.

## Repository layout

Per the spec (Section 13): `app/` (FastAPI + orchestrator + RAG), `mcp_observability/`, `mcp_kubernetes/`, `deploy/kind/`, `docs/` (seed runbooks/postmortems), `evals/`, `tests/`, `scripts/` (smoke tests + seeding).

## Build status (Definition of Done)

- [x] Runbooks/postmortems indexed; RAG quality measurable (Recall@1/3/5)
- [x] App communicates with both MCP servers; observability tools bounded + read-only
- [x] Real local `kind` cluster hosts the demo workload
- [x] Kubernetes MCP reads workload/pod/deployment state
- [x] Kubernetes MCP cannot read Secrets, exec, or mutate (RBAC + no such tools)
- [x] Three deterministic incident scenarios
- [x] Evidence normalized before model reasoning
- [x] Deterministic timeline ordering
- [x] Hypotheses reference evidence; unsupported IDs rejected
- [x] Partial tool failure still yields a useful response (tested)
- [x] Root-cause accuracy measurable; one command runs the eval suite
- [x] Docker Compose starts postgres (+ app image buildable)
- [x] README explains architecture and tradeoffs