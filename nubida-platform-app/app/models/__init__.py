from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime, Float,
    Time, DECIMAL, ForeignKey, UniqueConstraint, JSON, Index, text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.portfolio_template import PortfolioTemplate
from app.models.activity import Activity


# ============================================================
# SQLite 호환 Primary Key
# ============================================================

def PK():
    """SQLite 호환 Primary Key — dev는 Integer, prod는 BigInteger"""
    from app.core.config import settings
    if "sqlite" in settings.DATABASE_URL:
        return Column(Integer, primary_key=True, autoincrement=True)
    return Column(Integer, primary_key=True, autoincrement=True)


def FK(column: str):
    """SQLite 호환 Foreign Key"""
    return Column(Integer, ForeignKey(column))


def FK_I(column: str, index=True, comment=None, nullable=True):
    """SQLite 호환 Foreign Key with index"""
    return Column(Integer, ForeignKey(column), index=index, comment=comment, nullable=nullable)


# ============================================================
# 사용자 및 인증
# ============================================================


class User(Base):
    __tablename__ = "users"

    id = PK()
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(50), nullable=False)
    phone = Column(String(20))
    role = Column(String(20), nullable=False, default="student")
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    director_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    registration_code = Column(String(7), unique=True, nullable=False, index=True, default="")
    is_active = Column(Boolean, default=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True, comment="승인한 사용자 ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    academy_type = Column(String(30), default="", comment="AI미술/AI로봇/다중")
    region = Column(String(50), default="", comment="지역")
    notification_settings = Column(JSON, default={})
    first_login_at = Column(DateTime(timezone=True), nullable=True, comment="최초 로그인 시각")
    onboarding_done = Column(Boolean, default=False, comment="첫 접속 가이드 투어 완료 여부")
    nubida_machine_locked = Column(Boolean, default=False, comment="누비다머신 사용 잠금 (원장 계정에 설정 시 소속 학생 전체 차단)")
    login_version = Column(Integer, default=1, nullable=False, server_default="1", comment="이중로그인 방지 — 로그인마다 증가, 이전 토큰 무효화")
    # ── 로그인 시도 제한 (rate limit, 2026-09-14) ──
    # 연속 실패가 임계치를 넘으면 locked_until 까지 로그인 차단.
    # 성공 시 두 값 모두 초기화된다.
    failed_login_attempts = Column(Integer, default=0, nullable=False, server_default="0",
                                   comment="연속 로그인 실패 횟수 (rate limit)")
    locked_until = Column(DateTime, nullable=True, default=None,
                          comment="로그인 잠금 해제 시각 (NULL=미잠금)")
    # ── 관리자 2단계 인증 (TOTP, 2026-09-14) ──
    # super_admin/admin/hq_admin 계정만 대상. totp_enabled=1 이면 로그인 시
    # 비밀번호 통과 후 추가로 6자리 코드를 요구한다.
    totp_secret = Column(String(64), nullable=True, default=None,
                         comment="TOTP 시크릿 (base32)")
    totp_enabled = Column(Boolean, nullable=False, default=False, server_default="0",
                          comment="2단계 인증 사용 여부")
    totp_recovery = Column(Text, nullable=True, default=None,
                           comment="복구코드 해시 JSON 배열")
    totp_confirmed_at = Column(DateTime, nullable=True, default=None,
                               comment="2단계 인증 최초 등록 시각")
    # ── 탈퇴 구분 (2026-10-02) ──
    # is_active=False 는 "승인 대기"와 "탈퇴"가 공유하던 값이라
    # 탈퇴생이 원장의 회원 승인 목록에 섞여 나타나는 버그가 있었다.
    # 탈퇴 시 withdrawn_at 을 기록하여 승인 대기(IS NULL)와 구분한다.
    withdrawn_at = Column(DateTime(timezone=True), nullable=True, default=None,
                          comment="탈퇴 처리 시각 (NULL=탈퇴 아님)")


class AccessLog(Base):
    __tablename__ = "access_logs"

    id = PK()
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(100), nullable=False)
    ip_address = Column(String(45))
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 학생/원장 문의(Q&A) — api/v1/inquiries.py가 raw SQL로 사용
# (운영 DB에만 존재하던 테이블 — 신규 DB create_all 반영용 모델 추가)
# ============================================================

class Inquiry(Base):
    __tablename__ = "inquiries"

    id = PK()
    director_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    director_name = Column(String(50), default="")
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    branch_name = Column(String(100), default="")
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="pending")  # pending / answered
    answer = Column(Text, default="")
    answered_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    answered_by_name = Column(String(50), default="")
    answered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    student_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    student_name = Column(String(50), default="")
    image_path = Column(String(500), nullable=True)


# ============================================================
# 승인 전 사용자 (자가등록 → 본사 승인 대기) — auth.py/pending_db.py 사용
# ※ pending_db.py는 MySQL 전용 유틸 — SQLite 모드에서는 사용되지 않음
# ============================================================

class PendingApproval(Base):
    __tablename__ = "pending_approvals"

    id = PK()
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(50), nullable=False)
    phone = Column(String(20))
    role = Column(String(20), nullable=False, default="student")
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    director_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    registration_code = Column(String(7), default="", index=True)
    academy_type = Column(String(30), default="")
    region = Column(String(50), default="")
    # 신규 학원/에듀케어명 (가입 시 입력 — 승인 시 Branch/Academy 자동생성 name 우선 사용, 9/7)
    branch_name = Column(String(100), default="")
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="pending")  # pending / approved / rejected


