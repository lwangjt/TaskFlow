import enum
from datetime import datetime
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, Table
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

# Association table for task dependencies (DAG edges)
task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column("parent_id", Integer, ForeignKey("tasks.id"), primary_key=True),
    Column("child_id", Integer, ForeignKey("tasks.id"), primary_key=True),
)

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship("Task", back_populates="workflow", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    name = Column(String(255), nullable=False)
    image = Column(String(255), nullable=False)  # Container image for K8s Job
    command = Column(Text, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    workflow = relationship("WorkflowRun", back_populates="tasks")
    
    # Self-referential many-to-many for DAG dependencies
    parents = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=id == task_dependencies.c.child_id,
        secondaryjoin=id == task_dependencies.c.parent_id,
        back_populates="children",
    )
    children = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=id == task_dependencies.c.parent_id,
        secondaryjoin=id == task_dependencies.c.child_id,
        back_populates="parents",
    )