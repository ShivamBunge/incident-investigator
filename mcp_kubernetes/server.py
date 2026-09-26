"""Kubernetes MCP server — small, read-only, demo-namespace scoped.

Tools (spec Section 5.3):
    get_workload_summary
    get_pod_status
    get_recent_deployments

Security: dedicated read-only ServiceAccount (deploy/kind/rbac.yaml); demo
namespace only; no Secret access; no pod exec; no create/update/patch/delete.
Deliberately no generic run_kubectl tool.

Transport: stdio (spawned as a child process by the FastAPI app).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_kubernetes import client as k8s_client

mcp = MCPServer("kubernetes")


@mcp.tool()
def get_workload_summary(service: str) -> dict:
    """Workload state useful for incident investigation: desired/ready/available
    replicas, pod readiness, restart counts, container image, recent warning
    events. Returns available=false if the cluster is unreachable.

    Args:
        service: Service name (deployment name), e.g. checkout-api
    """
    return k8s_client.get_workload_summary(service)


@mcp.tool()
def get_pod_status(service: str) -> dict:
    """Per-pod status: phase, ready/not ready, restart count, last termination
    reason, waiting reason, container image.

    Args:
        service: Service name (pods selected by label app=<service>)
    """
    return k8s_client.get_pod_status(service)


@mcp.tool()
def get_recent_deployments(service: str) -> dict:
    """Current image/version, rollout timestamp when derivable, replica status,
    revision annotation, and recent ReplicaSets.

    Args:
        service: Service name
    """
    return k8s_client.get_recent_deployments(service)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()