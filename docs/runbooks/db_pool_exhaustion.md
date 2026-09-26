# Checkout DB Connection Pool Exhaustion Runbook

Service: checkout-api
Owner: payments-platform
Severity guidance: SEV2 when error rate exceeds 5 percent, SEV1 when checkout is fully down

## Symptoms

- 5xx error rate on checkout-api rises sharply, often from under 1 percent to high single digits or above.
- p99 latency rises at the same time as the error rate; requests block waiting for a database connection and then time out.
- Application logs contain repeated `connection pool timeout` or `sqlalchemy TimeoutError connection pool exhausted` messages.
- Kubernetes pods remain mostly healthy: replicas ready, no crash loops, CPU and memory within normal range.
- The deployment history may or may not show a recent rollout; this failure mode is load- or leak-driven, not release-driven.

## Quick triage

1. Confirm the error-rate rise and the latency rise started at the same timestamp.
2. Search logs for `connection pool timeout` and `pool exhausted` signatures.
3. Check pod status: if pods are Ready and restart counts are flat, the workload itself is probably not the problem.
4. Check whether a deployment happened shortly before the errors. If one did, also evaluate the deployment regression runbook before concluding.

## Diagnosis

The checkout-api service uses a bounded database connection pool. Under pool exhaustion, request handlers block waiting for a connection until the pool timeout fires. The characteristic signature is:

- error rate and latency rising together
- log signature `sqlalchemy TimeoutError connection pool exhausted`
- healthy pods and no new deployment

Common root causes:

- a slow query holding connections longer than usual
- a connection leak where request handlers do not release connections back to the pool
- a traffic increase that exceeds the configured pool capacity

## Verification steps

- Inspect active database connections and compare the count against the configured pool size.
- Look for sessions stuck in `idle in transaction` state, which indicates leaked connections.
- Correlate the start time of connection growth with the start of the error-rate rise.

## Mitigation

- Restarting the service releases leaked connections and restores the pool temporarily, but the leak returns under load.
- Fix the underlying leak or slow query before closing the incident.
- Consider raising the pool size only after confirming the workload justifies it; a larger pool can shift pressure onto the database.