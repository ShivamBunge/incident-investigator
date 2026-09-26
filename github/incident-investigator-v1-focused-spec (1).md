# Incident Investigator — Focused v1 Design & Build Specification

**Status:** Focused, buildable v1  
**Audience:** Engineer implementing the system with an AI coding assistant  
**Primary learning goals:** RAG, MCP, AI-agent orchestration, evaluation, evidence grounding, and basic Kubernetes runtime inspection  
**Implementation language:** Python 3.12+  
**API framework:** FastAPI  
**Persistence:** PostgreSQL + pgvector  
**v1 runtime:** Docker Compose for app/data services + local Kubernetes (`kind`) for the demo workload  
**v1 safety mode:** Read-only investigation; no remediation actions

---

## 1. Product Goal

Build an AI-assisted incident investigator that answers:

> "Why is this service failing?"

The system must combine:

1. **Live incident evidence** exposed through one MCP observability server.
2. **Durable engineering knowledge** retrieved through RAG from runbooks and postmortems.
3. **LLM reasoning** that produces ranked root-cause hypotheses.
4. **Evidence citations** for every important operational claim.

The goal is not to build a full SRE platform.

The v1 goal is to prove that an AI system can:

```text
collect relevant evidence
        ↓
retrieve related operational knowledge
        ↓
correlate both
        ↓
produce an evidence-backed root-cause hypothesis
```

---

## 2. Problem Being Solved

During an incident, an engineer typically checks several sources:

- error-rate and latency metrics;
- application logs;
- recent deployments;
- runbooks;
- previous incidents.

The information is fragmented, and the engineer must manually correlate timestamps and symptoms.

The Incident Investigator reduces this investigation cost by gathering the relevant evidence and presenting a structured diagnosis.

Example input:

```text
Why is checkout-api returning 5xx errors?
```

Example output:

```text
Most likely cause:
Database connection pool exhaustion.

Evidence:
- error rate rose from 0.5% to 9.2% at 14:03
- latency increased at the same time
- logs contain repeated "connection pool timeout"
- the current symptom pattern matches the DB exhaustion runbook

Confidence: 0.87

Next checks:
- inspect active DB connections
- verify whether request handlers release connections correctly
```

The system must distinguish:

- **fact** — directly supported by live evidence;
- **derived finding** — deterministic calculation over evidence;
- **hypothesis** — model-generated explanation;
- **recommendation** — suggested next diagnostic step.

Core rule:

> The model may reason about production, but it must not invent production state.

---

## 3. v1 Scope

### Included

v1 supports:

- text-based incident questions;
- one target service per investigation;
- bounded time window;
- one MCP observability server backed by deterministic mock metric/log data;
- one small Kubernetes MCP server backed by a real local `kind` cluster;
- error-rate lookup;
- latency lookup;
- error-log search/summary;
- Kubernetes workload/pod/deployment inspection;
- RAG over runbooks and postmortems;
- deterministic timeline construction;
- ranked root-cause hypotheses;
- evidence IDs/citations;
- partial-failure handling;
- a small evaluation harness.

### Explicitly excluded from v1

Do **not** implement:

- real Prometheus/Loki integration;
- broad Kubernetes observability or cluster-management features;
- GitHub integration;
- traces;
- automatic remediation;
- authentication/OIDC;
- multi-cluster support;
- multi-agent systems;
- Redis queues;
- streaming responses;
- Helm;
- GitOps;
- autonomous recursive agent loops.

These are extension points only after the core AI system works.

---

## 4. System Architecture

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

The observability MCP server uses deterministic incident datasets instead of real Prometheus/Loki backends.

That is intentional.

The Kubernetes MCP server, however, talks to a real local `kind` cluster running a tiny demo workload. This gives the project genuine Kubernetes state without requiring a full monitoring stack.

The observability MCP contracts must be designed so a real Prometheus/Loki adapter can replace the mock provider later without changing the orchestrator.

---

## 5. Components

### 5.1 FastAPI / Orchestrator

Responsibilities:

- receive investigation request;
- validate service and time window;
- decide which bounded capabilities are required;
- call MCP tools;
- normalize returned evidence;
- query RAG using the user question plus observed symptoms;
- build a timeline;
- call the LLM for synthesis;
- validate citations;
- return structured output.

Do not build an open-ended autonomous loop.

Use a bounded investigation plan.

