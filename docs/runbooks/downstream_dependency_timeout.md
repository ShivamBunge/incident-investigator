# Downstream Dependency Timeout Runbook

Service: checkout-api
Downstream dependencies: payment-service, inventory-service

## Symptoms

- checkout-api latency rises while CPU and memory stay normal.
- Logs show timeout errors naming a downstream dependency, for example `timeout calling payment-service`.
- checkout-api pods are healthy and there is no recent deployment of checkout-api itself.
- The downstream dependency is failing or slow.

## Quick triage

1. Identify the downstream dependency named in the timeout logs.
2. Confirm checkout-api resource usage is normal; rule out local CPU or memory saturation.
3. Check whether the dependency's own dashboards show elevated errors or latency.
4. Verify there was no recent checkout-api deployment that changed timeout or retry configuration.

## Diagnosis

When a downstream dependency degrades, checkout requests block on the outbound call until the client timeout fires. The signature is:

- latency rise without local resource pressure
- repeated `timeout calling payment-service` or similar log lines
- healthy pods and no recent rollout of checkout-api

Distinguish this from database connection pool exhaustion: pool exhaustion logs mention the connection pool, while dependency timeouts name the downstream service.

## Mitigation

- Fail fast: reduce the client timeout for the degraded dependency so request threads are not pinned waiting.
- Enable circuit breaking for the dependency if the client library supports it.
- Escalate to the owning team of the failing dependency; the fix is usually on their side.