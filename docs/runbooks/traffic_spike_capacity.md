# Traffic Spike and Capacity Runbook

Service: checkout-api

## Symptoms

- Latency and error rate rise during marketing events or seasonal peaks.
- CPU saturation on pods; the horizontal pod autoscaler is at its maximum replica count.
- No new error signatures in logs; failures are timeouts and load-shedding rejections.

## Quick triage

1. Compare request volume with baseline; a clear spike indicates load-driven degradation.
2. Check CPU throttling metrics and autoscaler events.
3. Rule out dependency failures and connection pool exhaustion signatures before concluding.

## Mitigation

- Scale replicas or raise autoscaler ceilings.
- Enable queue-based load shedding for non-critical endpoints.
- Communicate expected degradation to stakeholders during the event.