Example:

```json
{
  "steps": [
    "get_error_rate",
    "get_latency",
    "get_recent_deployments",
    "get_error_log_summary",
    "retrieve_operational_docs"
  ]
}
```

Independent tool calls should execute concurrently.

---

### 5.2 Observability MCP Server

The v1 MCP server exposes only domain-specific read tools.

Required tools:

```text
get_service_error_rate
get_service_latency
get_recent_deployments
get_error_log_summary
search_logs
```

Optional convenience tool:

```text
get_incident_snapshot
```

Do not expose:

```text
run_shell
execute_sql
query_any_url
run_promql
run_logql
```

The model should not get arbitrary system access.

Each MCP result must be structured and bounded.

The observability MCP must use a provider abstraction:

```text
ObservabilityProvider
├── MockObservabilityProvider        # v1
└── PrometheusLokiProvider           # later
```

For v1:

```text
get_service_error_rate
        ↓
MockObservabilityProvider
        ↓
scenario JSON
```

Later:

```text
get_service_error_rate
        ↓
PrometheusLokiProvider
        ↓
Prometheus HTTP API
```

Likewise:

```text
search_logs
        ↓
PrometheusLokiProvider
        ↓
Loki HTTP API
```

The MCP tool names, arguments, and result schemas must remain unchanged when the provider is swapped.

Example:

```json
{
  "service": "checkout-api",
  "metric": "error_rate",
  "points": [
    {"timestamp": "2026-09-22T14:00:00Z", "value": 0.004},
    {"timestamp": "2026-09-22T14:05:00Z", "value": 0.091}
  ]
}
```

---

### 5.3 Kubernetes MCP Server

The Kubernetes integration is intentionally small.

Required read-only tools:

```text
get_workload_summary
get_pod_status
get_recent_deployments
```

The server talks to the local `kind` cluster through the Kubernetes API.

`get_workload_summary(service)` should return only the information useful for incident investigation:

```text
desired replicas
ready replicas
available replicas
pod names
pod readiness
restart counts
container images
recent warning conditions/events when easy to obtain
```

`get_pod_status(service)` should summarize:

```text
phase
ready/not ready
restart count
last termination reason
waiting reason
container image
```

`get_recent_deployments(service)` should return:

```text
current image/version
rollout timestamp when derivable
replica status
revision/annotations when available
```

Security requirements:

- dedicated ServiceAccount;
- read-only access;
- demo namespace only;
- no Secret access;
- no pod exec;
- no create/update/patch/delete permissions.

Do not expose a generic `run_kubectl(command)` tool.

### 5.4 RAG Layer

RAG indexes only:

```text
runbooks
postmortems
known-issue documents
```

Do not index everything.

Each chunk stores:

```text
document_id
title
document_type
service
heading
content
embedding
source_uri
```

Chunking strategy:

- preserve Markdown headings;
- split oversized sections by paragraph;
- target roughly 400–800 tokens;
- store service metadata;
- avoid blind fixed-character chunking.

Retrieval pipeline:

```text
question + observed error signatures
        ↓
embedding
        ↓
vector similarity
        ↓
service/document-type filter
        ↓
top-k chunks
        ↓
citations
```

Example:

```text
Original:
Why is checkout-api failing?

Observed log signature:
sqlalchemy TimeoutError connection pool exhausted

RAG query:
checkout-api sqlalchemy connection pool exhausted runbook
```

Start with vector search + metadata filters.

No reranker in the first implementation unless evaluation proves it is needed.

---

## 6. Core Data Model

Only four persistent concepts are necessary.

### Investigation

```text
id
service
question
start_time
end_time
status
created_at
completed_at
```

### Evidence

```text
id
investigation_id
source_type
evidence_type
observed_at
summary
raw_payload
source_locator
```

Possible `source_type`:

```text
observability
kubernetes
rag_document
derived
```

Possible `evidence_type`:

```text
metric
deployment
log_signature
workload_status
pod_status
runbook_chunk
postmortem_chunk
derived_statistic
```

### Document

```text
id
title
document_type
service
source_uri
content_hash
created_at
updated_at
```

### DocumentChunk

```text
id
document_id
chunk_index
heading
content
embedding
metadata
```

No Redis, ingestion queue, feedback table, user table, or audit database is required for v1.

Tool invocations can initially be emitted as structured logs.

---

