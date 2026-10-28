# TaskFlow Implementation and Operations Specification

## Runtime configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./taskflow.db` | SQLAlchemy database URL. Production should use PostgreSQL. |
| `TASKFLOW_NAMESPACE` | `default` | Namespace used for submitted Jobs. |
| `KUBERNETES_SERVICE_HOST` | unset | Selects in-cluster credentials when present; otherwise the local kubeconfig is loaded. |

The application creates tables at startup. Production deployments should use a migration
tool before introducing schema changes; `create_all` is intentionally limited to the
initial lightweight service.

## API behavior and validation

All write endpoints accept JSON bodies validated by Pydantic:

* `POST /workflows/`: `{"name": "build"}`.
* `POST /workflows/{workflow_id}/tasks/`: `name`, `image`, `command` (an argument
  array), optional `parent_ids`, and optional non-negative `max_retries`.
* `POST /tasks/{task_id}/execute`: checks that every parent belongs to the same
  workflow and is `COMPLETED` before dispatch.
* `GET /workflows/{workflow_id}/status`: returns aggregate status and per-task state.

Unknown resources return `404`. Invalid dependency references, duplicate parents, and
unmet dependency barriers return `400`. A task that is already queued/running returns
`409`. Kubernetes submission failures return `502` and retain retry state.

## State and retry semantics

`PENDING -> QUEUED -> RUNNING` is the successful dispatch path. The Kubernetes Job
uses `restartPolicy: Never` and `backoffLimit: 0`, so retry ownership remains in
TaskFlow. A submission failure increments `retry_count`; while
`retry_count <= max_retries`, the task returns to `PENDING` and
`task_retries_total` increments. Once the retry budget is exhausted it becomes
`FAILED`.

The current service does not yet include a Kubernetes watch/worker that converts a
completed Job into `COMPLETED`. Until that worker is added, completion should be
performed by the future Job watcher rather than inferred from successful API
submission. This prevents a queued Job from being reported as successfully executed.

## Kubernetes security

`k8s-rbac.yaml` uses a namespace-scoped `Role` and grants only Job `create`, `get`,
`watch`, and `delete` permissions to the TaskFlow service account. It does not grant
pod, secret, or cluster-wide permissions. Deployments should set the application Pod's
`serviceAccountName` to `taskflow` and use a non-root container policy.

## Observability

Commands are stored as JSON argument arrays so spaces and quoting inside an individual
argument are preserved; TaskFlow never passes the command through a shell.

`GET /metrics` exposes Prometheus text format. The following labels are stable:

* `task_execution_duration_seconds{task_name,status}` records dispatch latency with
  `success` or `failed` status.
* `task_failures_total{task_name}` counts Kubernetes API failures.
* `task_retries_total{task_name}` counts failures that remain eligible for retry.

## Verification and coverage

Run:

```bash
pip install -r requirements.txt
pytest -q
```

The repository test configuration measures coverage for `app/` and fails below 90%.
The current suite covers API lifecycle, dependency barriers, retry exhaustion,
metrics output, Kubernetes manifest construction, DNS-safe names, and API error
translation.
