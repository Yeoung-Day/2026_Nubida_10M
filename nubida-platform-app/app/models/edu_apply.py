"""
교육 신청(Education Application) Models — 2026-09-21
(2026-09-21 개편: 게시판형 공고 + 강사 팝업 + 지역 분류)

본사가 **공고(게시글)** 를 올리면 방문자가 [신청] 버튼으로 접수하는 구조.

보안 원칙 (개인정보):
  - 이름·연락처 등 개인정보는 **본사(super_admin / admin) 전용**이다.
  - 학생 / 학부모 / 원장 / 에듀케어(branch_admin) 에게는 API 응답 자체에
    실명·연락처가 담기지 않는다 (UI 숨김이 아니라 서버 차단).
  - 소속 강사 신청의 PDF(강사카드)는 본사만 다운로드할 수 있다.

테이블:
  edu_programs                — 교육 공고 (본사가 작성하는 게시글)
  edu_applications            — 교육 신청 (공고에 대한 접수)
  edu_instructor_applications — 소속 강사 신청 (PDF 첨부, 지역 분류)
  edu_notify_logs             — 승인 안내 발송 이력 (본사 내부 기록용)
"""
from sqlalchemy import Column, String, Text, Integer, DateTime, Boolean
from sqlalchemy.sql import func

from app.core.database import Base
from app.models import PK


# ============================================================
# 공통 상태값
# ============================================================
# 신청 상태
# pending    : 접수
# reviewing  : 확인중
# approved   : 승인
# rejected   : 반려
APPLY_STATUSES = ("pending", "reviewing", "approved", "rejected")

# 공고 모집 상태
# open    : 모집중
# closed  : 마감
PROGRAM_STATUSES = ("open", "closed")


class EduProgram(Base):
    """교육 공고 — 본사가 작성하는 게시글.

    방문자는 이 공고를 보고 [신청] 버튼을 눌러 접수한다.
    타이틀·내용·모집기간 모두 본사가 관리한다.
    """

    __tablename__ = "edu_programs"

    id = PK()

    # ── 게시글 내용 (본사 작성) ──
    title = Column(String(200), nullable=False)       # 공고 제목
    category = Column(String(80))                     # 분류 (강사양성과정 / 코딩지도사 등, 자유)
    content = Column(Text)                            # 본문 (교육 내용)
    summary = Column(String(300))                     # 목록에 보이는 한 줄 요약

    # ── 모집 정보 ──
    status = Column(String(20), nullable=False, default="open", index=True)  # open/closed
    recruit_start = Column(String(20))                # 모집 시작일 (YYYY-MM-DD)
    recruit_end = Column(String(20))                  # 모집 마감일 (YYYY-MM-DD)
    capacity = Column(Integer, default=0)             # 정원 (0 = 제한 없음)
    location = Column(String(120))                    # 교육 장소
    fee = Column(String(80))                          # 교육비 (표시용 문자열)
    contact = Column(String(120))                     # 문의처 (표시용)

    # ── 게시판 운영 ──
    is_pinned = Column(Boolean, default=False)        # 상단 고정
    sort_order = Column(Integer, default=0)           # 정렬 (작을수록 위)
    is_visible = Column(Boolean, default=True)        # 공개 여부

    # ── 작성자 (본사) ──
    created_by = Column(Integer)
    created_by_name = Column(String(50))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EduApplication(Base):
    """교육 신청 — 공고에 대한 접수 (게시판형)"""

    __tablename__ = "edu_applications"

    id = PK()

    # ── 어떤 공고에 대한 신청인지 ──
    # (구버전 자유입력 데이터 호환을 위해 nullable)
    program_id = Column(Integer, index=True)
    title = Column(String(200), nullable=False)   # 공고 제목 스냅샷 (공고 삭제돼도 보존)

    # ── 신청자 정보 (개인정보 — 본사 전용) ──
    name = Column(String(50), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(120))
    region = Column(String(80))          # 지역
    organization = Column(String(120))   # 소속
    memo = Column(Text)                  # 비고

    # ── 처리 상태 ──
    status = Column(String(20), nullable=False, default="pending", index=True)
    admin_note = Column(Text)            # 본사 메모 (신청자에게 비노출)

    # ── 접수 경로 추적 ──
    ip_address = Column(String(64))
    user_agent = Column(String(300))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EduInstructorApplication(Base):
    """소속 강사 신청 — 일반 항목 + 생년월일/경력/자격증 + 강사카드 PDF"""

    __tablename__ = "edu_instructor_applications"

    id = PK()

    title = Column(String(200), nullable=False)

    # ── 기본 정보 (개인정보 — 본사 전용) ──
    name = Column(String(50), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(120))
    region = Column(String(80), index=True)   # 지역 — 본사 목록에서 지역별 분류
    organization = Column(String(120))
    memo = Column(Text)

    # ── 강사 전용 추가 항목 ──
    birth_date = Column(String(20))          # 생년월일 (YYYY-MM-DD)
    career = Column(Text)                    # 경력사항
    has_certificate = Column(String(10))     # 자격증 유무 (yes/no)
    certificate_detail = Column(Text)        # 자격증 종류·상세

    # ── 강사카드 PDF (본사 전용 다운로드) ──
    pdf_path = Column(String(300))           # 서버 저장 경로 (/uploads/edu_apply/...)
    pdf_name = Column(String(300))           # 원본 파일명

    status = Column(String(20), nullable=False, default="pending", index=True)
    admin_note = Column(Text)

    ip_address = Column(String(64))
    user_agent = Column(String(300))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EduNotifyLog(Base):
    """승인 안내 발송 이력 — 본사가 복사해서 직접 발송한 내용을 기록만 해둔다.

    외부 발송 연동 없음(오발송 위험 0). 본사 내부 확인용.
    """

    __tablename__ = "edu_notify_logs"

    id = PK()

    target_type = Column(String(20), nullable=False, index=True)  # application / instructor
    target_id = Column(Integer, nullable=False, index=True)

    # ── 수신자 (본사 전용 — 외부 노출 금지) ──
    recipient_name = Column(String(50))
    recipient_phone = Column(String(30))
    recipient_email = Column(String(120))

    channel = Column(String(20), default="sms")   # sms / email
    subject = Column(String(200))
    body = Column(Text)

    sent_by = Column(Integer)                     # 발송 처리한 관리자 ID
    sent_by_name = Column(String(50))
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "EduProgram",
    "EduApplication",
    "EduInstructorApplication",
    "EduNotifyLog",
    "APPLY_STATUSES",
    "PROGRAM_STATUSES",
]
