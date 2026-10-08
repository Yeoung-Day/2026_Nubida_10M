"""
📋 감사 로그 스키마
"""
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    action: str
    ip_address: Optional[str] = None
    details: Optional[Any] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    status: str = "success"
    data: list[AuditLogResponse] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0
    message: str = ""


class AuditStatsResponse(BaseModel):
    status: str = "success"
    data: dict = {}
    message: str = ""