## 7. API Surface

Keep the API small.

### `POST /api/v1/documents`

Add a runbook or postmortem.

Request:

```json
{
  "title": "Checkout DB Exhaustion Runbook",
  "document_type": "runbook",
  "service": "checkout-api",
  "content": "..."
}
```

The endpoint parses, chunks, embeds, and stores synchronously in v1.

### `POST /api/v1/investigations`

Request:

```json
{
  "question": "Why is checkout-api returning 5xx errors?",
  "service": "checkout-api",
  "time_range": {
    "start": "2026-09-22T13:30:00Z",
    "end": "2026-09-22T14:30:00Z"
  }
}
```

Response:

```json
{
  "investigation_id": "inv_123",
  "summary": "...",
  "findings": [],
  "hypotheses": [],
  "timeline": [],
  "recommendations": [],
  "evidence": []
}
```

### `GET /api/v1/investigations/{id}`

Returns the previously stored result.

### `GET /health`

Returns application health.

That is enough for v1.

---

## 8. Investigation Flow

```text
1. Receive question
2. Validate time window
3. Collect metric/log evidence through the observability MCP server
4. Collect workload/pod/deployment evidence through the Kubernetes MCP server
5. Normalize all MCP results into Evidence objects
6. Extract dominant observed symptoms
7. Build a focused RAG query
8. Retrieve relevant runbook/postmortem chunks
9. Add retrieved chunks as Evidence
10. Build deterministic timeline
11. Ask LLM to produce findings + hypotheses
12. Validate evidence references
13. Return structured result
```

The LLM should not decide event ordering.

Timeline ordering comes from timestamps.

The LLM should not create evidence.

It only reasons over collected evidence.

---

## 9. LLM Output Contract

The final model output must conform to:

```json
{
  "summary": "string",
  "findings": [
    {
      "statement": "string",
      "evidence_ids": ["ev_1"]
    }
  ],
  "hypotheses": [
    {
      "statement": "string",
      "confidence": 0.0,
      "supporting_evidence_ids": ["ev_1", "ev_3"],
      "contradicting_evidence_ids": []
    }
  ],
  "recommendations": [
    {
      "statement": "string",
      "reason": "string"
    }
  ],
  "missing_information": []
}
```

Rules:

- factual claims require evidence IDs;
- hypotheses must be labeled as hypotheses;
- confidence must not imply certainty;
- unsupported evidence IDs are rejected;
- if data is unavailable, say so explicitly.

---

## 10. Incident Scenarios

Build three scenarios first.

### Scenario A — DB connection pool exhaustion

Signals:

```text
error rate rises
latency rises
logs show connection-pool timeout
Kubernetes workload remains mostly healthy
deployment may or may not be recent
```

Expected RAG match:

```text
DB connection pool exhaustion runbook
```

Expected root cause:

```text
database connection pool exhaustion
```

### Scenario B — Downstream dependency timeout

Signals:

```text
checkout latency rises
checkout logs show timeout calling payment-service
checkout CPU/memory remain normal
```

Expected RAG match:

```text
downstream dependency timeout runbook
```

Expected root cause:

```text
payment-service dependency failure
```

### Scenario C — Bad deployment

Signals:

```text
new version deployed in Kubernetes
errors begin shortly afterward
new error signature appears
pod readiness/restart state may degrade
previous version was healthy
```

Expected RAG match:

```text
deployment regression postmortem/runbook
```

Expected root cause:

```text
recent deployment regression
```

Optional later scenarios:

```text
traffic spike
OOM/memory regression
```

---

## 11. Evaluation

Evaluation is part of the product, not an afterthought.

For each scenario store ground truth:

```text
expected root cause
expected relevant document
expected important evidence
expected tools
```

Measure:

### Retrieval

```text
Recall@1
Recall@3
Recall@5
```

### Investigation

```text
root-cause top-1 accuracy
root-cause top-3 accuracy
correct tool-selection rate
evidence coverage
unsupported-claim rate
```

### Operational

```text
investigation latency
number of MCP calls
LLM token usage
```

A change to chunking, prompts, retrieval, or planning must be runnable against the same evaluation set.

This is one of the main features that makes the project AI-engineering work instead of a demo.

---

## 12. Non-Functional Requirements

### Reliability

- MCP calls have timeouts.
- One failed tool must not fail the entire investigation.
- Partial results are allowed.
- The response must list unavailable evidence sources.

