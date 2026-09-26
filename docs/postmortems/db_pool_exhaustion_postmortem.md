# Postmortem: Checkout Outage from Database Connection Pool Exhaustion

Date: 2026-08-14
Service: checkout-api
Impact: 38 minutes of elevated 5xx errors on checkout

## What happened

At 09:12 UTC the checkout-api error rate rose from 0.4 percent to 8.7 percent within minutes. Latency rose at the same time. Logs showed repeated `connection pool timeout` errors. Kubernetes pods were healthy throughout the incident.

## Timeline

- 09:12 error rate begins rising
- 09:14 latency p99 exceeds 4 seconds
- 09:16 on-call paged; logs show `sqlalchemy TimeoutError connection pool exhausted`
- 09:31 connection leak fix deployed
- 09:43 error rate back to baseline

## Root cause

A code path introduced in the 2026-08-12 release opened a transaction per retry attempt without returning connections to the pool. Under moderate load the pool exhausted and requests blocked until the pool timeout fired.

## Lessons learned

- The symptom pattern of error rate and latency rising together, pool timeout logs, and healthy pods is characteristic of connection pool exhaustion.
- Connection pool utilization was not alerting; pool utilization alerts were added after this incident.
- A rollback was not required; a targeted fix restored correct behavior.