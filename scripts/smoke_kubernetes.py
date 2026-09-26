"""Smoke test for Phase 3: Kubernetes MCP client functions against the local
kind cluster. Degrades gracefully (available=false) if the cluster is absent.

Run from the project root with the venv active:
    python scripts/smoke_kubernetes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_kubernetes import client as k8s_client  # noqa: E402

SERVICE = "checkout-api"


def main() -> None:
    summary = k8s_client.get_workload_summary(SERVICE)
    print(f"workload summary: available={summary['available']}")
    if not summary["available"]:
        print(f"  error: {summary.get('error')}")
    if summary["available"]:
        print(f"  replicas: desired={summary['desired_replicas']} ready={summary['ready_replicas']} available={summary['available_replicas']}")
        print(f"  image: {summary['image']}")
        for pod in summary["pods"]:
            print(f"  pod {pod['name']}: phase={pod['phase']} ready={pod['ready']} restarts={pod['restart_count']}")
        for ev in summary["warning_events"]:
            print(f"  warning: {ev['reason']} {ev['message'][:80]}")

    pods = k8s_client.get_pod_status(SERVICE)
    print(f"pod status: available={pods['available']}, count={len(pods.get('pods', []))}")

    deployments = k8s_client.get_recent_deployments(SERVICE)
    print(f"deployments: available={deployments['available']}")
    if deployments["available"]:
        print(f"  current: {deployments['current_version']} revision={deployments['revision']} rollout={deployments['rollout_timestamp']}")
        for rs in deployments["replica_sets"]:
            print(f"  rs rev={rs['revision']} image={rs['image']} created={rs['created_at']}")


if __name__ == "__main__":
    main()