# ============================================================
# 누비다 AI — 채팅 어시스턴트 (확정설계안 v2)
# ai_messages(대화) / ai_faq_knowledge(RAG 지식) / ai_feedback(해결·부족)
# ============================================================

class AiMessage(Base):
    __tablename__ = "ai_messages"

    id = PK()
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)
    role = Column(String(10), nullable=False)            # user / assistant
    content = Column(Text, nullable=False)
    model = Column(String(50), default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    attempt = Column(Integer, default=1)                 # 이 답변의 힌트 단계 (1~4)
    faq_id = Column(Integer, nullable=True, index=True)  # 참조한 RAG 지식 (피드백 연결용)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiFaqKnowledge(Base):
    __tablename__ = "ai_faq_knowledge"

    id = PK()
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)              # JSON float[] (임베딩 캐시)
    source = Column(String(20), default="ai")            # ai / inquiry / manual
    source_id = Column(Integer, nullable=True)
    quality_score = Column(Float, default=0.0)
    up_count = Column(Integer, default=0)                # ✅ 해결(도움 됨)
    down_count = Column(Integer, default=0)              # ⚠️ 부족
    status = Column(String(20), default="pending")       # pending / published / rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiFeedback(Base):
    __tablename__ = "ai_feedback"

    id = PK()
    message_id = Column(Integer, ForeignKey("ai_messages.id"), nullable=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    helpful = Column(Integer, default=0)                 # 1 해결 / -1 부족(재시도)
    attempt = Column(Integer, default=1)                 # 몇 번째 시도에서 해결했는지
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 지사
# ============================================================

class Branch(Base):
    __tablename__ = "branches"

    id = PK()
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    address = Column(Text)
    phone = Column(String(20))
    email = Column(String(100))
    status = Column(String(20), default="active")
    contract_start = Column(Date)
    contract_end = Column(Date)
    license_key = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_approved = Column(Boolean, default=True)


class BranchSetting(Base):
    __tablename__ = "branch_settings"

    id = PK()
    branch_id = Column(Integer, ForeignKey("branches.id"), unique=True)
    max_students = Column(Integer, default=100)
    operating_hours = Column(JSON)
    payment_config = Column(JSON)
    notification_config = Column(JSON)


# ============================================================
# 학원 (에듀케어에 소속된 실제 교육 기관)
# ============================================================


class Academy(Base):
    __tablename__ = "academies"

    id = PK()
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    address = Column(Text)
    phone = Column(String(20))
    status = Column(String(20), default="active")
    director_name = Column(String(100))
    student_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AcademyCourse(Base):
    __tablename__ = "academy_courses"

    id = PK()
    academy_id = Column(Integer, ForeignKey("academies.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("academy_id", "course_id", name="uq_academy_course"),)


# ============================================================
# 학원별 강좌 카테고리 관리
# ============================================================


class BranchCategory(Base):
    """학원(Branch)별 강좌 카테고리 관리 — display_name, color 별도 지정 가능"""
    __tablename__ = "branch_categories"

    id = PK()
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    category_key = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=True, comment="학원에서 보여줄 카테고리명 (없으면 Category.name 사용)")
    color = Column(String(7), nullable=True, comment="표시 색상 hex")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("branch_id", "category_key", name="uq_branch_category"),
    )


class DirectorCategory(Base):
    """원장(Director)별 강좌 카테고리 권한"""
    __tablename__ = "director_categories"

    id = PK()
    director_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    category_key = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=True)
    color = Column(String(7), nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("director_id", "category_key", name="uq_director_category"),
    )


# ============================================================
# 강좌 및 수업
# ============================================================

class Course(Base):
    __tablename__ = "courses"

    id = PK()
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    subject = Column(String(50))
    category = Column(String(50), default="ai_art", index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    price = Column(DECIMAL(12, 2))
    max_capacity = Column(Integer, default=30)
    instructor = Column(String(50))
    status = Column(String(20), default="active")
    thumbnail = Column(String(500), nullable=True, comment="강좌 대표 이미지 URL")
    sort_order = Column(Integer, default=0)
    content_blocks = Column(JSON, nullable=True, comment="강좌 콘텐츠 블록 JSON 배열")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    folders = relationship("CourseFolder", secondary="course_folder_items", backref="courses", lazy="selectin")


class ClassSchedule(Base):
    __tablename__ = "class_schedules"

    id = PK()
    course_id = FK_I("courses.id")
    teacher_id = FK("users.id")
    branch_id = Column(Integer, default=0, index=True)
    title = Column(String(200), default="")
    description = Column(String(500), default="")
    day_of_week = Column(Integer)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    room = Column(String(50))
    date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = PK()
    student_id = FK_I("users.id")
    course_id = FK_I("courses.id")
    enrolled_date = Column(Date, server_default=text("(CURRENT_DATE)"))
    status = Column(String(20), default="active")
    payment_status = Column(String(20), default="pending")
    __table_args__ = (UniqueConstraint("student_id", "course_id"),)


# ============================================================
# 성적 및 학습
# ============================================================

class Exam(Base):
    __tablename__ = "exams"

    id = PK()
    course_id = FK_I("courses.id")
    title = Column(String(100), nullable=False)
    exam_date = Column(Date)
    max_score = Column(DECIMAL(5, 2))
    exam_type = Column(String(20))


class Score(Base):
    __tablename__ = "scores"

    id = PK()
    student_id = FK_I("users.id")
    exam_id = FK_I("exams.id")
    score = Column(DECIMAL(5, 2))
    grade = Column(String(2))
    feedback = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Attendance(Base):
    __tablename__ = "attendance"

    id = PK()
    student_id = FK_I("users.id")
    schedule_id = FK("class_schedules.id")
    date = Column(Date, nullable=False)
    status = Column(String(20))
    remark = Column(Text, default="")
    __table_args__ = (UniqueConstraint("student_id", "schedule_id", "date"),)


# ============================================================
# 결제 및 매출
# ============================================================

class Payment(Base):
    __tablename__ = "payments"

    id = PK()
    parent_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True, comment="결제한 학부모 ID (학부모 결제 시)")
    student_id = FK_I("users.id")
    course_id = FK("courses.id")
    branch_id = FK_I("branches.id")
    amount = Column(DECIMAL(12, 2), nullable=False)
    method = Column(String(20))
    status = Column(String(20), default="pending")
    paid_at = Column(DateTime(timezone=True))
    receipt_number = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TaxInvoice(Base):
    __tablename__ = "tax_invoices"

    id = PK()
    payment_id = FK("payments.id")
    invoice_number = Column(String(50), unique=True, nullable=False)
    issue_date = Column(Date, server_default=text("(CURRENT_DATE)"))
    amount = Column(DECIMAL(12, 2))
    status = Column(String(20), default="issued")


