# TaskFlow: Technical Specification Document

**Version:** 1.0.0  
**Domain:** Distributed Workflow Orchestration & Container Execution Service  
**Core Stack:** Python, FastAPI, PostgreSQL, SQLAlchemy, Docker, Kubernetes (Batch v1), Prometheus, GitHub Actions

---

## 1. System Overview & Architecture

TaskFlow is a lightweight, reliable workflow execution service designed to coordinate containerized tasks inside a Kubernetes cluster. It exposes a RESTful API for workflow and task ingestion, tracks execution states persistently in PostgreSQL, enforces Directed Acyclic Graph (DAG) dependency constraints, and orchestrates container execution via the Kubernetes API.

```text
+-------------+         REST APIs          +------------------+
| Client / UI | -------------------------> | FastAPI Backend  |
+-------------+                            +------------------+
                                                    |
                       +----------------------------+----------------------------+
                       | Write State                                             | Trigger Job
                       v                                                         v
         +---------------------------+                             +---------------------------+
         | PostgreSQL (Persistent DB)|                             | Kubernetes API (Batch v1) |
         +---------------------------+                             +---------------------------+
                                                                                 |
                                                                                 v
                                                                   +---------------------------+
                                                                   | Isolated Task Pods (Jobs) |
                                                                   +---------------------------+
```

---

## 2. Data Architecture & Schema

The persistence layer uses PostgreSQL with SQLAlchemy as the ORM. The schema models workflows, tasks, and dependency edges.

| Table Name | Description | Key Columns |
| :--- | :--- | :--- |
| `workflow_runs` | Represents an independent pipeline instance. | `id` (PK), `name`, `status`, `created_at`, `updated_at` |
| `tasks` | Individual units of execution within a workflow. | `id` (PK), `workflow_id` (FK), `name`, `image`, `command`, `status`, `retry_count`, `max_retries` |
| `task_dependencies` | Association table defining DAG parent-child edges. | `parent_id` (PK/FK), `child_id` (PK/FK) |

### State Machine Lifecycle (`TaskStatus`)
*   `PENDING`: Task created, waiting for workflow scheduling.
*   `QUEUED`: Dependencies satisfied, waiting for Kubernetes cluster resource allocation.
*   `RUNNING`: Kubernetes Job pod actively executing.
*   `COMPLETED`: Exit code $0$ returned by container.
*   `FAILED`: Non-zero exit code or timeout; eligible for retries up to `max_retries`.

---

## 3. REST API Specification

The service exposes a FastAPI application with JSON request/response contracts.

| Endpoint | Method | Description | Request Body / Parameters |
| :--- | :--- | :--- | :--- |
| `/workflows/` | `POST` | Initialize a new workflow run. | `name: string` |
| `/workflows/{id}/tasks/` | `POST` | Attach a task to a workflow with parent dependencies. | `name`, `image`, `command`, `parent_ids: list[int]` |
| `/tasks/{id}/execute` | `POST` | Evaluate dependencies and dispatch task to Kubernetes. | Path Parameter: `task_id` |
| `/workflows/{id}/status` | `GET` | Retrieve aggregate workflow progress and task states. | Path Parameter: `workflow_id` |
| `/metrics` | `GET` | Expose Prometheus metrics endpoint for scrapers. | None |

---

## 4. Workflow Execution & Dependency Engine

TaskFlow enforces strict sequencing using DAG dependency resolution:
1. **Topological Validation:** When tasks are registered, cycle detection prevents invalid circular dependencies.
2. **Dependency Barrier:** Before a task transitions from `PENDING` to `QUEUED`, the engine verifies that **all parent tasks** have a status of `COMPLETED`.
3. **Retry & Backoff Strategy:** Failed tasks increment `retry_count`. If $\text{retry\_count} < \text{max\_retries}$, the task state reverts to `PENDING` with an exponential backoff delay before re-dispatching.

---

## 5. Containerized Execution (Kubernetes Integration)

Instead of running worker threads locally, TaskFlow isolates each task inside an ephemeral Kubernetes `Job` resource via the official `kubernetes` Python client.

*   **Resource Isolation:** Each task runs in its own container image specified at registration.
*   **Job Manifest Structure:**
    *   `apiVersion`: `batch/v1`
    *   `kind`: `Job`
    *   `restartPolicy`: `Never` (allowing TaskFlow to control retry behaviors directly).
    *   `backoffLimit`: $0$ (delegating retry management to the backend state machine).
*   **Security & RBAC:** The backend service account is granted scoped permissions (`create`, `get`, `watch`, `delete` on `jobs` in the designated namespace) via a Kubernetes ClusterRole and RoleBinding.

---

## 6. Observability & Telemetry

Instrumentation is built using the `prometheus-client` library to track execution health and performance metrics:

*   **`task_execution_duration_seconds` (Histogram):** Measures container execution latency grouped by task name and final status (`success` / `failed`).
*   **`task_failures_total` (Counter):** Tracks aggregate task failures for alerting and error analysis.
*   **`task_retries_total` (Counter):** Tracks how many times tasks required automated retry mitigation.

---

## 7. CI/CD & Deployment Pipeline

Automated pipelines are implemented using GitHub Actions (`.github/workflows/ci.yml`):
1. **Lint & Test:** Runs `flake8`, `black`, and `pytest` with a live PostgreSQL service container.
2. **Docker Build & Push:** Builds the multi-stage FastAPI Docker image and pushes it to a container registry (e.g., GitHub Packages or AWS ECR).
3. **Cluster Deployment:** Applies Kubernetes manifests and rolling updates to the target cluster via `kubectl`.