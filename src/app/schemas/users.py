"""User schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.base import PartialUpdate
from app.schemas.past_education import PastEducation, PastEducationCreate


class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    past_education: list[PastEducationCreate] = Field(default_factory=list)


class UserUpdate(PartialUpdate):
    """All fields optional — only send what you want to change."""
    # personal_statement is nullable, so it can be cleared with null. password and
    # past_education are left out: the CRUD layer already ignores a null for them.
    non_nullable = frozenset(
        {
            "first_name",
            "last_name",
            "email",
            "research_interests",
            "career_goals",
            "program_interests",
        }
    )

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    past_education: Optional[list[PastEducationCreate]] = None
    research_interests: Optional[list[str]] = None
    career_goals: Optional[list[str]] = None
    program_interests: Optional[list[str]] = None
    personal_statement: Optional[str] = None


class User(BaseModel):
    """What the backend sends back — note there's no password field here."""
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    past_education: list[PastEducation] = Field(default_factory=list)
    research_interests: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    program_interests: list[str] = Field(default_factory=list)
    personal_statement: Optional[str] = None
    created_at: datetime
    updated_at: datetime