# ============================================================
# 영상
# ============================================================

class Video(Base):
    __tablename__ = "videos"

    id = PK()
    course_id = FK_I("courses.id")
    title = Column(String(200), nullable=False)
    subject = Column(String(100))
    description = Column(Text)
    url = Column(String(500), nullable=False)
    video_type = Column(String(20), nullable=False, default="youtube")  # youtube / vimeo / upload
    thumbnail_url = Column(String(500))
    duration_seconds = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 포트폴리오
# ============================================================

class Portfolio(Base):
    __tablename__ = "portfolios"

    id = PK()
    student_id = FK_I("users.id")
    title = Column(String(200), nullable=False)
    description = Column(Text)
    content = Column(Text)  # 보고서 본문 (HTML/rich text)
    content_url = Column(String(500))
    file_type = Column(String(20))  # image / pdf / link / video
    thumbnail_url = Column(String(500))
    image_urls = Column(Text)  # JSON 배열: 첨부 이미지 URL 목록
    subject = Column(String(100))
    tags = Column(Text)
    is_public = Column(Boolean, default=True)
    status = Column(String(20), default="draft")  # draft / published

    # 📎 강좌 연결 (학생이 속한 강좌 + 템플릿 ID)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    template_id = Column(Integer, ForeignKey("portfolio_templates.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 원격 수업
# ============================================================

class RemoteClass(Base):
    __tablename__ = "remote_classes"

    id = PK()
    title = Column(String(200), nullable=False)
    description = Column(Text)
    course_id = FK_I("courses.id")
    teacher_id = FK_I("users.id")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, default=60)
    status = Column(String(20), default="scheduled")
    room_url = Column(String(500))
    max_participants = Column(Integer, default=30)
    recording_url = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    course = relationship("Course", backref="remote_classes", lazy="selectin")


class RemoteAttendance(Base):
    __tablename__ = "remote_attendance"

    id = PK()
    class_id = FK_I("remote_classes.id")
    student_id = FK_I("users.id")
    join_at = Column(DateTime(timezone=True), nullable=False)
    leave_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="attended")


# ============================================================
# 알림
# ============================================================

class Notification(Base):
    __tablename__ = "notifications"

    id = PK()
    user_id = FK_I("users.id")
    title = Column(String(100), nullable=False)
    content = Column(Text)
    notif_type = Column(String(30))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 카테고리 관리
# ============================================================


class Category(Base):
    __tablename__ = "categories"

    id = PK()
    key = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0)
    color = Column(String(7))  # hex color e.g. '#2563EB'
    bg_color = Column(String(7))  # bg hex color
    is_active = Column(Boolean, default=True)
    is_public = Column(Boolean, default=True, comment="본사가 전체 공개(원장/에듀케어 매출·인원 사용 허용) 여부")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 공지사항 (본사 → 전체 공지)
# ============================================================

class Notice(Base):
    __tablename__ = "notices"

    id = PK()
    title = Column(String(200), nullable=False)
    content = Column(Text)
    author = Column(String(50), nullable=False, default="관리자")
    status = Column(String(20), default="published")
    is_pinned = Column(Boolean, default=False)
    view_count = Column(Integer, default=0)
    is_popup = Column(Boolean, default=False)
    popup_start = Column(String(32), nullable=True, default="")
    popup_end = Column(String(32), nullable=True, default="")
    popup_targets = Column(Text, nullable=True)
    publish_targets = Column(Text, nullable=True, comment="발행 대상 — main,student,parent,director,educare (콤마구분 복수선택)")
    images = Column(Text, nullable=True, comment="첨부 이미지 경로 JSON 배열")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ============================================================
# 강좌 학습 자료
# ============================================================

class CourseMaterial(Base):
    __tablename__ = "course_materials"

    id = PK()
    course_id = FK_I("courses.id")
    title = Column(String(200), nullable=False)
    description = Column(Text)
    material_type = Column(String(30), nullable=False, default="document")
    # material_type: document(pdf/ppt/hwp), video, image, link, embed, lecture
    file_url = Column(String(500))
    embed_url = Column(String(500))  # YouTube embed URL
    file_size = Column(Integer, default=0)
    duration_minutes = Column(Integer, default=0)  # 영상 길이
    content_html = Column(Text)  # 강의 콘텐츠 (PPT 슬라이드 포함 HTML, 코드 블록) — 하위호환
    content_blocks = Column(JSON, nullable=True, comment="블록 배열: [{type:'slide'|'code'|'text'|'image', data: {...}}]")
    chapter = Column(String(100), nullable=True, default="", comment="챕터명")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ============================================================