Example:

```text
Metrics available
Logs unavailable
Deployments available

→ complete investigation with warning
```

### Security

- all MCP tools are read-only;
- bounded tool schemas;
- no arbitrary commands;
- treat log/document contents as untrusted;
- prompt instructions found inside logs/docs must never change tool permissions;
- redact obvious tokens/secrets before sending evidence to an external model.

### Maintainability

- Pydantic models at boundaries;
- typed functions;
- small modules;
- version prompts in source control;
- keep LLM provider behind an internal interface;
- tests around MCP contracts and citation validation.

### Performance

Initial targets:

```text
RAG retrieval       < 1 second excluding embedding API
MCP tool timeout    5–10 seconds
full investigation  < 30 seconds target
```

These are development targets, not production SLOs.

---

## 13. Repository Layout

Keep the repository intentionally small.

```text
incident-investigator/
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
│
├── app/
│   ├── main.py
│   ├── api.py
│   ├── models.py
│   ├── db.py
│   ├── orchestrator.py
│   ├── evidence.py
│   ├── timeline.py
│   ├── llm.py
│   └── rag/
│       ├── ingest.py
│       ├── chunk.py
│       └── retrieve.py
│
├── mcp_observability/
│   ├── server.py
│   ├── provider.py
│   └── scenarios/
│       ├── db_pool.json
│       ├── dependency_timeout.json
│       └── bad_deployment.json
│
├── mcp_kubernetes/
│   ├── server.py
│   └── client.py
│
├── deploy/
│   └── kind/
│       ├── cluster.yaml
│       ├── namespace.yaml
│       ├── checkout-deployment.yaml
│       └── rbac.yaml
│
├── docs/
│   ├── runbooks/
│   └── postmortems/
│
├── evals/
│   ├── dataset.json
│   └── run_evals.py
│
└── tests/
    ├── test_rag.py
    ├── test_mcp.py
    ├── test_orchestrator.py
    └── test_citations.py
```

Do not split the FastAPI app into multiple microservices.

---

## 14. Technology Choices

Use:

```text
Python 3.12+
FastAPI
Pydantic v2
PostgreSQL
pgvector
SQLAlchemy
Alembic
official MCP Python SDK
official Python Kubernetes client
kind
kubectl
one LLM provider through an internal adapter
Docker Compose
pytest
```

Do not add infrastructure unless a requirement demands it.

---

## 15. Implementation Order

### Phase 1 — RAG

Build:

```text
document ingestion
markdown-aware chunking
embeddings
pgvector retrieval
citations
retrieval evaluation
```

Exit condition:

```text
correct runbook appears in top 3 for the three seeded scenarios
```

### Phase 2 — MCP

Build one MCP observability server over deterministic scenario data.

Exit condition:

```text
FastAPI application can call bounded MCP tools and normalize results into Evidence
```

### Phase 3 — Small real Kubernetes integration

Create a local `kind` cluster and deploy one tiny `checkout-api` demo workload.

Implement the Kubernetes MCP server with:

```text
get_workload_summary
get_pod_status
get_recent_deployments
```

Use a dedicated read-only ServiceAccount scoped to the demo namespace.

Exit condition:

```text
FastAPI can retrieve real pod/workload/deployment state through MCP
without granting write, Secret, or exec access
```

### Phase 4 — Investigation engine

Combine:

```text
mock observability MCP evidence
+
real Kubernetes MCP evidence
+
RAG evidence
+
timeline
+
LLM synthesis
+
citation validation
```

Exit condition:

```text
all three incidents produce evidence-backed hypotheses
```

### Phase 5 — Evaluation and hardening

Add:

```text
root-cause evaluation
retrieval evaluation
partial-failure tests
prompt-injection tests
timeouts
structured logging
```

At this point, v1 is complete.

Do not add real Prometheus/Loki, GitHub, traces, or remediation before reaching this milestone.

---

## 16. Definition of Done

v1 is complete when:

