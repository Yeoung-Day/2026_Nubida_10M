from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# ============================================================
# 원격 수업
# ============================================================

class RemoteClassResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    course_id: int
    teacher_id: int
    scheduled_at: Optional[str] = None
    duration_minutes: int = 60
    status: str = "scheduled"
    room_url: Optional[str] = None
    max_participants: int = 30
    recording_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class RemoteClassListResponse(BaseModel):
    status: str = "success"
    data: list[RemoteClassResponse] = []
    message: str = ""
    total: int = 0


class RemoteClassCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    course_id: int
    teacher_id: int
    scheduled_at: str  # ISO datetime string
    duration_minutes: int = Field(default=60, ge=1)
    room_url: Optional[str] = Field(None, max_length=500)
    max_participants: int = Field(default=30, ge=1)
    recording_url: Optional[str] = Field(None, max_length=500)


class RemoteClassUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    scheduled_at: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    status: Optional[str] = None
    room_url: Optional[str] = Field(None, max_length=500)
    max_participants: Optional[int] = Field(None, ge=1)
    recording_url: Optional[str] = Field(None, max_length=500)


# ============================================================
# 원격 수업 출석
# ============================================================

class RemoteAttendanceResponse(BaseModel):
    id: int
    class_id: int
    student_id: int
    join_at: Optional[str] = None
    leave_at: Optional[str] = None
    status: str = "attended"

    class Config:
        from_attributes = True


class RemoteAttendanceListResponse(BaseModel):
    status: str = "success"
    data: list[RemoteAttendanceResponse] = []
    message: str = ""
    total: int = 0