# 학습 진행률
# ============================================================

class LearningProgress(Base):
    __tablename__ = "learning_progress"

    id = PK()
    student_id = FK_I("users.id")
    material_id = FK_I("course_materials.id")
    course_id = FK_I("courses.id")
    block_index = Column(Integer, nullable=True)  # 블록 인덱스 (블록별 진행 상태용)
    is_completed = Column(Boolean, default=False)
    progress_percent = Column(Integer, default=0)  # 0-100
    last_viewed_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("student_id", "material_id", "block_index", name="uq_student_material_block"),
    )


from app.models.portfolio_template import PortfolioTemplate


# Model registry for init_db
all_models = [
    User, AccessLog, Inquiry, PendingApproval, AiMessage, AiFaqKnowledge, AiFeedback, Branch, BranchSetting, BranchCategory, Course, ClassSchedule,
    Enrollment, Exam, Score, Attendance, Payment, TaxInvoice,
    Notification, Video, Portfolio, Notice, CourseMaterial, LearningProgress, AcademyCourse,
    RemoteClass, RemoteAttendance, Category, PortfolioTemplate, Activity,
]

# ============================================================
# 학급 관리 (SchoolClass, ClassCourse, ClassStudent)
# ============================================================


class SchoolClass(Base):
    __tablename__ = "school_classes"

    id = PK()
    name = Column(String(100), nullable=False)
    grade = Column(String(50))
    branch_id = FK_I("branches.id")
    director_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="active")
    student_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClassCourse(Base):
    __tablename__ = "class_courses"

    id = PK()
    class_id = Column(Integer, ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "course_id"),)


