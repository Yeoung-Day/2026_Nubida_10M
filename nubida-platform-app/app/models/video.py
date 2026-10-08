"""
Video Model — 강좌 영상 관리
"""
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime
from sqlalchemy.sql import func

from app.core.database import Base
from app.models import PK, FK_I


class Video(Base):
    __tablename__ = "videos"

    id = PK()
    course_id = FK_I("courses.id")
    title = Column(String(200), nullable=False)
    description = Column(Text)
    url = Column(String(500), nullable=False)
    video_type = Column(String(20), nullable=False, default="youtube")  # youtube / vimeo / upload
    thumbnail_url = Column(String(500))
    duration_seconds = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
