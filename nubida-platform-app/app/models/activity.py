"""
📸 활동 영상 모델 — Activities (이미지/영상 갤러리)
"""
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class Activity(Base):
    """활동 영상 — 이미지/비디오 갤러리"""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    file_type = Column(String(10), nullable=False, default="image")  # image / video
    file_path = Column(String(500), nullable=False)
    thumbnail_path = Column(String(500), nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_visible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
