from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from app.executor import _job_name, submit_k8s_job


def test_job_name_is_dns_safe_and_bounded():
    name = _job_name(4, "A task__with spaces!" * 10)
    assert name.startswith("taskflow-job-4-")
    assert len(name) <= 63
    assert name[-1].isalnum()


def test_submit_job_builds_manifest():
    response = MagicMock()
    response.metadata.name = "taskflow-job-1-demo"
    api = MagicMock()
    api.create_namespaced_job.return_value = response
    with (
        patch("app.executor._load_kubernetes_config"),
        patch("app.executor.client.BatchV1Api", return_value=api),
    ):
        assert submit_k8s_job(1, "Demo", "alpine", ["echo", "ok"], "jobs") == response.metadata.name
    api.create_namespaced_job.assert_called_once()
    assert api.create_namespaced_job.call_args.args[0] == "jobs"


def test_submit_job_wraps_api_errors():
    api = MagicMock()
    api.create_namespaced_job.side_effect = ApiException(reason="forbidden")
    with (
        patch("app.executor._load_kubernetes_config"),
        patch("app.executor.client.BatchV1Api", return_value=api),
    ):
        with pytest.raises(RuntimeError, match="Failed to create"):
            submit_k8s_job(2, "Demo", "alpine", ["echo"])
