from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# ============================================================
# 포트폴리오
# ============================================================

class PortfolioResponse(BaseModel):
    id: int
    student_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    content_url: Optional[str] = None
    file_type: Optional[str] = None
    thumbnail_url: Optional[str] = None
    subject: Optional[str] = None
    tags: Optional[str] = None
    is_public: bool = True
    status: str = "draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class PortfolioListResponse(BaseModel):
    status: str = "success"
    data: list[PortfolioResponse] = []
    message: str = ""
    total: int = 0


class PortfolioCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    content_url: Optional[str] = Field(None, max_length=500)
    file_type: Optional[str] = None  # image / pdf / link / video
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    subject: Optional[str] = Field(None, max_length=100)
    tags: Optional[str] = None
    is_public: bool = True


class PortfolioUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    content_url: Optional[str] = Field(None, max_length=500)
    file_type: Optional[str] = None
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    subject: Optional[str] = Field(None, max_length=100)
    tags: Optional[str] = None
    is_public: Optional[bool] = None
    status: Optional[str] = None
