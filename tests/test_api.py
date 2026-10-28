from unittest.mock import patch

from app.models import TaskStatus


def create_workflow(client):
    response = client.post("/workflows/", json={"name": "build"})
    assert response.status_code == 201
    return response.json()["workflow_id"]


def create_task(client, workflow_id, **overrides):
    payload = {
        "name": "compile",
        "image": "python:3.12",
        "command": ["python", "-c", "print(1)"],
        **overrides,
    }
    return client.post(f"/workflows/{workflow_id}/tasks/", json=payload)


def test_workflow_and_task_lifecycle(client):
    workflow_id = create_workflow(client)
    task = create_task(client, workflow_id)
    assert task.status_code == 201
    task_id = task.json()["task_id"]

    with patch("app.main.submit_k8s_job", return_value="job-1"):
        response = client.post(f"/tasks/{task_id}/execute")
    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.RUNNING
    status = client.get(f"/workflows/{workflow_id}/status")
    assert status.json()["status"] == "RUNNING"


def test_missing_resources_and_dependency_barrier(client):
    assert (
        client.post(
            "/workflows/999/tasks/",
            json={"name": "x", "image": "alpine", "command": ["true"]},
        ).status_code
        == 404
    )
    assert client.post("/tasks/999/execute").status_code == 404
    assert client.get("/workflows/999/status").status_code == 404
    workflow_id = create_workflow(client)
    parent = create_task(client, workflow_id).json()["task_id"]
    child = create_task(
        client, workflow_id, name="package", parent_ids=[parent]
    ).json()["task_id"]
    blocked = client.post(f"/tasks/{child}/execute")
    assert blocked.status_code == 400
    assert "not completed" in blocked.json()["detail"]


def test_parent_validation_and_duplicate_ids(client):
    workflow_id = create_workflow(client)
    parent = create_task(client, workflow_id).json()["task_id"]
    assert (
        create_task(client, workflow_id, parent_ids=[parent, parent]).status_code
        == 400
    )
    other_workflow = create_workflow(client)
    other_task = create_task(client, other_workflow).json()["task_id"]
    assert create_task(client, workflow_id, parent_ids=[other_task]).status_code == 400


def test_failed_submission_retries_then_fails(client):
    workflow_id = create_workflow(client)
    task_id = create_task(client, workflow_id, max_retries=1).json()["task_id"]
    with patch("app.main.submit_k8s_job", side_effect=RuntimeError("cluster down")):
        assert client.post(f"/tasks/{task_id}/execute").status_code == 502
        assert client.post(f"/tasks/{task_id}/execute").status_code == 502
    status = client.get(f"/workflows/{workflow_id}/status").json()
    assert status["status"] == "FAILED"
    assert status["tasks"][0]["status"] == "FAILED"
    assert client.post(f"/tasks/{task_id}/execute").status_code == 409


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "task_execution_duration_seconds" in response.text
