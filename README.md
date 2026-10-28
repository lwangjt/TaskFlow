# TaskFlow

TaskFlow is a FastAPI service for registering workflow tasks, enforcing
dependencies, and dispatching each task as an isolated Kubernetes `Job`.
State is persisted with SQLAlchemy and exposed through Prometheus metrics.

## Architecture

```text
Client -> FastAPI -> SQLAlchemy/PostgreSQL
                 -> Kubernetes Batch API -> Task Job
                 -> Prometheus /metrics
```

The local default database is SQLite. Production deployments should set
`DATABASE_URL` to PostgreSQL.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/workflows/` | Create a workflow: `{"name": "build"}` |
| `POST` | `/workflows/{id}/tasks/` | Add a task with image, command arguments, parents, and retry budget |
| `POST` | `/tasks/{id}/execute` | Validate dependencies and submit a Kubernetes Job |
| `GET` | `/workflows/{id}/status` | Return aggregate and per-task status |
| `GET` | `/metrics` | Expose Prometheus metrics |

Task commands are supplied as an argument array, not a shell string:

```json
{
  "name": "compile",
  "image": "python:3.12",
  "command": ["python", "-c", "print('ok')"],
  "parent_ids": [],
  "max_retries": 3
}
```

Dependencies must belong to the same workflow and must be `COMPLETED` before
the child can be dispatched. Submission follows:

```text
PENDING -> QUEUED -> RUNNING
```

Kubernetes submission failures increment the retry count and return the task to
`PENDING` while its retry budget remains. Exhausted tasks become `FAILED`.

## Local development

```bash
python3 -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The interactive API is available at <http://127.0.0.1:8000/docs>.

For local Kubernetes execution, configure a kubeconfig. In-cluster execution
uses the service account when `KUBERNETES_SERVICE_HOST` is present.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./taskflow.db` | SQLAlchemy database URL |
| `TASKFLOW_NAMESPACE` | `default` | Kubernetes namespace for Jobs |
| `KUBERNETES_SERVICE_HOST` | unset | Selects in-cluster Kubernetes configuration |

The service account permissions are defined in [k8s-rbac.yaml](./k8s-rbac.yaml).

## Testing

```bash
pytest -q
```

The test suite enforces at least 90% coverage of `app/`.

## Implementation status

The API currently tracks successful Job submission as `RUNNING`. A Kubernetes
watcher/controller is still required to observe Job completion and transition
tasks to `COMPLETED` or terminal `FAILED` based on the container result. See
[docs/implementation_and_operations.md](./docs/implementation_and_operations.md)
for operational details and known limitations.
