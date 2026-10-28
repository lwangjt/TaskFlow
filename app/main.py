import json
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.executor import submit_k8s_job
from app.metrics import TASK_EXECUTION_LATENCY, TASK_RETRIES_TOTAL
from app.models import Base, Task, TaskStatus, WorkflowRun
from app.schemas import (
    TaskCreate,
    TaskExecutionResponse,
    TaskResponse,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowStatusResponse,
)

app = FastAPI(title="TaskFlow Execution Service", version="1.0.0")


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def _workflow_status(tasks: list[Task]) -> str:
    if not tasks or all(task.status == TaskStatus.PENDING for task in tasks):
        return "PENDING"
    if any(task.status == TaskStatus.FAILED for task in tasks):
        return "FAILED"
    if all(task.status == TaskStatus.COMPLETED for task in tasks):
        return "COMPLETED"
    return "RUNNING"


@app.post("/workflows/", response_model=WorkflowResponse, status_code=201)
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db)):
    workflow = WorkflowRun(name=payload.name, status="PENDING")
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return {"workflow_id": workflow.id, "status": workflow.status}


@app.post("/workflows/{workflow_id}/tasks/", response_model=TaskResponse, status_code=201)
def add_task(workflow_id: int, payload: TaskCreate, db: Session = Depends(get_db)):
    workflow = db.get(WorkflowRun, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    parent_ids = set(payload.parent_ids)
    if len(parent_ids) != len(payload.parent_ids):
        raise HTTPException(status_code=400, detail="Duplicate parent IDs are not allowed")
    parents = (
        db.query(Task)
        .filter(Task.id.in_(parent_ids), Task.workflow_id == workflow_id)
        .all()
        if parent_ids
        else []
    )
    if len(parents) != len(parent_ids):
        raise HTTPException(
            status_code=400, detail="Every parent must belong to this workflow"
        )
    task = Task(
        workflow_id=workflow_id,
        name=payload.name,
        image=payload.image,
        command=json.dumps(payload.command),
        max_retries=payload.max_retries,
        parents=parents,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"task_id": task.id, "name": task.name, "status": task.status}


@app.post("/tasks/{task_id}/execute", response_model=TaskExecutionResponse)
def execute_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == TaskStatus.FAILED and task.retry_count > task.max_retries:
        raise HTTPException(status_code=409, detail="Task retry budget is exhausted")
    if task.status not in (TaskStatus.PENDING, TaskStatus.FAILED):
        raise HTTPException(status_code=409, detail="Task is not ready for execution")
    incomplete = next(
        (parent for parent in task.parents if parent.status != TaskStatus.COMPLETED), None
    )
    if incomplete:
        raise HTTPException(
            status_code=400,
            detail=f"Parent task {incomplete.id} is not completed.",
        )
    task.status = TaskStatus.QUEUED
    db.commit()
    start_time = time.perf_counter()
    try:
        job_name = submit_k8s_job(
            task.id, task.name, task.image, json.loads(task.command)
        )
        task.status = TaskStatus.RUNNING
        db.commit()
        TASK_EXECUTION_LATENCY.labels(
            task_name=task.name, status="success"
        ).observe(time.perf_counter() - start_time)
        return {"task_id": task.id, "k8s_job": job_name, "status": task.status}
    except Exception as exc:
        task.retry_count += 1
        task.status = (
            TaskStatus.PENDING
            if task.retry_count <= task.max_retries
            else TaskStatus.FAILED
        )
        if task.status == TaskStatus.PENDING:
            TASK_RETRIES_TOTAL.labels(task_name=task.name).inc()
        TASK_EXECUTION_LATENCY.labels(
            task_name=task.name, status="failed"
        ).observe(time.perf_counter() - start_time)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse
)
def workflow_status(workflow_id: int, db: Session = Depends(get_db)):
    workflow = db.get(WorkflowRun, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    tasks = [
        {"task_id": task.id, "name": task.name, "status": task.status}
        for task in workflow.tasks
    ]
    return {
        "workflow_id": workflow.id,
        "status": _workflow_status(workflow.tasks),
        "tasks": tasks,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
