"""Application and task (dashboard) schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.models import ApplicationStatus
from app.schemas.base import PartialUpdate


class Application(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: int
    user_id: int
    program_id: int
    program_name: str
    university_name: str
    status: ApplicationStatus = ApplicationStatus.not_started
    transcripts_done: bool = False
    recommendations_done: bool = False
    statement_done: bool = False
    test_scores_done: bool = False
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ApplicationUpdate(PartialUpdate):
    non_nullable = frozenset(
        {
            "status",
            "transcripts_done",
            "recommendations_done",
            "statement_done",
            "test_scores_done",
        }
    )

    status: Optional[ApplicationStatus] = None
    transcripts_done: Optional[bool] = None
    recommendations_done: Optional[bool] = None
    statement_done: Optional[bool] = None
    test_scores_done: Optional[bool] = None
    notes: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    due_date: Optional[datetime] = None
    application_id: Optional[int] = None


class TaskUpdate(PartialUpdate):
    non_nullable = frozenset({"title", "completed"})

    title: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None


class Task(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    user_id: int
    application_id: Optional[int] = None
    title: str
    due_date: Optional[datetime] = None
    completed: bool = False

class ApplicationCreateResponse(BaseModel):
    success: bool = True
    application: Application

class TaskCreateResponse(BaseModel):
    success: bool = True
    task: Task