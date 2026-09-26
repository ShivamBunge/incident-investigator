"""Read-only Kubernetes access scoped to the demo namespace.

Security requirements (spec Section 5.3):
- dedicated ServiceAccount with read-only RBAC (deploy/kind/rbac.yaml)
- demo namespace only; no Secret access; no pod exec; no write verbs
- graceful degradation: unreachable cluster returns available=False results
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client import ApiException

NAMESPACE = os.environ.get("K8S_NAMESPACE", "demo")
KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "") or None
REQUEST_TIMEOUT = 8  # seconds, matches MCP_TOOL_TIMEOUT_SECONDS

_config_loaded = False


def _load_config() -> None:
    global _config_loaded
    if _config_loaded:
        return
    if KUBECONFIG_PATH:
        k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
    else:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            # Local dev: default kubeconfig written by `kind` (~/.kube/config)
            k8s_config.load_kube_config()
    _config_loaded = True


def _apps() -> k8s.AppsV1Api:
    _load_config()
    return k8s.AppsV1Api()


def _core() -> k8s.CoreV1Api:
    _load_config()
    return k8s.CoreV1Api()


def _unavailable(service: str, exc: Exception) -> dict:
    return {"available": False, "service": service, "error": f"{type(exc).__name__}: {exc}"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _pod_ready(pod) -> bool:
    statuses = pod.status.container_statuses or []
    return bool(statuses) and all(s.ready for s in statuses)


def _restarts(pod) -> int:
    statuses = pod.status.container_statuses or []
    return sum(s.restart_count or 0 for s in statuses)


def _image(pod) -> str | None:
    statuses = pod.status.container_statuses or []
    return statuses[0].image if statuses else None


def _waiting_reason(pod) -> str | None:
    for s in pod.status.container_statuses or []:
        if s.state and s.state.waiting and s.state.waiting.reason:
            return s.state.waiting.reason
    return None


def _last_termination_reason(pod) -> str | None:
    for s in pod.status.container_statuses or []:
        if s.last_state and s.last_state.terminated:
            return s.last_state.terminated.reason
    return None


def _warning_events(service: str) -> list[dict]:
    """Warning events touching objects related to the service, bounded to 10."""
    try:
        events = _core().list_namespaced_event(NAMESPACE, _request_timeout=REQUEST_TIMEOUT)
    except Exception:
        return []
    out = []
    for ev in events.items:
        name = getattr(getattr(ev, "involved_object", None), "name", "") or ""
        if ev.type == "Warning" and service in name:
            out.append(
                {
                    "object": name,
                    "reason": ev.reason,
                    "message": (ev.message or "")[:200],
                    "last_timestamp": _iso(ev.last_timestamp or ev.event_time),
                }
            )
    return out[:10]


def get_workload_summary(service: str) -> dict:
    """Replica counts, pod readiness/restarts, image, recent warning events."""
    try:
        deployment = _apps().read_namespaced_deployment(
            service, NAMESPACE, _request_timeout=REQUEST_TIMEOUT
        )
        pod_list = _core().list_namespaced_pod(
            NAMESPACE, label_selector=f"app={service}", _request_timeout=REQUEST_TIMEOUT
        )
    except (ApiException, Exception) as exc:  # noqa: BLE001 - degrade gracefully
        return _unavailable(service, exc)

    container = deployment.spec.template.spec.containers[0]
    return {
        "available": True,
        "service": service,
        "namespace": NAMESPACE,
        "desired_replicas": deployment.spec.replicas,
        "ready_replicas": deployment.status.ready_replicas or 0,
        "available_replicas": deployment.status.available_replicas or 0,
        "image": container.image,
        "pods": [
            {
                "name": p.metadata.name,
                "phase": p.status.phase,
                "ready": _pod_ready(p),
                "restart_count": _restarts(p),
                "image": _image(p),
            }
            for p in pod_list.items
        ],
        "warning_events": _warning_events(service),
    }


def get_pod_status(service: str) -> dict:
    """Per-pod: phase, readiness, restarts, termination/waiting reasons, image."""
    try:
        pod_list = _core().list_namespaced_pod(
            NAMESPACE, label_selector=f"app={service}", _request_timeout=REQUEST_TIMEOUT
        )
    except (ApiException, Exception) as exc:  # noqa: BLE001 - degrade gracefully
        return _unavailable(service, exc)

    return {
        "available": True,
        "service": service,
        "namespace": NAMESPACE,
        "pods": [
            {
                "name": p.metadata.name,
                "phase": p.status.phase,
                "ready": _pod_ready(p),
                "restart_count": _restarts(p),
                "last_termination_reason": _last_termination_reason(p),
                "waiting_reason": _waiting_reason(p),
                "image": _image(p),
            }
            for p in pod_list.items
        ],
    }


def get_recent_deployments(service: str) -> dict:
    """Current image/version, rollout timestamp, replica status, revision,
    and the most recent ReplicaSets (bounded to 5)."""
    try:
        apps = _apps()
        deployment = apps.read_namespaced_deployment(
            service, NAMESPACE, _request_timeout=REQUEST_TIMEOUT
        )
        rs_list = apps.list_namespaced_replica_set(
            NAMESPACE, label_selector=f"app={service}", _request_timeout=REQUEST_TIMEOUT
        )
    except (ApiException, Exception) as exc:  # noqa: BLE001 - degrade gracefully
        return _unavailable(service, exc)

    rollout_ts = None
    for cond in deployment.status.conditions or []:
        if cond.type == "Progressing" and cond.last_update_time:
            rollout_ts = _iso(cond.last_update_time)

    owned = [
        rs
        for rs in rs_list.items
        if any(
            o.kind == "Deployment" and o.name == deployment.metadata.name
            for o in (rs.metadata.owner_references or [])
        )
    ]
    owned.sort(
        key=lambda r: r.metadata.creation_timestamp
        or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )

    return {
        "available": True,
        "service": service,
        "namespace": NAMESPACE,
        "current_version": deployment.spec.template.spec.containers[0].image,
        "rollout_timestamp": rollout_ts,
        "replica_status": {
            "desired": deployment.spec.replicas,
            "ready": deployment.status.ready_replicas or 0,
            "available": deployment.status.available_replicas or 0,
        },
        "revision": (deployment.metadata.annotations or {}).get(
            "deployment.kubernetes.io/revision"
        ),
        "replica_sets": [
            {
                "revision": (rs.metadata.annotations or {}).get(
                    "deployment.kubernetes.io/revision"
                ),
                "image": rs.spec.template.spec.containers[0].image,
                "created_at": _iso(rs.metadata.creation_timestamp),
                "replicas": rs.spec.replicas,
                "ready_replicas": rs.status.ready_replicas or 0,
            }
            for rs in owned[:5]
        ],
    }