- [ ] runbooks/postmortems can be indexed;
- [ ] RAG quality is measurable;
- [ ] the application communicates with both MCP servers;
- [ ] observability MCP tool calls are bounded and read-only;
- [ ] a real local `kind` cluster hosts the demo workload;
- [ ] Kubernetes MCP can read workload/pod/deployment state;
- [ ] Kubernetes MCP cannot read Secrets, exec into pods, or mutate workloads;
- [ ] three deterministic incident scenarios exist;
- [ ] evidence is normalized before model reasoning;
- [ ] timeline ordering is deterministic;
- [ ] hypotheses reference evidence;
- [ ] unsupported evidence IDs are rejected;
- [ ] partial tool failure still yields a useful response;
- [ ] root-cause accuracy can be measured;
- [ ] one command runs the evaluation suite;
- [ ] Docker Compose starts the local system;
- [ ] README explains architecture and tradeoffs.

---

## 17. What Makes This SDE2-Level

The project is not SDE2-level because it uses an LLM.

It becomes SDE2-level because it demonstrates:

- clear system boundaries;
- explicit contracts;
- grounded AI output;
- fault handling;
- measurable retrieval quality;
- measurable diagnosis quality;
- security around AI-accessible tools;
- deterministic vs probabilistic responsibility separation;
- architectural tradeoffs;
- a migration path from mocks to production integrations.

A strong interview discussion should cover:

```text
Why MCP instead of calling integrations directly?
Why bounded tools instead of arbitrary queries?
Why is RAG separate from live evidence?
How is RAG quality measured?
How do you prevent hallucinated evidence?
What happens if logs are unavailable?
Why is the timeline deterministic?
How would this change at 10x traffic?
How would Prometheus/Loki replace the mock observability provider?
Why is Kubernetes real while metrics/logs are mocked in v1?
```

---

## 18. Later Extensions — Not Part of v1

Only after v1 works. Kubernetes is already present in a deliberately small read-only form.

### Extension A — Prometheus + Loki

Replace mock observability provider with real adapters:

```text
get_service_error_rate → Prometheus
get_service_latency → Prometheus
get_error_log_summary → Loki
search_logs → Loki
```

Keep MCP tool contracts unchanged.

### Extension B — Deeper Kubernetes evidence

The v1 Kubernetes integration stays deliberately small.

Possible later additions:

```text
Kubernetes Events
probe status
resource requests/limits
OOMKilled reason
ReplicaSet rollout history
```

Do not add write/remediation tools without a separate approval/policy design.

### Extension C — Git correlation

Add:

```text
recent commits
deployment → commit mapping
bounded diff summary
```

### Extension D — Real traces

Only after metrics/log investigation is stable.

---

## 19. Industry Validation / References

This project is intentionally aligned with a real engineering direction: using AI agents to investigate operational failures by gathering and correlating observability evidence.

Google SRE has publicly discussed deploying agentic AI to improve operations in complex distributed systems:

- Google Cloud — **AI in SRE: Where and how Google is deploying agentic AI to improve operations**  
  https://cloud.google.com/blog/products/devops-sre/how-google-sre-is-using-agentic-ai-to-improve-operations

AWS OpenSearch describes an Investigation Agent that performs hypothesis-driven analysis across observability data and surfaces root-cause hypotheses:

- AWS Big Data Blog — **Agentic AI for observability and troubleshooting with Amazon OpenSearch Service**  
  https://aws.amazon.com/blogs/big-data/agentic-ai-for-observability-and-troubleshooting-with-amazon-opensearch-service/

AWS also exposes observability workflows through MCP Apps:

- AWS Machine Learning Blog — **Agentic observability with Amazon OpenSearch Service MCP Apps**  
  https://aws.amazon.com/blogs/machine-learning/agentic-observability-with-amazon-opensearch-service-mcp-apps/

- AWS Developer Guide — **Agentic Observability with MCP Apps**  
  https://docs.aws.amazon.com/opensearch-service/latest/developerguide/opensearch-observability-mcp-app.html

Protocol/platform references:

- MCP Python SDK  
  https://py.sdk.modelcontextprotocol.io/

- Kubernetes RBAC — for the later Kubernetes extension  
  https://kubernetes.io/docs/reference/access-authn-authz/rbac/

---

## 20. Final Build Principle

Keep the first version deliberately narrow:

```text
RAG
+
one mocked observability MCP server
+
one small real Kubernetes MCP server
+
three incident scenarios
+
one controlled investigation flow
+
one evaluation harness
```

Build those pieces deeply.

Do not expand the project because a technology is interesting.

A new component is allowed only when it improves the core question:

> "Can the system determine why this service is failing, and prove its answer with evidence?"
