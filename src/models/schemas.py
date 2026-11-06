from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskStatus(str, Enum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    REPLANNING = "REPLANNING"
    NEEDS_INFO = "NEEDS_INFO"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class AgentMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    budget: float | None = Field(default=None, ge=0)
    deadline: datetime | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)

    @field_validator("deadline", mode="before")
    @classmethod
    def parse_deadline(cls, value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class TaskStep(BaseModel):
    step_id: str
    step_name: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    tool_name: str
    estimated_cost: float = 0.0
    actual_cost: float | None = None
    estimated_duration: float = 0.0
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None


class ToolResult(BaseModel):
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    partial: bool = False
    retryable: bool = False
    duration_seconds: float = 0.0


class Decision(BaseModel):
    action: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    final_status: TaskStatus | None = None
    message: str | None = None


class AgentResult(BaseModel):
    task_id: str
    status: TaskStatus
    message: str = ""
    proposal_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    steps: list[TaskStep] = Field(default_factory=list)
    traces: list[dict[str, Any]] = Field(default_factory=list)
    budget: float | None = None
    total_cost: float | None = None
    total_duration: float | None = None
    constraint_details: dict[str, Any] = Field(default_factory=dict)


class TraceEvent(BaseModel):
    task_id: str
    step: str
    plan: dict[str, Any] = Field(default_factory=dict)
    action: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    status_change: str = ""
    replanning_reason: str | None = None
    next_action: str = ""
    duration_seconds: float = 0.0
    mode: AgentMode = AgentMode.MOCK
    final_result: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
