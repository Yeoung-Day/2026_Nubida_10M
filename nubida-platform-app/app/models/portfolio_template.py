"""
📁 포트폴리오 템플릿 모델 — 강좌별 포트폴리오 양식 정의
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class PortfolioTemplate(Base):
    """강좌별 포트폴리오 양식 템플릿"""
    __tablename__ = "portfolio_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="포트폴리오")
    description = Column(Text, default="")  # 템플릿 설명
    guide_text = Column(Text, default="")  # 작성 가이드 (안내문)

    # 양식 구성 (JSON)
    # [
    #   {"type": "text", "label": "제목", "required": true, "placeholder": ""},
    #   {"type": "textarea", "label": "내용", "required": true, "placeholder": ""},
    #   {"type": "image", "label": "사진 첨부", "required": false, "max_count": 10},
    #   {"type": "file", "label": "파일 첨부", "required": false, "max_count": 5},
    #   {"type": "video", "label": "영상 링크", "required": false},
    #   {"type": "code", "label": "코드 입력", "required": false},
    #   {"type": "rating", "label": "만족도", "required": false, "max": 5},
    # ]
    form_fields = Column(JSON, default=list)

    # 대상
    target_role = Column(String(20), default="student")  # student / all
    is_active = Column(Boolean, default=True)

    # 📅 스케줄 설정 (다중 주차/요일 — JSON 배열)
    weeks = Column(JSON, default=list)   # [1,3,5] — 첫째/셋째/다섯째주
    days = Column(JSON, default=list)    # ["월","수"] — 월요일, 수요일
    sort_order = Column(Integer, default=0)   # 정렬 순서

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