class ClassStudent(Base):
    __tablename__ = "class_students"

    id = PK()
    class_id = Column(Integer, ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    enrolled_at = Column(Date, server_default=text("(CURRENT_DATE)"))
    status = Column(String(20), default="active")
    __table_args__ = (UniqueConstraint("class_id", "student_id"),)


class ClassMaterial(Base):
    """학급-학습자료(페이지) 직접 연결"""
    __tablename__ = "class_materials"

    id = PK()
    class_id = Column(Integer, ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("course_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "material_id"),)


# ============================================================
# 메이커 코딩 교육 시스템 (초등 4~6학년 아두이노)
# ============================================================


class MakerCourse(Base):
    """월별 메이커 강좌 (스마트팜 / 자율주행차 / 스마트휴지통)"""
    __tablename__ = "maker_courses"

    id = PK()
    title = Column(String(100), nullable=False)
    month = Column(String(7), nullable=False, index=True)  # "2026-05"
    description = Column(Text)
    thumbnail = Column(String(500))
    kit_name = Column(String(100))  # MDF 키트 이름
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Lesson(Base):
    """차시 — 강좌 내 개별 수업"""
    __tablename__ = "lessons"

    id = PK()
    maker_course_id = Column(Integer, ForeignKey("maker_courses.id"), nullable=False, index=True)
    order_num = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content_type = Column(String(20), default="ppt")  # ppt / video
    ppt_url = Column(String(500))
    video_url = Column(String(500))
    duration_minutes = Column(Integer, default=10)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Studio(Base):
    """공부방 (원장 운영)"""
    __tablename__ = "studios"

    id = PK()
    name = Column(String(100), nullable=False)
    admin_name = Column(String(50))
    admin_phone = Column(String(20))
    password_hash = Column(String(255))
    max_students = Column(Integer, default=10)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MakerStudent(Base):
    """공부방 소속 학생"""
    __tablename__ = "maker_students"

    id = PK()
    studio_id = Column(Integer, ForeignKey("studios.id"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    login_id = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    grade = Column(String(20))  # 초4 / 초5 / 초6
    start_date = Column(Date, server_default=text("(CURRENT_DATE)"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MakerEnrollment(Base):
    """수강신청"""
    __tablename__ = "maker_enrollments"

    id = PK()
    student_id = Column(Integer, ForeignKey("maker_students.id"), nullable=False, index=True)
    maker_course_id = Column(Integer, ForeignKey("maker_courses.id"), nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="active")
    __table_args__ = (UniqueConstraint("student_id", "maker_course_id"),)


class LessonProgress(Base):
    """차시별 진도"""
    __tablename__ = "lesson_progress"

    id = PK()
    enrollment_id = Column(Integer, ForeignKey("maker_enrollments.id"), nullable=False, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("enrollment_id", "lesson_id"),)


class Coding(Base):
    """학생 코드 저장"""
    __tablename__ = "codings"

    id = PK()
    enrollment_id = Column(Integer, ForeignKey("maker_enrollments.id"), nullable=False, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    code_content = Column(Text)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())


class AiCoding(Base):
    """AI 생성 코드"""
    __tablename__ = "ai_codings"

    id = PK()
    enrollment_id = Column(Integer, ForeignKey("maker_enrollments.id"), nullable=False, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    code_content = Column(Text)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())


class CodingComparison(Base):
    """코드 비교 결과"""
    __tablename__ = "coding_comparisons"

    id = PK()
    enrollment_id = Column(Integer, ForeignKey("maker_enrollments.id"), nullable=False, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    diff_result = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MakerPortfolio(Base):
    """포트폴리오 (1차/2차)"""
    __tablename__ = "maker_portfolios"

    id = PK()
    enrollment_id = Column(Integer, ForeignKey("maker_enrollments.id"), nullable=False, index=True)
    portfolio_type = Column(String(10), nullable=False)  # "1차" / "2차"
    files = Column(JSON)
    description = Column(Text)
    content = Column(Text)  # 보고서 본문
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    confirmed_by = Column(Integer, ForeignKey("studios.id"))
    confirmed_at = Column(DateTime(timezone=True))


# ============================================================
# 개인 일정 (StudentSchedule) — 학생이 직접 등록
# ============================================================


class StudentSchedule(Base):
    """학생 개인 일정 — 학생이 직접 등록한 일정"""
    __tablename__ = "student_schedules"

    id = PK()
    student_id = FK_I("users.id")
    title = Column(String(200), nullable=False)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    memo = Column(Text, default="")
    color = Column(String(20), default="#0891B2")  # 틸 기본색
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 강좌 폴더 — 2단계 depth (부모-자식)
# ============================================================

class CourseFolder(Base):
    """강좌 폴더 — 최대 2단계 depth"""
    __tablename__ = "course_folders"

    id = PK()
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("course_folders.id"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    category = Column(String(50), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    children = relationship("CourseFolder", backref="parent", remote_side=[id], lazy="selectin")


class CourseFolderItem(Base):
    """강좌-폴더 N:M 연결"""
    __tablename__ = "course_folder_items"

    id = PK()
    folder_id = Column(Integer, ForeignKey("course_folders.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("folder_id", "course_id"),)


class BranchCourseAllocation(Base):
    """학원-강좌 N:M 할당 — 하나의 강좌를 여러 학원에 할당 가능"""
    __tablename__ = "branch_course_allocations"

    id = PK()
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, comment="할당 활성화 ON/OFF (할당 유지한 채 일시 중단)")
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("branch_id", "course_id", name="uq_branch_course_allocation"),)


# ============================================================
# 사용자 토큰 및 멤버십 링크
# ============================================================

class ReportHistory(Base):
    """보고서 생성 이력"""
    __tablename__ = "report_history"

    id = PK()
    director_id = FK_I("users.id")
    title = Column(String(200), nullable=False)
    report_type = Column(String(50), nullable=False)  # "학생 성적 보고서", "출결 현황 보고서", "수업 통계 보고서"
    date_range_start = Column(Date, nullable=True)
    date_range_end = Column(Date, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserToken(Base):
    """사용자 토큰 — 등록/연결용 (NBD-XXXXXXXX)"""
    __tablename__ = "user_tokens"

    id = PK()
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    token = Column(String(20), unique=True, nullable=False, index=True)
    purpose = Column(String(20), nullable=False)  # 'registration', 'linking'
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MembershipLink(Base):
    """멤버십 링크 — 부모-자식, 원장-학생 등 관계"""
    __tablename__ = "membership_links"

    id = PK()
    parent_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    child_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    relationship = Column(String(20), nullable=False)  # 'parent_child', 'director_student', 'teacher_student', 'branch_manager_director'
    status = Column(String(20), nullable=False, default="pending")  # 'active', 'pending', 'rejected'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", "relationship", name="uq_parent_child_relationship"),
    )


class DirectorReport(Base):
    """원장 월간 운영 보고서 — 대표님 제출용 양식"""
    __tablename__ = "director_reports"

    id = PK()
    director_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="draft")  # 'draft', 'submitted'
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    # 기본 정보
    branch_name = Column(String(200), nullable=False, default="")
    director_name = Column(String(100), nullable=False, default="")
    contact = Column(String(100), nullable=False, default="")

    # 수강생 현황
    total_students = Column(Integer, default=0)
    new_registrations = Column(Integer, default=0)
    withdrawals = Column(Integer, default=0)
    retention_rate = Column(Integer, default=0)  # 퍼센트 (예: 95)

    # 이번 달 목표
    target_new_students = Column(Integer, default=0)
    target_monthly_revenue = Column(Integer, default=0)
    target_other = Column(Text, default="")

    # 이슈 및 건의사항
    issue_facility_content = Column(Text, default="")
    issue_facility_request = Column(Text, default="")
    issue_education_content = Column(Text, default="")
    issue_education_request = Column(Text, default="")
    issue_admin_content = Column(Text, default="")
    issue_admin_request = Column(Text, default="")
    issue_other_content = Column(Text, default="")
    issue_other_request = Column(Text, default="")

    # 전월 실적
    result_new_students = Column(Integer, default=0)
    result_new_students_rate = Column(Integer, default=0)  # 목표 달성률 %
    result_monthly_revenue = Column(Integer, default=0)
    result_monthly_revenue_rate = Column(Integer, default=0)  # 목표 달성률 %
    result_retention_rate = Column(Integer, default=0)  # 실제 유지율 %
    result_retention_rate_achieved = Column(Integer, default=0)  # 목표 달성률 %

    # 특이사항
    notes = Column(Text, default="")

    # 서명
    confirmed_date = Column(String(20), default="")
    is_agreed = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BranchReport(Base):
    """지사 월간 운영 보고서 — 원장 보고서 참조 + 지사 자체 보고"""
    __tablename__ = "branch_reports"

    id = PK()
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    director_report_id = Column(Integer, ForeignKey("director_reports.id"), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    # 기본 정보
    branch_name = Column(String(200), nullable=False, default="")
    manager_name = Column(String(100), nullable=False, default="")
    contact = Column(String(100), nullable=False, default="")

    # 수강생 현황
    total_students = Column(Integer, default=0)
    new_registrations = Column(Integer, default=0)
    withdrawals = Column(Integer, default=0)
    retention_rate = Column(Integer, default=0)

    # 목표
    target_new_students = Column(Integer, default=0)
    target_monthly_revenue = Column(Integer, default=0)
    target_other = Column(Text, default="")

    # 이슈
    issue_facility_content = Column(Text, default="")
    issue_facility_request = Column(Text, default="")
    issue_education_content = Column(Text, default="")
    issue_education_request = Column(Text, default="")
    issue_admin_content = Column(Text, default="")
    issue_admin_request = Column(Text, default="")
    issue_other_content = Column(Text, default="")
    issue_other_request = Column(Text, default="")

    # 실적
    result_new_students = Column(Integer, default=0)
    result_new_students_rate = Column(Integer, default=0)
    result_monthly_revenue = Column(Integer, default=0)
    result_monthly_revenue_rate = Column(Integer, default=0)
    result_retention_rate = Column(Integer, default=0)
    result_retention_rate_achieved = Column(Integer, default=0)

    # 특이사항
    notes = Column(Text, default="")

    # 서명
    confirmed_date = Column(String(20), default="")
    is_agreed = Column(Boolean, default=False)

    # 원장 보고서 전달 여부
    director_report_received = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# Chat Models
# ============================================================

class ChatRoom(Base):
    """채팅방"""
    __tablename__ = "chat_rooms"
    id = PK()
    room_type = Column(String(20), default="direct")  # direct | group | announcement
    name = Column(String(200), default="")
    created_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ChatParticipant(Base):
    """채팅방 참여자"""
    __tablename__ = "chat_participants"
    id = PK()
    room_id = FK_I("chat_rooms.id")
    user_id = FK_I("users.id")
    last_read_id = Column(Integer, default=0)
    role = Column(String(20), default="member")  # member | admin
    joined_at = Column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """채팅 메시지"""
    __tablename__ = "chat_messages"
    id = PK()
    room_id = FK_I("chat_rooms.id")
    sender_id = FK_I("users.id")
    message_type = Column(String(20), default="text")  # text | file | system
    content = Column(Text, default="")
    file_url = Column(String(500), default="")
    file_name = Column(String(200), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())



# ============================================================
# 교육 프로그램 관리
# ============================================================

class EducationProgram(Base):
    """교육 프로그램"""
    __tablename__ = "education_programs"
    id = PK()
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50), default="maker_coding")
    status = Column(String(20), default="active")
    created_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ProgramChapter(Base):
    """프로그램 차시"""
    __tablename__ = "program_chapters"
    id = PK()
    program_id = Column(Integer, ForeignKey("education_programs.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    sort_order = Column(Integer, default=0)
    description = Column(Text)
    ppt_file = Column(String(500))
    ppt_url = Column(String(500))
    video_url = Column(String(500))
    video_title = Column(String(200))
    duration_minutes = Column(Integer, default=0)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ProgramAssignment(Base):
    """프로그램 할당"""
    __tablename__ = "program_assignments"
    id = PK()
    program_id = Column(Integer, ForeignKey("education_programs.id"), nullable=False, index=True)
    assignee_type = Column(String(20), nullable=False)
    assignee_id = Column(Integer, nullable=False)
    assigned_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("program_id", "assignee_type", "assignee_id", name="uq_program_assign"),)

# ============================================================
# 원장 계약 관리
# ============================================================

class DirectorContract(Base):
    """원장 계약 정보 (직영/프랜차이즈)"""
    __tablename__ = "director_contracts"
    id = PK()
    director_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    contract_type = Column(String(20), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    contract_start = Column(Date)
    contract_end = Column(Date)
    monthly_fee = Column(DECIMAL(12,2), default=0)
    royalty_rate = Column(DECIMAL(5,2), default=0)
    status = Column(String(20), default="active")
    memo = Column(Text)
    created_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())



# ============================================================
# 아두이노 코드 저장소
# ============================================================

class ArduinoCode(Base):
    """아두이노 웹 코딩 에디터 — 작성한 코드 저장"""
    __tablename__ = "arduino_codes"

    id = PK()
    course_id = Column(Integer, ForeignKey("courses.id"), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    title = Column(String(200), nullable=False, default="새 스케치")
    code = Column(Text, default="")
    description = Column(Text, default="")
    tags = Column(String(500), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 탈퇴 학생 히스토리 (본사 전용)
# ============================================================

class WithdrawnStudent(Base):
    """탈퇴/수업종료 학생 히스토리 — 본사만 확인 가능"""
    __tablename__ = "withdrawn_students"

    id = PK()
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    student_name = Column(String(50), nullable=False)
    student_username = Column(String(50), nullable=False)
    student_email = Column(String(100))
    course_name = Column(String(100))
    branch_name = Column(String(100))
    director_name = Column(String(50))
    end_date = Column(Date, server_default=text("(CURRENT_DATE)"))
    reason = Column(String(500), default="")
    withdrawn_by = FK_I("users.id", comment="탈퇴 처리한 사용자 ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 원장 수익금 (매출 기록)
# ============================================================

class Revenue(Base):
    """원장별 매출 기록"""
    __tablename__ = "revenues"

    id = PK()
    branch_id = FK_I("branches.id")
    director_id = FK_I("users.id")
    student_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    course_name = Column(String(200), default="")
    amount = Column(DECIMAL(14, 2), default=0)
    method = Column(String(50), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 원장 수익금 결제 승인 (본사 <-> 원장)
# ============================================================

class RevenueApproval(Base):
    """원장 수익금 결제 요청 및 본사 승인 처리"""
    __tablename__ = "revenue_approvals"

    id = PK()
    director_id = FK_I("users.id", comment="원장 ID")
    branch_id = FK_I("branches.id")
    period_start = Column(Date, nullable=False, comment="정산 시작일")
    period_end = Column(Date, nullable=False, comment="정산 종료일")
    total_amount = Column(DECIMAL(14, 2), default=0, comment="총 수익금")
    hq_account_number = Column(String(100), default="", comment="본사 계좌번호")
    status = Column(String(20), default="pending", comment="pending/approved/rejected/paid")
    director_note = Column(Text, default="", comment="원장 메모")
    approved_at = Column(DateTime(timezone=True), nullable=True, comment="본사 승인일")
    paid_at = Column(DateTime(timezone=True), nullable=True, comment="지급 완료일")
    approved_by = FK_I("users.id", nullable=True, comment="승인한 본사 관리자 ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# 월별 수강료 (교육비) 납부 관리
# ============================================================

class TuitionPayment(Base):
    """원장 매출관리 — 월별 학생 교육비 납부 기록

    course_type: ai_art(AI아트, 98,000원) / ai_robot(AI로봇, 198,000원)
    """
    __tablename__ = "tuition_payments"

    id = PK()
    director_id = FK_I("users.id", comment="원장(소유) user id")
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    student_id = FK_I("users.id", comment="학생 user id")
    period_ym = Column(String(7), nullable=False, comment="YYYY-MM 정산월")
    course_type = Column(String(20), nullable=False, default="ai_art",
                         comment="ai_art=AI아트 98000 / ai_robot=AI로봇 198000")
    amount = Column(DECIMAL(12, 2), default=0, comment="해당월 교육비")
    paid = Column(Boolean, default=False, comment="납부 여부")
    paid_at = Column(DateTime(timezone=True), nullable=True, comment="납부 체크 시각")
    memo = Column(String(255), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("director_id", "student_id", "period_ym"),)


# ============================================================
# 전역 설정 (key-value) — 본사 입금 계좌 등
# ============================================================


class AppSetting(Base):
    """전역 설정 (key-value) — 본사 입금 계좌 등"""
    __tablename__ = "app_settings"

    id = PK()
    key = Column(String(50), unique=True, index=True)
    value = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================================
# Web Push 구독 정보
# ============================================================

class PushSubscription(Base):
    """PWA + 네이티브(FCM/APNs) Push Notification 구독 정보

    - 웹 브라우저: endpoint/p256dh_key/auth_key (VAPID)
    - 네이티브 앱: device_token/platform/device_id (FCM/APNs)
    """
    __tablename__ = "push_subscriptions"

    id = PK()
    user_id = FK_I("users.id")
    # ── 네이티브 앱 (FCM/APNs) ──
    device_token = Column(String(500), nullable=True, index=True)  # FCM/APNs 토큰
    platform = Column(String(20), nullable=True)                   # android | ios | web
    device_id = Column(String(200), nullable=True)                 # 기기 식별자
    app_version = Column(String(50), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # ── 웹 푸시 (VAPID) — 네이티브 전용 행에서는 NULL ──
    endpoint = Column(String(500), nullable=True)
    p256dh_key = Column(String(200), nullable=True)
    auth_key = Column(String(100), nullable=True)
    user_agent = Column(String(200), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "endpoint", name="uq_user_endpoint"),)


# ============================================================
# 포인트 / 기프티콘 시스템
# ============================================================


class CoursePoint(Base):
    """과정별/포트폴리오별 포인트 설정 (본사 설정)"""
    __tablename__ = "course_points"

    id = PK()
    target_type = Column(String(20), nullable=False, comment="'course': 교육과정, 'portfolio': 포트폴리오")
    target_id = Column(Integer, nullable=True, comment="course_id / maker_course_id / NULL(기본값)")
    points = Column(Integer, nullable=False, default=0, comment="지급 포인트")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("target_type", "target_id", name="uq_course_point_target"),)


class PointTransaction(Base):
    """포인트 거래 내역"""
    __tablename__ = "point_transactions"

    id = PK()
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    points = Column(Integer, nullable=False, comment="+획득 / -사용")
    transaction_type = Column(String(30), nullable=False, comment="course_complete / portfolio_approve / gifticon_exchange / admin_adjust")
    reference_id = Column(Integer, nullable=True, comment="연관 ID (enrollment_id / portfolio_id / gifticon_request_id)")
    description = Column(String(200), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationship
    user = relationship("User", backref="point_transactions", lazy="selectin")


class GifticonSetting(Base):
    """기프티콘 상품 설정 (본사)"""
    __tablename__ = "gifticon_settings"

    id = PK()
    name = Column(String(100), nullable=False, comment="상품명 (e.g. 치킨 기프티콘)")
    gifticon_type = Column(String(50), nullable=False, comment="종류 (문화상품권/치킨/커피/편의점)")
    value = Column(Integer, default=0, comment="금액 (원)")
    points_required = Column(Integer, nullable=False, default=0, comment="필요 포인트")
    thumbnail = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GifticonRequest(Base):
    """기프티콘 신청"""
    __tablename__ = "gifticon_requests"

    id = PK()
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    gifticon_setting_id = Column(Integer, ForeignKey("gifticon_settings.id"), nullable=False)
    points_used = Column(Integer, nullable=False, comment="사용된 포인트")
    status = Column(String(20), nullable=False, default="pending", comment="pending / approved / rejected / completed")
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="처리 관리자")
    admin_note = Column(String(500), default="")
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # relationships
    user = relationship("User", backref="gifticon_requests", lazy="selectin", foreign_keys=[user_id])
    admin = relationship("User", backref="processed_gifticon_requests", lazy="selectin", foreign_keys=[admin_id])
    gifticon_setting = relationship("GifticonSetting", backref="requests", lazy="selectin")


# Extended model registry
all_models.extend([
    MakerCourse, Lesson, Studio, MakerStudent, MakerEnrollment,
    LessonProgress, Coding, AiCoding, CodingComparison, MakerPortfolio,
    CourseFolder, CourseFolderItem,
    UserToken, MembershipLink,
    SchoolClass, ClassCourse, ClassStudent, ClassMaterial,
    StudentSchedule,
    ReportHistory,
    DirectorReport,
    BranchReport,
    ChatRoom, ChatParticipant, ChatMessage,
    ArduinoCode,
    EducationProgram, ProgramChapter, ProgramAssignment,
    DirectorContract,
    PushSubscription,
    WithdrawnStudent,
    Revenue,
    RevenueApproval,
    # ============================================================
    # 포인트 / 기프티콘 시스템
    # ============================================================
    CoursePoint,
    PointTransaction,
    GifticonSetting,
    GifticonRequest,
    PortfolioTemplate,
    # 전역 설정 (본사 계좌 등)
    AppSetting,
])


# ============================================================
# 하단에 추가 import가 필요한 모델들
# ============================================================





# ============================================================
# 누비다머신 — 머신러닝 이미지 학습 시스템
# ============================================================

class MlProject(Base):
    __tablename__ = "ml_projects"

    id = PK()
    student_id = FK_I("users.id", index=True, comment="소유 학생")
    title = Column(String(120), nullable=False, default="새 프로젝트")
    description = Column(Text, default="")
    status = Column(String(20), default="collecting")   # collecting/learning/ready/exported
    model_type = Column(String(30), default="image")    # image (추후 pose/text/video 확장)
    sample_count = Column(Integer, default=0)
    model_path = Column(String(255), nullable=True)     # 학습 완료 모델 파일 경로
    model_export_path = Column(String(255), nullable=True)  # TFLite 등 내보낸 파일
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MlSample(Base):
    __tablename__ = "ml_samples"

    id = PK()
    project_id = FK_I("ml_projects.id", index=True, comment="소속 프로젝트")
    class_name = Column(String(50), nullable=False)     # 라벨 이름
    file_path = Column(String(255), nullable=False)     # 이미지 경로 (audio 모드는 스펙트로그램 PNG)
    media_type = Column(String(10), default="image")    # image / audio (Phase 2 음성 분류)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    Index("idx_ml_proj_class", "project_id", "class_name")


class MlArduinoMapping(Base):
    __tablename__ = "ml_arduino_mappings"

    id = PK()
    project_id = FK_I("ml_projects.id", index=True, comment="프로젝트")
    class_name = Column(String(50), nullable=False)     # 분류된 클래스
    action = Column(String(30), nullable=False, default="led_on")  # led_on/led_off/servo/buzzer
    target_value = Column(String(80), nullable=True)    # servo=90, pin=13 등
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    Index("idx_ml_map_proj", "project_id")

# 누비다머신 ML 모델 레지스트리 (클래스 정의 후 추가)
all_models.extend([
    MlProject,
    MlSample,
    MlArduinoMapping,
])


# ============================================================
# 과목(교육명) 마스터 — 본사에서 CRUD, 교육자료/강좌 분류 기준 통일
# ============================================================

class Subject(Base):
    __tablename__ = "subjects"

    id = PK()
    name = Column(String(50), nullable=False, unique=True, index=True, comment="과목(교육명)")
    sort_order = Column(Integer, default=0, comment="노출 순서")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
# 원장 교육 자료 (본사 → 원장 배포 전용)
# 학생 강좌 학습 자료(CourseMaterial)와 완전 분리 — course_id 불필요.
# ============================================================

class DirectorEduMaterial(Base):
    __tablename__ = "director_edu_materials"

    id = PK()
    title = Column(String(200), nullable=False)
    description = Column(Text)
    material_type = Column(String(30), nullable=False, default="document")
    # material_type: document(pdf/ppt/hwp), video, image, link
    file_url = Column(String(500))
    file_size = Column(Integer, default=0)
    category = Column(String(50), nullable=True, default="", comment="분류 (마케팅/매뉴얼/교사연수 등)")
    content_html = Column(Text)  # 상세 설명/링크 타입 시 URL 또는 내용
    is_published = Column(Boolean, default=False)
    view_count = Column(Integer, default=0)
    created_by = FK_I("users.id")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# 원장 교육 자료 레지스트리 (클래스 정의 후 추가)
all_models.append(DirectorEduMaterial)

# 과목 마스터 레지스트리
all_models.append(Subject)


# ============================================================
# 교육 신청 (공개 접수 → 본사 전용 관리) — 2026-09-21
# 개인정보(이름/연락처)는 본사(super_admin/admin) 전용.
# __init__ 로딩 완료 후 import 하여 순환 참조를 피한다.
# ============================================================
from app.models.edu_apply import (  # noqa: E402
    EduApplication, EduInstructorApplication, EduNotifyLog,
)

all_models.extend([EduApplication, EduInstructorApplication, EduNotifyLog])
