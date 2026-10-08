from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# ============================================================
# 영상
# ============================================================

class VideoResponse(BaseModel):
    id: int
    course_id: int
    title: str
    description: Optional[str] = None
    url: str
    video_type: str
    thumbnail_url: Optional[str] = None
    duration_seconds: int = 0
    sort_order: int = 0
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    status: str = "success"
    data: list[VideoResponse] = []
    message: str = ""
    total: int = 0


class VideoCreate(BaseModel):
    course_id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    url: str = Field(..., max_length=500)
    video_type: str = Field(default="youtube")  # youtube / vimeo / upload
    thumbnail_url: Optional[str] = None
    duration_seconds: int = 0
    sort_order: int = 0
    is_active: bool = True


class VideoUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    url: Optional[str] = Field(None, max_length=500)
    video_type: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
