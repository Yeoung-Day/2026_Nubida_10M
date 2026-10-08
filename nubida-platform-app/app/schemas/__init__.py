from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Any
from datetime import date, datetime


# ============================================================
# 표준 응답
# ============================================================

class ApiResponse(BaseModel):
    status: str = "success"
    data: Any = None
    message: str = ""


class PaginatedResponse(ApiResponse):
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0


# ============================================================
# 인증
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str
    # ── 관리자 2단계 인증 (TOTP) — 2026-09-14 ──
    # totp_enabled=1 인 관리자 계정은 이 값이 있어야 최종 로그인된다.
    # 없으면 login() 이 {"totp_required": true} 를 반환한다.
    totp_code: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)
    name: str = Field(..., max_length=50)
    phone: Optional[str] = None
    role: str = Field(default="student")
    branch_id: Optional[int] = None
    registration_code: Optional[str] = None
    branch_name: Optional[str] = None
    # 소속배지 정책(9/7 확정): 신규 가입자만 저장 — region 우선, 없으면 branch_name
    region: Optional[str] = None
    academy_type: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    branch_id: Optional[int] = None
    memo: Optional[str] = None


class FindIdRequest(BaseModel):
    name: str = Field(..., max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)

class FindPasswordRequest(BaseModel):
    username: str
    name: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


# ============================================================
# 지사
# ============================================================

