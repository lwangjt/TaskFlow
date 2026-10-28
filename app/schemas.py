from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskStatus


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    image: str = Field(min_length=1, max_length=255)
    command: list[str] = Field(min_length=1)
    parent_ids: list[int] = Field(default_factory=list)
    max_retries: int = Field(default=3, ge=0)


class WorkflowResponse(BaseModel):
    workflow_id: int
    status: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    name: str
    status: TaskStatus


class TaskExecutionResponse(BaseModel):
    task_id: int
    k8s_job: str
    status: TaskStatus


class WorkflowStatusResponse(BaseModel):
    workflow_id: int
    status: str
    tasks: list[dict]