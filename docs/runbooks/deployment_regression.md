# Deployment Regression Runbook

Service: checkout-api

## Symptoms

- A new version was deployed to Kubernetes shortly before errors began.
- A new error signature appears in logs that was not present before the rollout.
- Pod readiness may degrade, restart counts may climb, or CrashLoopBackOff may appear.
- The previous version was healthy.

## Quick triage

1. Compare the rollout timestamp with the start of the error rise; a gap of minutes is typical.
2. Check the current container image and rollout revision in Kubernetes.
3. Look for a new exception type in logs that is absent from earlier log windows.
4. Check pod status for waiting reasons such as `CrashLoopBackOff` or failing readiness probes.

## Diagnosis

A deployment regression means the newly rolled out version behaves worse than the previous one. Evidence that supports this root cause:

- errors begin shortly after the rollout
- the new error signature is absent from logs before the rollout
- workload state degraded after the rollout: readiness failures, restarts, or crash loops

Distinguish this from pool exhaustion and dependency timeouts: a regression correlates with the rollout timestamp and often introduces a brand-new error signature.

## Mitigation

- Roll back to the previous known-good image.
- Verify error rate and latency recover after the rollback.
- File a postmortem linking the regression to the specific change.