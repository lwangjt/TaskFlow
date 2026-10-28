import os
import re
from collections.abc import Sequence

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.metrics import TASK_FAILURES_TOTAL


def _load_kubernetes_config() -> None:
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()


def _job_name(task_id: int, task_name: str) -> str:
    suffix = re.sub(r"[^a-z0-9-]", "-", task_name.lower()).strip("-")
    suffix = re.sub(r"-+", "-", suffix)[:40].strip("-") or "task"
    return f"taskflow-job-{task_id}-{suffix}"


def submit_k8s_job(
    task_id: int,
    task_name: str,
    image: str,
    command: Sequence[str],
    namespace: str | None = None,
) -> str:
    """Create one non-restarting Kubernetes Job and return its name."""
    namespace = namespace or os.getenv("TASKFLOW_NAMESPACE", "default")
    _load_kubernetes_config()
    job_name = _job_name(task_id, task_name)
    manifest = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace),
        spec=client.V1JobSpec(
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            name="task-container",
                            image=image,
                            command=list(command),
                        )
                    ],
                )
            ),
        ),
    )
    try:
        response = client.BatchV1Api().create_namespaced_job(namespace, manifest)
        return response.metadata.name
    except ApiException as exc:
        TASK_FAILURES_TOTAL.labels(task_name=task_name).inc()
        raise RuntimeError(f"Failed to create Kubernetes Job: {exc}") from exc