class BranchCreate(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    admin_id: Optional[int] = None


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None


# ============================================================
# 강좌
# ============================================================

class CourseCreate(BaseModel):
    title: str = Field(..., max_length=100)
    description: Optional[str] = None
    category: str = Field(..., min_length=1)
    status: Optional[str] = "active"
    folder_id: Optional[int] = None  # 폴더에 연결


class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    folder_id: Optional[int] = None  # 폴더 경로 변경


class EnrollmentCreate(BaseModel):
    student_id: int
    course_id: int


class ScoreCreate(BaseModel):
    student_id: int
    exam_id: int
    score: float
    feedback: Optional[str] = None


class PaymentCreate(BaseModel):
    student_id: int
    course_id: int
    branch_id: int
    parent_id: Optional[int] = None
    amount: float
    method: str


class NotificationCreate(BaseModel):
    user_id: int
    title: str
    content: Optional[str] = None
    notif_type: str = "system"


# ============================================================
# 공지사항
# ============================================================

class NoticeCreate(BaseModel):
    title: str = Field(..., max_length=200)
    content: Optional[str] = None
    author: str = "관리자"
    status: str = "published"
    is_pinned: bool = False
    # 팝업 (로그인 시 전체화면 공지)
    is_popup: bool = False
    popup_start: Optional[str] = ""
    popup_end: Optional[str] = ""
    popup_targets: Optional[str] = "all"
    # 발행 대상 — 메인페이지 + 사용자 페이지 복수 선택 (콤마 구분)
    # 예: "main,student,parent" / "all" (전체)
    publish_targets: Optional[str] = ""
    # 첨부 이미지 경로 JSON 배열 문자열
    images: Optional[str] = ""


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    is_pinned: Optional[bool] = None
    # 팝업
    is_popup: Optional[bool] = None
    popup_start: Optional[str] = None
    popup_end: Optional[str] = None
    popup_targets: Optional[str] = None
    publish_targets: Optional[str] = None
    images: Optional[str] = None


# ============================================================
# 학습 자료
# ============================================================

class CourseMaterialCreate(BaseModel):
    course_id: int
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    material_type: str = "document"
    file_url: Optional[str] = None
    embed_url: Optional[str] = None
    file_size: int = 0
    duration_minutes: int = 0
    content_html: Optional[str] = None
    sort_order: int = 0
    chapter: Optional[str] = None


class CourseMaterialUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    material_type: Optional[str] = None
    file_url: Optional[str] = None
    embed_url: Optional[str] = None
    file_size: Optional[int] = None
    duration_minutes: Optional[int] = None
    content_html: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    chapter: Optional[str] = None


class LearningProgressUpdate(BaseModel):
    material_id: Optional[int] = None
    block_index: Optional[int] = None
    is_completed: bool = False
    progress_percent: int = 0


# ============================================================
# 누비다 AI (ai_assistant) — 확정설계안 v2
# ============================================================

class AiChatRequest(BaseModel):
    """학생 채팅 질문 — attempt(힌트 단계 1~4) 포함"""
    course_id: Optional[int] = None
    message: str = Field(..., min_length=1, max_length=1000, description="질문 내용 (1~1000자)")
    attempt: int = Field(1, ge=1, le=4, description="힌트 단계 — ⚠️ 부족 누를 때마다 증가")


class AiFeedbackRequest(BaseModel):
    """✅ 해결(1) / ⚠️ 부족(-1) 피드백"""
    message_id: int
    helpful: int = Field(..., ge=-1, le=1, description="1=해결, -1=부족")
    comment: Optional[str] = Field(None, max_length=500)


class AiFaqPublishRequest(BaseModel):
    """본사 FAQ 승격/거절"""
    faq_id: int
    action: str = Field(..., pattern="^(publish|reject)$")


# ============================================================
# 강좌 폴더
# ============================================================

class FolderCreate(BaseModel):
    name: str = Field(..., max_length=100, description="폴더명")
    parent_id: Optional[int] = Field(None, description="부모 폴더 ID (null=최상위)")
    category: Optional[str] = Field(None, description="카테고리 (null=전체공용)")


class FolderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    category: Optional[str] = None


class StudentScheduleCreate(BaseModel):
    title: str = Field(..., max_length=200)
    date: date
    start_time: Optional[str] = None  # "HH:MM"
    end_time: Optional[str] = None    # "HH:MM"
    memo: Optional[str] = None
    color: Optional[str] = "#0891B2"


class StudentScheduleUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    memo: Optional[str] = None
    color: Optional[str] = None


# ============================================================
# 카테고리 관리
# ============================================================

class CategoryCreate(BaseModel):
    key: str = Field(..., max_length=50, description="카테고리 키 (e.g. maker_coding)")
    name: str = Field(..., max_length=100, description="카테고리명 (e.g. 메이커 코딩)")
    sort_order: Optional[int] = Field(0, description="정렬 순서")
    color: Optional[str] = Field(None, max_length=7, description="글자색 hex")
    bg_color: Optional[str] = Field(None, max_length=7, description="배경색 hex")


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    key: Optional[str] = Field(None, max_length=50)
    sort_order: Optional[int] = None
    color: Optional[str] = Field(None, max_length=7)
    bg_color: Optional[str] = Field(None, max_length=7)
    is_active: Optional[bool] = None
    is_public: Optional[bool] = Field(None, description="전체 공개(원장/에듀케어 매출·인원 사용 허용)")


class CategoryResponse(BaseModel):
    id: int
    key: str
    name: str
    sort_order: int
    color: Optional[str] = None
    bg_color: Optional[str] = None
    is_active: bool
    course_count: int = 0
    folder_count: int = 0
    created_at: Optional[str] = None


class FolderCourseAction(BaseModel):
    course_id: int = Field(..., description="폴더에 추가/제거할 강좌 ID")


# ============================================================
# 보고서
# ============================================================

class ReportCreate(BaseModel):
    report_type: str = Field(..., description="보고서 타입 (학생 성적 보고서, 출결 현황 보고서, 수업 통계 보고서)")
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None


class ReportResponse(BaseModel):
    id: int
    director_id: int
    title: str
    report_type: str
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None
    file_path: str
    file_size: int
    created_at: Optional[datetime] = None


class DirectorReportCreate(BaseModel):
    """원장 월간 보고서 작성"""
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    # 기본 정보
    branch_name: str = ""
    director_name: str = ""
    contact: str = ""
    # 수강생 현황
    total_students: int = 0
    new_registrations: int = 0
    withdrawals: int = 0
    retention_rate: int = 0
    # 이번 달 목표
    target_new_students: int = 0
    target_monthly_revenue: int = 0
    target_other: str = ""
    # 이슈 및 건의사항
    issue_facility_content: str = ""
    issue_facility_request: str = ""
    issue_education_content: str = ""
    issue_education_request: str = ""
    issue_admin_content: str = ""
    issue_admin_request: str = ""
    issue_other_content: str = ""
    issue_other_request: str = ""
    # 실적
    result_new_students: int = 0
    result_new_students_rate: int = 0
    result_monthly_revenue: int = 0
    result_monthly_revenue_rate: int = 0
    result_retention_rate: int = 0
    result_retention_rate_achieved: int = 0
    # 특이사항
    notes: str = ""
    # 서명
    confirmed_date: str = ""
    is_agreed: bool = False
    status: str = "draft"


class DirectorReportResponse(BaseModel):
    id: int
    director_id: int
    status: str
    year: int
    month: int
    branch_name: str
    director_name: str
    contact: str
    total_students: int
    new_registrations: int
    withdrawals: int
    retention_rate: int
    target_new_students: int
    target_monthly_revenue: int
    target_other: str
    issue_facility_content: str
    issue_facility_request: str
    issue_education_content: str
    issue_education_request: str
    issue_admin_content: str
    issue_admin_request: str
    issue_other_content: str
    issue_other_request: str
    result_new_students: int
    result_new_students_rate: int
    result_monthly_revenue: int
    result_monthly_revenue_rate: int
    result_retention_rate: int
    result_retention_rate_achieved: int
    notes: str
    confirmed_date: str
    is_agreed: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BranchReportCreate(BaseModel):
    """지사 월간 보고서 작성"""
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    branch_id: Optional[int] = None
    director_report_id: Optional[int] = None
    # 기본 정보
    branch_name: str = ""
    manager_name: str = ""
    contact: str = ""
    # 수강생 현황
    total_students: int = 0
    new_registrations: int = 0
    withdrawals: int = 0
    retention_rate: int = 0
    # 이번 달 목표
    target_new_students: int = 0
    target_monthly_revenue: int = 0
    target_other: str = ""
    # 이슈 및 건의사항
    issue_facility_content: str = ""
    issue_facility_request: str = ""
    issue_education_content: str = ""
    issue_education_request: str = ""
    issue_admin_content: str = ""
    issue_admin_request: str = ""
    issue_other_content: str = ""
    issue_other_request: str = ""
    # 실적
    result_new_students: int = 0
    result_new_students_rate: int = 0
    result_monthly_revenue: int = 0
    result_monthly_revenue_rate: int = 0
    result_retention_rate: int = 0
    result_retention_rate_achieved: int = 0
    # 특이사항
    notes: str = ""
    # 서명
    confirmed_date: str = ""
    is_agreed: bool = False
    director_report_received: bool = False
    status: str = "draft"


class BranchReportResponse(BaseModel):
    id: int
    branch_id: int
    director_report_id: Optional[int] = None
    status: str
    year: int
    month: int
    branch_name: str
    manager_name: str
    contact: str
    total_students: int
    new_registrations: int
    withdrawals: int
    retention_rate: int
    target_new_students: int
    target_monthly_revenue: int
    target_other: str
    issue_facility_content: str
    issue_facility_request: str
    issue_education_content: str
    issue_education_request: str
    issue_admin_content: str
    issue_admin_request: str
    issue_other_content: str
    issue_other_request: str
    result_new_students: int
    result_new_students_rate: int
    result_monthly_revenue: int
    result_monthly_revenue_rate: int
    result_retention_rate: int
    result_retention_rate_achieved: int
    notes: str
    confirmed_date: str
    is_agreed: bool
    director_report_received: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============================================================
# 원장 교육 자료 (본사 → 원장 배포)
# ============================================================

class DirectorEduMaterialCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    material_type: str = "document"
    file_url: Optional[str] = None
    file_size: int = 0
    category: Optional[str] = None
    content_html: Optional[str] = None
    is_published: bool = False


class DirectorEduMaterialUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    material_type: Optional[str] = None
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    category: Optional[str] = None
    content_html: Optional[str] = None
    is_published: Optional[bool] = None


# ============================================================
# 과목(교육명) 마스터
# ============================================================

class SubjectCreate(BaseModel):
    name: str = Field(..., max_length=50)
    sort_order: Optional[int] = 0


class SubjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
