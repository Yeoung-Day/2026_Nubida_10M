"""
누비다플랫폼 — 본사(Headquarters) 전용 API 라우터
본사 관리자(super_admin/admin)가 사용: 대시보드, 지사/프로그램/강좌/카테고리/계약/결제/보고서 통합 관리
카테고리 시스템 (2026-06): ai_art(AI미술), ai_robot(AI로봇) 2개 카테고리로 통일
"""
from typing import Optional
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Response, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, and_ as sa_and_, delete, update, or_, cast, Integer
from datetime import date, datetime, timedelta, timezone

from app.core.database import get_db
from app.core.security import get_current_user, require_role, hash_password, generate_registration_code
from app.core.config import settings
from app.models import (
    User, Branch, Academy, Course, Enrollment, Payment, Notification, AccessLog,
    Notice, EducationProgram, ProgramChapter, ProgramAssignment,
    DirectorContract, DirectorReport, BranchReport, CourseFolderItem, RevenueApproval,
    Revenue, BranchSetting,
    WithdrawnStudent, CourseFolder, ClassStudent, Category as CatModel,
    Revenue, CourseMaterial, AcademyCourse,
    SchoolClass, TuitionPayment, ClassCourse,
)
from app.schemas import (
    UserCreate, UserUpdate, BranchCreate, BranchUpdate,
    ApiResponse, PaginatedResponse, NoticeCreate, NoticeUpdate,
    CourseCreate, CourseUpdate, CategoryCreate, CategoryUpdate,
    FolderCreate, FolderUpdate,
)

router = APIRouter(prefix="/headquarters", tags=["본사 관리"])


class PendingUserProxy:
    """pending.db의 사용자를 메인 DB User 객체처럼 사용하기 위한 프록시"""
    def __init__(self, data):
        self.id = data["id"]
        self.username = data["username"]
        self.name = data["name"]
        self.email = data.get("email", data["username"])
        self.phone = data.get("phone", "")
        self.role = data["role"]
        self.branch_id = data.get("branch_id")
        self.registration_code = data.get("registration_code", "")
        self.is_active = False
        self.created_at = data.get("requested_at", "")
        self.requested_at = data.get("requested_at", "")
        self.pending = True


def _paginate(total: int, page: int, per_page: int) -> int:
    """계산: total_pages"""
    if total <= 0:
        return 0
    return (total + per_page - 1) // per_page


DEFAULT_SETTLEMENT_CONFIG = {"hq_royalty_rate": 45, "profit_rate": 7, "income_tax_rate": 3.3}


async def _ensure_branch_setting(db, branch_id):
    """지사의 정산 설정(BranchSetting)이 없으면 기본값으로 생성.

    ★ 승인 시점에 반드시 생성해 두어, 본사 지사 관리 화면에서
      정산 설정(로열티율/순수익률/사업소득세율)을 바로 수정할 수 있게 한다.
    """
    if not branch_id:
        return None
    existing = (await db.execute(
        select(BranchSetting).where(BranchSetting.branch_id == branch_id)
    )).scalar_one_or_none()
    if existing:
        # 기존 값이 있으면 누락된 키만 채운다 (덮어쓰지 않음)
        cfg = dict(existing.payment_config or {})
        changed = False
        for k, v in DEFAULT_SETTLEMENT_CONFIG.items():
            if cfg.get(k) is None:
                cfg[k] = v
                changed = True
        if changed:
            existing.payment_config = cfg
        return existing
    new_bs = BranchSetting(branch_id=branch_id, payment_config=dict(DEFAULT_SETTLEMENT_CONFIG))
    db.add(new_bs)
    await db.flush()
    return new_bs


# ============================================================
# Section 1: 탈퇴 회원 관리
# ============================================================


@router.get("/withdrawn-students")
async def get_withdrawn_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 탈퇴/수업종료 학생 목록 (페이지네이션)"""
    total_query = select(func.count(WithdrawnStudent.id))
    total = (await db.execute(total_query)).scalar() or 0

    query = (
        select(WithdrawnStudent)
        .order_by(WithdrawnStudent.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": s.id,
            "student_id": s.student_id,
            "student_name": s.student_name,
            "username": s.student_username,
            "email": s.student_email,
            "course_name": s.course_name,
            "branch_name": s.branch_name,
            "director_name": s.director_name,
            "end_date": str(s.end_date) if s.end_date else None,
            "reason": s.reason,
            "withdrawn_by": s.withdrawn_by,
            "created_at": str(s.created_at) if s.created_at else None,
        } for s in items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


# ============================================================
# Section 1b: 대시보드
# ============================================================


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 대시보드 통계"""
    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    active_branches = (await db.execute(
        select(func.count(Branch.id)).where(Branch.status == "active")
    )).scalar()
    total_revenue = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == "completed")
    )).scalar()
    total_enrollments = (await db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.status == "active")
    )).scalar()

    return ApiResponse(data={
        "total_users": user_count or 0,
        "active_branches": active_branches or 0,
        "total_revenue": float(total_revenue or 0),
        "total_enrollments": total_enrollments or 0,
        "total_branches": active_branches or 0,
        "today_signups": 0,
        "monthly_revenue": float(total_revenue or 0),
        "branches": [],
        "recent_activities": [],
    })


# ============================================================
# Section 2: Users CRUD
# ============================================================


@router.get("/users")
async def get_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    role: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
    response: Response = None,
):
    """본사 — 사용자 목록 (페이지네이션, 역할 필터)"""
    if response:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    query = select(User)
    count_query = select(func.count(User.id))

    conditions = []
    if role:
        conditions.append(User.role == role)
    else:
        # 전체 역할 — 모든 사용자 표시 (super_admin 포함)
        pass

    if conditions:
        query = query.where(sa_and_(*conditions))
        count_query = count_query.where(sa_and_(*conditions))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "name": u.name,
            "phone": u.phone,
            "role": u.role,
            "branch_id": u.branch_id,
            "registration_code": u.registration_code,
            "is_active": u.is_active,
            "created_at": str(u.created_at) if u.created_at else None,
        } for u in users],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.post("/users")
async def create_user(
    data: UserCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 새 사용자 생성"""
    existing = await db.execute(
        select(User).where((User.username == data.username) | (User.email == data.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 존재하는 사용자명 또는 이메일입니다.")

    code = generate_registration_code()
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        phone=data.phone,
        role=data.role or "student",
        branch_id=data.branch_id,
        registration_code=code,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data={
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "registration_code": user.registration_code,
    }, message="사용자가 생성되었습니다.")


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 사용자 정보 수정"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data={
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "email": user.email,
    }, message="사용자가 수정되었습니다.")


@router.put("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 사용자 활성/비활성 상태 토글"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if user.id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="본인 계정은 정지할 수 없습니다.")
    user.is_active = not (user.is_active or False)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data={"id": user.id, "is_active": user.is_active}, message="사용자 상태가 변경되었습니다.")


@router.put("/users/{user_id}/nubida-machine-lock")
async def toggle_nubida_machine_lock(
    user_id: int,
    body: dict = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 원장의 누비다머신 사용 잠금 설정/해제 (소속 학생 전체 차단/복구)"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if user.role != "director":
        raise HTTPException(status_code=400, detail="원장 계정만 누비다머신 잠금을 설정할 수 있습니다.")
    body = body or {}
    locked = bool(body.get("locked", not (user.nubida_machine_locked or False)))
    user.nubida_machine_locked = locked
    await db.commit()
    await db.refresh(user)
    return ApiResponse(
        data={"id": user.id, "role": user.role, "nubida_machine_locked": bool(user.nubida_machine_locked or False)},
        message="누비다머신 사용이 잠금 처리되었습니다." if locked else "누비다머신 사용이 정상화되었습니다.",
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 사용자 삭제 (연결된 에듀케어/학원도 함께 정리)"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    from app.models import (
        Branch, Academy, DirectorContract, Attendance, Score,
        PushSubscription, UserToken, PointTransaction, LearningProgress,
        StudentSchedule, WithdrawnStudent, RemoteClass, RemoteAttendance,
        ArduinoCode, ChatParticipant, ChatMessage, GifticonRequest, Portfolio,
        MembershipLink, ReportHistory, SchoolClass, ClassSchedule, ChatRoom,
        DirectorCategory, Revenue,
    )

    # ===== FK 참조 테이블 정리 (모든 역할 공통) =====
    # attendance
    await db.execute(delete(Attendance).where(Attendance.student_id == user_id))
    # scores
    await db.execute(delete(Score).where(Score.student_id == user_id))
    # enrollments
    await db.execute(delete(Enrollment).where(Enrollment.student_id == user_id))
    # activities (uploaded_by) — models에 Activity 클래스가 없어 raw SQL로 처리
    from sqlalchemy import text as sa_text
    await db.execute(sa_text("DELETE FROM activities WHERE uploaded_by = :uid"), {"uid": user_id})
    # push_subscriptions
    await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id))
    # user_tokens
    await db.execute(delete(UserToken).where(UserToken.user_id == user_id))
    # notifications
    await db.execute(delete(Notification).where(Notification.user_id == user_id))
    # point_transactions
    await db.execute(delete(PointTransaction).where(PointTransaction.user_id == user_id))
    # learning_progress
    await db.execute(delete(LearningProgress).where(LearningProgress.student_id == user_id))
    # class_students
    await db.execute(delete(ClassStudent).where(ClassStudent.student_id == user_id))
    # student_schedules
    await db.execute(delete(StudentSchedule).where(StudentSchedule.student_id == user_id))
    # withdrawn_students
    await db.execute(delete(WithdrawnStudent).where(WithdrawnStudent.student_id == user_id))
    await db.execute(delete(WithdrawnStudent).where(WithdrawnStudent.withdrawn_by == user_id))
    # remote_classes (teacher_id)
    await db.execute(delete(RemoteClass).where(RemoteClass.teacher_id == user_id))
    # remote_attendance (student_id)
    await db.execute(delete(RemoteAttendance).where(RemoteAttendance.student_id == user_id))
    # arduino_codes
    await db.execute(delete(ArduinoCode).where(ArduinoCode.user_id == user_id))
    # chat_participants
    await db.execute(delete(ChatParticipant).where(ChatParticipant.user_id == user_id))
    # chat_messages (sender_id)
    await db.execute(delete(ChatMessage).where(ChatMessage.sender_id == user_id))
    # gifticon_requests (user_id, admin_id)
    await db.execute(delete(GifticonRequest).where(GifticonRequest.user_id == user_id))
    await db.execute(delete(GifticonRequest).where(GifticonRequest.admin_id == user_id))
    # portfolios
    await db.execute(delete(Portfolio).where(Portfolio.student_id == user_id))
    # payments (student_id, parent_id)
    await db.execute(delete(Payment).where(Payment.student_id == user_id))
    await db.execute(delete(Payment).where(Payment.parent_id == user_id))
    # revenues (director_id, student_id)
    await db.execute(delete(Revenue).where(Revenue.director_id == user_id))
    await db.execute(delete(Revenue).where(Revenue.student_id == user_id))
    # revenue_approvals (director_id, approved_by)
    await db.execute(delete(RevenueApproval).where(RevenueApproval.director_id == user_id))
    await db.execute(delete(RevenueApproval).where(RevenueApproval.approved_by == user_id))
    # access_logs
    await db.execute(delete(AccessLog).where(AccessLog.user_id == user_id))
    # course_materials (created_by)
    await db.execute(delete(CourseMaterial).where(CourseMaterial.created_by == user_id))
    # education_programs (created_by)
    await db.execute(delete(EducationProgram).where(EducationProgram.created_by == user_id))
    # program_assignments (assigned_by)
    await db.execute(delete(ProgramAssignment).where(ProgramAssignment.assigned_by == user_id))
    # branch_reports (author_id)
    await db.execute(delete(BranchReport).where(BranchReport.author_id == user_id))
    # director_reports (director_id)
    await db.execute(delete(DirectorReport).where(DirectorReport.director_id == user_id))
    # report_history (director_id)
    await db.execute(delete(ReportHistory).where(ReportHistory.director_id == user_id))
    # school_classes (director_id)
    await db.execute(delete(SchoolClass).where(SchoolClass.director_id == user_id))
    # class_schedules (teacher_id)
    await db.execute(delete(ClassSchedule).where(ClassSchedule.teacher_id == user_id))
    # chat_rooms (created_by)
    await db.execute(delete(ChatRoom).where(ChatRoom.created_by == user_id))
    # director_categories (director_id)
    await db.execute(delete(DirectorCategory).where(DirectorCategory.director_id == user_id))
    # membership_links (parent_id, child_id)
    await db.execute(delete(MembershipLink).where(MembershipLink.parent_id == user_id))
    await db.execute(delete(MembershipLink).where(MembershipLink.child_id == user_id))
    # director_contracts (director_id, created_by)
    await db.execute(delete(DirectorContract).where(DirectorContract.director_id == user_id))
    await db.execute(delete(DirectorContract).where(DirectorContract.created_by == user_id))

    # users 테이블 내 self-referencing (director_id, approved_by) 해제
    await db.execute(
        update(User).where(User.director_id == user_id).values(director_id=None)
    )
    await db.execute(
        update(User).where(User.approved_by == user_id).values(approved_by=None)
    )

    # branch_admin(에듀케어) 삭제 시 연결된 Branch도 삭제
    if user.role == "branch_admin" and user.branch_id:
        # user 자신의 branch_id FK를 먼저 해제 (삭제할 branch가 users 테이블에서 참조되고 있음)
        branch_to_delete_id = user.branch_id
        await db.execute(
            update(User).where(User.id == user_id).values(branch_id=None)
        )
        user.branch_id = None
        branch = await db.get(Branch, branch_to_delete_id)
        if branch:
            await db.delete(branch)

    # director(원장) 삭제 시 해당 원장 이름의 Academy + AcademyCourse + DirectorContract만 삭제
    if user.role == "director":
        acad_result = await db.execute(
            select(Academy).where(Academy.director_name == user.name)
        )
        academies = acad_result.scalars().all()
        for acad in academies:
            # AcademyCourse 먼저 삭제
            await db.execute(
                delete(AcademyCourse).where(AcademyCourse.academy_id == acad.id)
            )
            # Academy 자체 삭제
            await db.delete(acad)

    # student, director 등 모든 사용자 실제 삭제
    await db.delete(user)
    await db.commit()
    return ApiResponse(message="사용자와 연결된 모든 데이터가 삭제되었습니다.")


# ============================================================
# Section 3: Branches CRUD
# ============================================================


@router.get("/branches")
async def get_branches(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    show_pending: bool = Query(False, description="승인 대기 지사 포함 여부"),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 목록 (승인된 지사만 표시, show_pending=True 시 전체)"""
    base_query = select(Branch)
    if not show_pending:
        base_query = base_query.where(Branch.is_approved == True)
    count_query = select(func.count(Branch.id))
    if not show_pending:
        count_query = count_query.where(Branch.is_approved == True)
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        base_query.order_by(Branch.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    branches = result.scalars().all()
    return PaginatedResponse(
        data=[{
            "id": b.id,
            "name": b.name,
            "code": b.code,
            "address": b.address,
            "phone": b.phone,
            "email": b.email,
            "status": b.status,
            "contract_start": str(b.contract_start) if b.contract_start else None,
            "contract_end": str(b.contract_end) if b.contract_end else None,
            "created_at": str(b.created_at) if b.created_at else None,
            "is_approved": b.is_approved,
        } for b in branches],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/branches/list")
async def list_branches_for_assign(
    db: AsyncSession = Depends(get_db),
):
    """지사 목록 (회원가입 시 소속 선택용) - 인증 불필요"""
    result = await db.execute(
        select(Branch.id, Branch.name).where(Branch.status == "active").order_by(Branch.name)
    )
    return ApiResponse(data=[{"id": r.id, "name": r.name} for r in result.all()])


@router.get("/branches/public-map")
async def list_branches_public_map(
    db: AsyncSession = Depends(get_db),
):
    """
    공개 — 교육기관 찾기 지도용 기관 목록 (인증 불필요)
    - 에듀케어(Branch): 승인(is_approved) + 운영중(status=active) 지사만 노출. kind="educare"
    - 학원(Academy): 운영중(status=active)인 실제 교육기관(원장 운영) 노출. kind="academy"
    마커/목록 표시용(id/name/kind/address/phone/region/소속에듀케어명)만 반환 — 내부데이터 미포함.
    """
    items = []

    # 1) 에듀케어(지사, Branch)
    result = await db.execute(
        select(Branch)
        .where(Branch.is_approved == True, Branch.status == "active")  # noqa: E712
        .order_by(Branch.name)
    )
    branches = result.scalars().all()
    for b in branches:
        items.append({
            "id": b.id,
            "key": f"educare-{b.id}",  # 프론트 라우팅·필터용 유일 키
            "kind": "educare",         # 에듀케어(지사)
            "name": b.name or "",
            "address": b.address or "",
            "phone": b.phone or "",
            "branch_type": "educare",
            "region": _public_sido(b.address),
            "parent": "",              # 에듀케어는 그 자체가 기관
        })

    # 2) 학원(Academy) — 운영중(active). branch_id가 있으면 소속 에듀케어명 함께
    acad_result = await db.execute(
        select(Academy).where(Academy.status == "active").order_by(Academy.name)
    )
    academies = acad_result.scalars().all()
    acad_branch_ids = [a.branch_id for a in academies if a.branch_id]
    branch_name_map = {}
    if acad_branch_ids:
        br_res = await db.execute(select(Branch).where(Branch.id.in_(acad_branch_ids)))
        for br in br_res.scalars().all():
            branch_name_map[br.id] = br.name

    for a in academies:
        parent = ((a.branch_id in branch_name_map) and branch_name_map[a.branch_id]) or ""
        items.append({
            "id": a.id,
            "key": f"academy-{a.id}",
            "kind": "academy",         # 학원(원장 운영)
            "name": a.name or "",
            "address": a.address or "",
            "phone": a.phone or "",
            "branch_type": "academy",
            "region": _public_sido(a.address),
            "parent": parent,
        })

    return ApiResponse(data=items)


_PUBLIC_SIDOS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "강원도", "충청북도", "충청남도", "전라북도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도", "제주도",
]


def _public_sido(address):
    """도로명/지번 주소에서 자치시도 이름 추출 (매칭 실패 시 '')"""
    if not address:
        return ""
    a = address.strip()
    for s in _PUBLIC_SIDOS:
        if a.startswith(s):
            return s
    return ""


@router.get("/branches/by-type")
async def list_branches_by_type(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 유형별 목록 (직영/프랜차이즈)"""
    result = await db.execute(select(Branch).order_by(Branch.name))
    branches = result.scalars().all()

    # Get contract type for each branch
    branch_ids = [b.id for b in branches]
    contract_map = {}
    if branch_ids:
        c_res = await db.execute(
            select(DirectorContract.branch_id, DirectorContract.contract_type).where(
                DirectorContract.branch_id.in_(branch_ids),
                DirectorContract.status == "active",
            )
        )
        for row in c_res.all():
            contract_map[row.branch_id] = row.contract_type

    direct = []
    franchise = []
    for b in branches:
        bt = contract_map.get(b.id, "direct")
        item = {
            "id": b.id,
            "name": b.name,
            "code": b.code,
            "status": b.status,
            "type": bt,
        }
        if bt == "direct":
            direct.append(item)
        else:
            franchise.append(item)

    return ApiResponse(data={
        "direct": direct,
        "franchise": franchise,
    })


@router.get("/branches/{branch_id}")
async def get_branch_detail(
    branch_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 상세 정보 (학생/직원 수 포함)"""
    if current_user.get("role") == "branch_admin" and current_user.get("branch_id") != branch_id:
        raise HTTPException(status_code=403, detail="자신의 에듀케어 정보만 조회할 수 있습니다.")
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    student_count_q = select(func.count(User.id)).where(
        User.branch_id == branch_id, User.role == "student"
    )
    employee_count_q = select(func.count(User.id)).where(
        User.branch_id == branch_id, User.role.in_(["director", "teacher", "branch_admin"])
    )
    student_count = (await db.execute(student_count_q)).scalar() or 0
    employee_count = (await db.execute(employee_count_q)).scalar() or 0

    # 정산 설정 (본사 주관 — BranchSetting.payment_config)
    #   hq_royalty_rate : 본사 로열티율 % (기본 45)
    #   profit_rate     : 에듀케어 순수익률 % (기본 7, 과세표준 기준)
    #   income_tax_rate : 순수익 공제율 % (기본 3.3, 순수익에서 차감) — 3.3%(사업소득세) 또는 10% 선택
    hq_royalty_rate, profit_rate, income_tax_rate = 45.0, 7.0, 3.3
    bank_name, account_number, account_holder = "", "", ""
    bs_result = await db.execute(
        select(BranchSetting).where(BranchSetting.branch_id == branch_id)
    )
    bs = bs_result.scalar_one_or_none()
    if bs and bs.payment_config:
        cfg = bs.payment_config
        if cfg.get("hq_royalty_rate") is not None:
            hq_royalty_rate = float(cfg["hq_royalty_rate"])
        if cfg.get("profit_rate") is not None:
            profit_rate = float(cfg["profit_rate"])
        if cfg.get("income_tax_rate") is not None:
            income_tax_rate = float(cfg["income_tax_rate"])
        bank_name = cfg.get("bank_name", "") or ""
        account_number = cfg.get("account_number", "") or ""
        account_holder = cfg.get("account_holder", "") or ""

    return ApiResponse(data={
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "phone": branch.phone,
        "email": branch.email,
        "status": branch.status,
        "contract_start": str(branch.contract_start) if branch.contract_start else None,
        "contract_end": str(branch.contract_end) if branch.contract_end else None,
        "license_key": branch.license_key,
        "student_count": student_count,
        "employee_count": employee_count,
        "created_at": str(branch.created_at) if branch.created_at else None,
        "is_approved": branch.is_approved,
        # 정산 설정 (본사 관리)
        "hq_royalty_rate": hq_royalty_rate,
        "profit_rate": profit_rate,
        "income_tax_rate": income_tax_rate,
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
    })


@router.put("/branches/{branch_id}/settlement")
async def update_branch_settlement(
    branch_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사별 정산 설정 저장 (로열티율 / 에듀케어 순수익률 / 사업소득세율).

    ★ 정산 설정은 본사가 주관한다. 에듀케어 매출관리 ⚙️ 는 시뮬레이션 전용이며
      실제 정산 값은 이 엔드포인트로만 저장된다.
    """
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    bs_result = await db.execute(
        select(BranchSetting).where(BranchSetting.branch_id == branch_id)
    )
    bs = bs_result.scalar_one_or_none()
    if not bs:
        bs = BranchSetting(branch_id=branch_id, payment_config={})
        db.add(bs)

    config = dict(bs.payment_config or {})
    rate_keys = ("hq_royalty_rate", "profit_rate", "income_tax_rate")
    for key in rate_keys:
        if key in data and data[key] is not None and data[key] != "":
            try:
                rate = float(data[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="수익률은 숫자여야 합니다.")
            if rate < 0 or rate > 100:
                raise HTTPException(status_code=400, detail="수익률은 0~100 사이여야 합니다.")
            config[key] = rate

    # 입금 계좌도 본사에서 함께 관리 가능 (에듀케어가 입력한 값이 있으면 유지)
    for key in ("bank_name", "account_number", "account_holder"):
        if key in data:
            config[key] = str(data[key] or "").strip()

    bs.payment_config = config
    await db.commit()
    return ApiResponse(data={
        "branch_id": branch_id,
        "hq_royalty_rate": config.get("hq_royalty_rate", 45),
        "profit_rate": config.get("profit_rate", 7),
        "income_tax_rate": config.get("income_tax_rate", 3.3),
    }, message="정산 설정이 저장되었습니다.")


@router.get("/branches/{branch_id}/overview")
async def get_branch_overview(
    branch_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 오버뷰 (지사정보 + 소속원장 + 학생 + 결제 통합)"""
    # branch_admin은 자신의 branch만 조회 가능
    if current_user.get("role") == "branch_admin" and current_user.get("branch_id") != branch_id:
        raise HTTPException(status_code=403, detail="자신의 에듀케어 정보만 조회할 수 있습니다.")
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    # Directors (소속 원장) — 승인된 원장만 표시
    d_result = await db.execute(
        select(User).where(User.branch_id == branch_id, User.role == "director", User.is_active == True)
    )
    directors = d_result.scalars().all()

    # Students
    s_result = await db.execute(
        select(User).where(User.branch_id == branch_id, User.role == "student")
    )
    students = s_result.scalars().all()

    # Payments — 최근 결제 내역 (목록 표시용, 최대 20건)
    p_result = await db.execute(
        select(Payment).where(Payment.branch_id == branch_id).order_by(Payment.created_at.desc()).limit(20)
    )
    payments = p_result.scalars().all()

    # Payment 전체 집계 — .limit() 없이 SQL 집계 (50건 제한으로 total이 왜곡되던 버그 수정)
    pay_count = (await db.execute(
        select(func.count(Payment.id)).where(Payment.branch_id == branch_id)
    )).scalar() or 0
    pay_amount = float((await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.branch_id == branch_id)
    )).scalar() or 0)
    pay_completed = (await db.execute(
        select(func.count(Payment.id)).where(Payment.branch_id == branch_id, Payment.status == "completed")
    )).scalar() or 0
    pay_pending = (await db.execute(
        select(func.count(Payment.id)).where(Payment.branch_id == branch_id, Payment.status.in_(["pending", "failed"]))
    )).scalar() or 0

    # DirectorReport — 원장별 매출 (submitted 상태)
    dr_result = await db.execute(
        select(
            DirectorReport.director_id,
            func.sum(DirectorReport.result_monthly_revenue).label("revenue_amount"),
            func.count(DirectorReport.id).label("revenue_count"),
        ).where(
            DirectorReport.branch_id == branch_id,
            DirectorReport.status.in_(["submitted", "confirmed_by_branch", "confirmed_by_hq"]),
        ).group_by(DirectorReport.director_id)
    )
    director_revenues = {
        row.director_id: {
            "revenue_amount": int(row.revenue_amount or 0),
            "revenue_count": int(row.revenue_count or 0),
        }
        for row in dr_result.all()
    }

    # Revenue — 원장 일별 매출 (원장별 합계)
    rev_result = await db.execute(
        select(
            Revenue.director_id,
            func.sum(Revenue.amount).label("daily_revenue"),
            func.count(Revenue.id).label("daily_count"),
        ).where(
            Revenue.branch_id == branch_id,
        ).group_by(Revenue.director_id)
    )
    director_daily_revenues = {
        row.director_id: {
            "daily_revenue": float(row.daily_revenue or 0),
            "daily_count": int(row.daily_count or 0),
        }
        for row in rev_result.all()
    }

    # Payment — 원장별 수강생 결제 통계 (Enrollment를 통해 원장 매핑)
    payment_stats_by_director = {}
    for p in payments:
        # Payment에 연결된 student 찾기
        s = next((s for s in students if s.id == p.student_id), None)
        if s and s.director_id:
            d_id = s.director_id
        else:
            d_id = "unassigned"
        if d_id not in payment_stats_by_director:
            payment_stats_by_director[d_id] = {"total_amount": 0, "completed": 0, "pending": 0, "count": 0, "list": []}
        amt = p.amount or 0
        payment_stats_by_director[d_id]["total_amount"] += amt
        payment_stats_by_director[d_id]["count"] += 1
        if p.status == "completed":
            payment_stats_by_director[d_id]["completed"] += 1
        elif p.status == "pending":
            payment_stats_by_director[d_id]["pending"] += 1
        payment_stats_by_director[d_id]["list"].append({
            "id": p.id,
            "amount": amt,
            "status": p.status,
            "paid_at": str(p.paid_at) if p.paid_at else None,
            "created_at": str(p.created_at) if p.created_at else None,
            "student_id": p.student_id,
            "student_name": s.name if s else "",
        })

    # 각 원장에게 revenue_amount 매핑
    # ⭐ 결제 금액(total_payment/payment_total)은 실제 매출 데이터(revenues) 기준으로 계산
    #   - payments 테이블은 별도(수강생 결제)이며, 에듀케어 매출 요약에는 revenues(+director_reports 합계)를 사용
    enriched_directors = []
    for d in directors:
        rev = director_revenues.get(d.id, {"revenue_amount": 0, "revenue_count": 0})
        daily = director_daily_revenues.get(d.id, {"daily_revenue": 0, "daily_count": 0})
        ps = payment_stats_by_director.get(d.id, {"total_amount": 0, "completed": 0, "pending": 0, "count": 0, "list": []})
        # 매출 합계: 일별매출(daily_revenue) + 월 보고 매출(DirectorReport) 합산
        _total_revenue = float(daily["daily_revenue"] or 0) + float(rev["revenue_amount"] or 0)
        # 학생 수: 해당 원장에게 연결된 활성 학생 수 (실시간)
        _student_cnt = sum(1 for s in students if s.director_id == d.id and s.is_active)
        enriched_directors.append({
            "id": d.id,
            "name": d.name,
            "username": d.username,
            "email": d.email,
            "phone": d.phone,
            "is_active": d.is_active,
            "academy_type": d.academy_type or "",
            "region": d.region or "",
            "student_count": _student_cnt,
            "revenue_amount": rev["revenue_amount"],
            "revenue_count": rev["revenue_count"],
            "daily_revenue": daily["daily_revenue"],
            "daily_count": daily["daily_count"],
            "payment_total": _total_revenue,
            "total_payment": _total_revenue,
            "payment_completed": ps["completed"],
            "payment_pending": ps["pending"],
            "payment_count": daily["daily_count"] + rev["revenue_count"],
            "payment_list": ps["list"],
        })

    # 📋 통합 결제/매출 내역 — 수강생 결제 + 원장 매출(revenues) + 월간 보고(DirectorReport) 최근 20건
    rev_rows = (await db.execute(
        select(Revenue).where(Revenue.branch_id == branch_id).order_by(Revenue.created_at.desc()).limit(20)
    )).scalars().all()
    rep_rows = (await db.execute(
        select(DirectorReport).where(DirectorReport.branch_id == branch_id).order_by(DirectorReport.created_at.desc()).limit(20)
    )).scalars().all()
    _dname = {d.id: d.name for d in directors}
    unified_list = []
    for p in payments:
        unified_list.append({
            "id": p.id, "type": "payment", "amount": p.amount, "status": p.status,
            "paid_at": str(p.created_at) if p.created_at else None,
            "student_name": next((s.name for s in students if s.id == p.student_id), "수강생 결제"),
            "memo": "수강생 결제",
        })
    for r in rev_rows:
        unified_list.append({
            "id": r.id, "type": "revenue", "amount": float(r.amount or 0), "status": "completed",
            "paid_at": str(r.created_at) if r.created_at else None,
            "student_name": (_dname.get(r.director_id, "") + " 매출").strip(),
            "memo": r.course_name or "원장 매출",
        })
    for r in rep_rows:
        unified_list.append({
            "id": r.id, "type": "report", "amount": float(r.result_monthly_revenue or 0), "status": "completed",
            "paid_at": str(r.created_at) if r.created_at else None,
            "student_name": (_dname.get(r.director_id, "") + " 월보고").strip(),
            "memo": "월간 매출 보고",
        })
    unified_list.sort(key=lambda x: x["paid_at"] or "", reverse=True)
    unified_list = unified_list[:20]

    # 💰 결제 현황 통합 요약 — 수강생 결제(payments) + 원장 일별매출(revenues) + 월보고 매출(DirectorReport)
    #  실시간 집계: payments는 수강생 결제, revenues는 원장 매출, DirectorReport는 월간 보고 매출
    revenue_total = float(sum(v["daily_revenue"] for v in director_daily_revenues.values()) or 0)
    revenue_count = int(sum(v["daily_count"] for v in director_daily_revenues.values()) or 0)
    report_total = float(sum(v["revenue_amount"] for v in director_revenues.values()) or 0)
    report_count = int(sum(v["revenue_count"] for v in director_revenues.values()) or 0)
    total_amount = pay_amount + revenue_total + report_total
    total_count = int(pay_count) + revenue_count + report_count
    completed_count = int(pay_completed) + revenue_count + report_count
    pending_count = int(pay_pending)

    return ApiResponse(data={
        "branch": {
            "id": branch.id,
            "name": branch.name,
            "code": branch.code,
            "address": branch.address,
            "phone": branch.phone,
            "email": branch.email,
            "status": branch.status,
            "created_at": str(branch.created_at) if branch.created_at else None,
        },
        "directors": enriched_directors,
        "students": [{
            "id": s.id,
            "name": s.name,
            "username": s.username,
            "email": s.email,
            "phone": s.phone,
            "director_id": s.director_id,
            "is_active": s.is_active,
        } for s in students],
        "payments": {
            "list": unified_list,
            "total_count": total_count,
            "total_amount": total_amount,
            "completed_count": completed_count,
            "pending_count": pending_count,
            "payment_total": pay_amount,
            "revenue_total": revenue_total,
            "report_total": report_total,
        },
    })


@router.post("/branches")
async def create_branch(
    data: BranchCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 새 지사 생성 (옵션: 관리자 계정 함께 생성)"""
    existing = await db.execute(select(Branch).where(Branch.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 존재하는 지사 코드입니다.")

    branch = Branch(
        name=data.name,
        code=data.code,
        address=data.address,
        phone=data.phone,
        email=data.email,
        status="active",
        is_approved=True,
    )
    db.add(branch)
    await db.flush()

    # 관리자 계정 생성 (옵션)
    if data.admin_id:
        admin_user = await db.get(User, data.admin_id)
        if admin_user:
            admin_user.branch_id = branch.id

    await db.commit()
    await db.refresh(branch)
    return ApiResponse(data={
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
    }, message="지사가 생성되었습니다.")


@router.put("/branches/{branch_id}")
async def update_branch(
    branch_id: int,
    data: BranchUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 정보 수정"""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(branch, key, value)
    await db.commit()
    await db.refresh(branch)
    return ApiResponse(data={
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
    }, message="지사가 수정되었습니다.")


@router.delete("/branches/{branch_id}")
async def delete_branch(
    branch_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 삭제"""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")
    await db.delete(branch)
    await db.commit()
    return ApiResponse(message="지사가 삭제되었습니다.")


@router.post("/branches/{branch_id}/approve")
async def approve_branch(
    branch_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 승인 (is_approved=False → True)"""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")
    branch.is_approved = True
    branch.status = "active"
    await db.commit()
    await db.refresh(branch)
    return ApiResponse(data={"id": branch.id, "name": branch.name}, message="지사가 승인되었습니다.")


# ============================================================
# Section 3.5: Academies CRUD (학원 — 에듀케어 소속)
# ============================================================


@router.get("/academies")
async def get_academies(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    branch_id: Optional[int] = Query(None),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원 목록"""
    query = select(Academy).order_by(Academy.created_at.desc())
    base = select(func.count(Academy.id))
    if branch_id:
        query = query.where(Academy.branch_id == branch_id)
        base = base.where(Academy.branch_id == branch_id)
    total = (await db.execute(base)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    academies = result.scalars().all()
    return PaginatedResponse(
        data=[{
            "id": a.id,
            "name": a.name,
            "code": a.code,
            "branch_id": a.branch_id,
            "address": a.address,
            "phone": a.phone,
            "status": a.status,
            "director_name": a.director_name,
            "student_count": a.student_count,
            "created_at": str(a.created_at) if a.created_at else None,
        } for a in academies],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/academies/branch-stats")
async def get_academy_branch_stats(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — branch별 학원 통계 (학원 수, 학생 수, 강좌 수)"""
    result = await db.execute(
        select(
            Academy.branch_id,
            Branch.name.label("branch_name"),
            func.count(Academy.id).label("academy_count"),
            func.coalesce(func.sum(cast(Academy.student_count, Integer)), 0).label("total_students"),
        )
        .outerjoin(Branch, Academy.branch_id == Branch.id)
        .group_by(Academy.branch_id)
        .order_by(Branch.name)
    )
    rows = result.all()
    data = []
    for row in rows:
        # 각 branch/academy별 강좌 수
        course_count = 0
        acad_ids_subq = select(Academy.id).where(Academy.branch_id == row.branch_id)
        course_result = await db.execute(
            select(func.count(AcademyCourse.id)).where(AcademyCourse.academy_id.in_(acad_ids_subq))
        )
        course_count = course_result.scalar() or 0
        # ⚠️ SUM/COALESCE 결과가 DB 드라이버에 따라 문자열로 직렬화될 수 있다
        #    (student_count가 "38" 로 내려와 JS 에서 "0"+"38"="038" 문자열 연결이 되는 버그).
        #    JSON 응답이 항상 숫자가 되도록 int() 로 강제 변환한다.
        data.append({
            "branch_id": row.branch_id,
            "branch_name": row.branch_name or "알 수 없음",
            "academy_count": int(row.academy_count or 0),
            "student_count": int(row.total_students or 0),
            "course_count": int(course_count or 0),
        })
    return ApiResponse(data=data)


@router.post("/academies")
async def create_academy(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원 생성"""
    import secrets
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    academy = Academy(
        name=data.get("name", ""),
        code="#" + code,
        branch_id=data.get("branch_id"),
        address=data.get("address"),
        phone=data.get("phone"),
        status="active",
        director_name=data.get("director_name"),
    )
    db.add(academy)
    await db.commit()
    await db.refresh(academy)
    return ApiResponse(data={
        "id": academy.id, "name": academy.name, "code": academy.code,
        "branch_id": academy.branch_id, "status": academy.status,
    }, message="학원이 등록되었습니다.")


@router.put("/academies/{academy_id}")
async def update_academy(
    academy_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원 정보 수정"""
    academy = await db.get(Academy, academy_id)
    if not academy:
        raise HTTPException(status_code=404, detail="학원을 찾을 수 없습니다.")
    for field in ["name", "address", "phone", "status", "director_name", "branch_id"]:
        if field in data:
            setattr(academy, field, data[field])
    await db.commit()
    return ApiResponse(message="학원 정보가 수정되었습니다.")


@router.delete("/academies/{academy_id}")
async def delete_academy(
    academy_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원 삭제"""
    academy = await db.get(Academy, academy_id)
    if not academy:
        raise HTTPException(status_code=404, detail="학원을 찾을 수 없습니다.")
    # FK 제약으로 연결된 academy_courses 먼저 삭제
    await db.execute(
        delete(AcademyCourse).where(AcademyCourse.academy_id == academy_id)
    )
    await db.delete(academy)
    await db.commit()
    return ApiResponse(message="학원이 삭제되었습니다.")


# ============================================================
# 학원-강좌 연결 관리 (AcademyCourse)
# ============================================================


@router.get("/academy-courses")
async def get_academy_courses(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    academy_id: Optional[int] = Query(None),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원별 연결된 강좌 목록"""
    query = (
        select(AcademyCourse, Academy, Course)
        .join(Academy, Academy.id == AcademyCourse.academy_id)
        .join(Course, Course.id == AcademyCourse.course_id)
    )
    base = select(func.count(AcademyCourse.id))
    if academy_id:
        query = query.where(AcademyCourse.academy_id == academy_id)
        base = base.where(AcademyCourse.academy_id == academy_id)
    query = query.order_by(AcademyCourse.assigned_at.desc())
    
    total = (await db.execute(base)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    rows = result.all()
    
    return PaginatedResponse(
        data=[{
            "id": ac[0].id,
            "academy_id": ac[0].academy_id,
            "course_id": ac[0].course_id,
            "is_active": ac[0].is_active,
            "assigned_at": str(ac[0].assigned_at) if ac[0].assigned_at else None,
            "academy_name": ac[1].name,
            "course_name": ac[2].name,
            "course_category": ac[2].category,
        } for ac in rows],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.post("/academy-courses")
async def create_academy_course(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원에 강좌 연결"""
    academy_id = data.get("academy_id")
    course_id = data.get("course_id")
    
    if not academy_id or not course_id:
        raise HTTPException(status_code=400, detail="academy_id와 course_id는 필수입니다.")
    
    academy = await db.get(Academy, academy_id)
    if not academy:
        raise HTTPException(status_code=404, detail="학원을 찾을 수 없습니다.")
    
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")
    
    existing = await db.execute(
        select(AcademyCourse).where(
            AcademyCourse.academy_id == academy_id,
            AcademyCourse.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 연결된 강좌입니다.")
    
    ac = AcademyCourse(academy_id=academy_id, course_id=course_id)
    db.add(ac)
    await db.commit()
    await db.refresh(ac)
    return ApiResponse(data={
        "id": ac.id,
        "academy_id": ac.academy_id,
        "course_id": ac.course_id,
        "is_active": ac.is_active,
    }, message="강좌가 학원에 연결되었습니다.")


@router.delete("/academy-courses/{ac_id}")
async def delete_academy_course(
    ac_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 학원-강좌 연결 삭제"""
    ac = await db.get(AcademyCourse, ac_id)
    if not ac:
        raise HTTPException(status_code=404, detail="연결 정보를 찾을 수 없습니다.")
    await db.delete(ac)
    await db.commit()
    return ApiResponse(message="강좌 연결이 해제되었습니다.")


# ============================================================
# Section 4: Reports
# ============================================================


@router.get("/reports/daily")
async def get_daily_report(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 일간 리포트"""
    today = date.today()
    enrollments_today = (await db.execute(
        select(func.count(Enrollment.id)).where(
            func.date(Enrollment.enrolled_date) == today
        )
    )).scalar() or 0
    payments_today = (await db.execute(
        select(func.count(Payment.id)).where(
            func.date(Payment.created_at) == today,
            Payment.status == "completed",
        )
    )).scalar() or 0
    return ApiResponse(data={
        "enrollments_today": enrollments_today,
        "payments_today": payments_today,
        "date": str(today),
    })


@router.get("/reports/monthly")
async def get_monthly_report(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 월간 리포트"""
    today = date.today()
    first_of_month = today.replace(day=1)

    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "completed",
            Payment.paid_at >= first_of_month,
        )
    )
    revenue = float(revenue_result.scalar() or 0)

    enrollment_count = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.enrolled_date >= first_of_month
        )
    )).scalar() or 0

    return ApiResponse(data={
        "revenue": revenue,
        "enrollment_count": enrollment_count,
        "month": today.month,
        "year": today.year,
    })


@router.get("/director-reports")
async def get_consolidated_director_reports(
    year: int = Query(None),
    month: int = Query(None),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 에듀케어 보고서 통합 조회 (지사별 그룹)"""
    query = select(BranchReport)
    conditions = []
    if year:
        conditions.append(BranchReport.year == year)
    if month:
        conditions.append(BranchReport.month == month)
    if conditions:
        query = query.where(sa_and_(*conditions))
    query = query.order_by(BranchReport.branch_name, BranchReport.year.desc(), BranchReport.month.desc())

    result = await db.execute(query)
    reports = result.scalars().all()

    # Group by branch
    grouped = {}
    for r in reports:
        key = r.branch_name or f"branch_{r.branch_id}"
        if key not in grouped:
            grouped[key] = {
                "branch_name": r.branch_name,
                "branch_id": r.branch_id,
                "reports": [],
            }
        grouped[key]["reports"].append({
            "id": r.id,
            "director_name": r.manager_name,
            "year": r.year,
            "month": r.month,
            "status": r.status,
            "total_students": r.total_students,
            "new_registrations": r.new_registrations,
            "withdrawals": r.withdrawals,
            "retention_rate": r.retention_rate,
            "result_monthly_revenue": r.result_monthly_revenue,
            "result_new_students": r.result_new_students,
            "notes": r.notes,
            "contact": r.contact or "",
            "is_agreed": r.is_agreed or False,
            "created_at": str(r.created_at) if r.created_at else None,
            "updated_at": str(r.updated_at) if r.updated_at else None,
        })

    return ApiResponse(data=list(grouped.values()))


# ============================================================
# Section 5: Notices CRUD
# ============================================================


@router.get("/notices")
async def get_notices(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공지사항 목록"""
    query = select(Notice)
    count_query = select(func.count(Notice.id))
    if status:
        query = query.where(Notice.status == status)
        count_query = count_query.where(Notice.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Notice.is_pinned.desc(), Notice.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    notices = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "author": n.author,
            "status": n.status,
            "is_pinned": n.is_pinned,
            "is_popup": n.is_popup,
            "popup_start": n.popup_start,
            "popup_end": n.popup_end,
            "popup_targets": n.popup_targets,
            "publish_targets": n.publish_targets,
            "images": n.images,
            "view_count": n.view_count,
            "created_at": str(n.created_at) if n.created_at else None,
            "updated_at": str(n.updated_at) if n.updated_at else None,
        } for n in notices],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/notices/{notice_id}")
async def get_notice(
    notice_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공지사항 상세"""
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")

    # 조회수 증가
    notice.view_count = (notice.view_count or 0) + 1
    await db.commit()

    return ApiResponse(data={
        "id": notice.id,
        "title": notice.title,
        "content": notice.content,
        "author": notice.author,
        "status": notice.status,
        "is_pinned": notice.is_pinned,
        "is_popup": notice.is_popup,
        "popup_start": notice.popup_start,
        "popup_end": notice.popup_end,
        "popup_targets": notice.popup_targets,
        "publish_targets": notice.publish_targets,
        "images": notice.images,
        "view_count": notice.view_count,
        "created_at": str(notice.created_at) if notice.created_at else None,
        "updated_at": str(notice.updated_at) if notice.updated_at else None,
    })


@router.post("/notices")
async def create_notice(
    data: NoticeCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공지사항 작성"""
    notice = Notice(
        title=data.title,
        content=data.content or "",
        author=data.author or current_user.get("name", "관리자"),
        status=data.status or "published",
        is_pinned=data.is_pinned or False,
        is_popup=data.is_popup or False,
        popup_start=data.popup_start or "",
        popup_end=data.popup_end or "",
        popup_targets=data.popup_targets or "all",
        publish_targets=getattr(data, "publish_targets", "") or "",
        images=getattr(data, "images", "") or "",
    )
    db.add(notice)
    await db.commit()
    await db.refresh(notice)
    # 공지 발행 시 학생 알림 (notif_type='notice')
    try:
        if (notice.status or "published") == "published":
            from app.api.v1.push_notifications import notify_notice_published
            await notify_notice_published(db, notice.title, notice_id=notice.id)
    except Exception:
        pass
    return ApiResponse(data={
        "id": notice.id,
        "title": notice.title,
    }, message="공지사항이 등록되었습니다.")


@router.put("/notices/{notice_id}")
async def update_notice(
    notice_id: int,
    data: NoticeUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공지사항 수정"""
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(notice, key, value)
    await db.commit()
    await db.refresh(notice)
    return ApiResponse(data={
        "id": notice.id,
        "title": notice.title,
    }, message="공지사항이 수정되었습니다.")


@router.delete("/notices/{notice_id}")
async def delete_notice(
    notice_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공지사항 삭제"""
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    await db.delete(notice)
    await db.commit()
    return ApiResponse(message="공지사항이 삭제되었습니다.")


@router.post("/notices/upload-image")
async def upload_notice_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """본사 — 공지사항 이미지 업로드 (본문 삽입 / 첨부)"""
    import os
    import uuid as _uuid
    NOTICE_UPLOAD_DIR = "/app/uploads/notices"
    os.makedirs(NOTICE_UPLOAD_DIR, exist_ok=True)

    ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (jpg, png, gif, webp)")

    safe_name = f"notice_{current_user['id']}_{_uuid.uuid4().hex[:12]}.{ext}"
    content = await file.read()
    # 용량 제한 10MB
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 용량은 10MB 이하만 업로드할 수 있습니다.")
    with open(os.path.join(NOTICE_UPLOAD_DIR, safe_name), "wb") as f:
        f.write(content)

    return ApiResponse(data={
        "url": f"/uploads/notices/{safe_name}",
        "filename": safe_name,
    }, message="이미지가 업로드되었습니다.")


# ============================================================
# Section 6: Course Categories & Courses
# ============================================================


@router.get("/courses/categories")
async def get_course_categories(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 강좌 카테고리 목록 (강좌수/폴더수 포함)"""
    result = await db.execute(select(CatModel).order_by(CatModel.sort_order, CatModel.id))
    categories = result.scalars().all()

    # 강좌 수 집계
    course_count_q = await db.execute(
        select(Course.category, func.count(Course.id)).group_by(Course.category)
    )
    course_counts = dict(course_count_q.all())

    # 폴더 수 집계
    folder_count_q = await db.execute(
        select(CourseFolder.category, func.count(CourseFolder.id)).group_by(CourseFolder.category)
    )
    folder_counts = dict(folder_count_q.all())

    return ApiResponse(data=[{
        "id": c.id,
        "key": c.key,
        "name": c.name,
        "sort_order": c.sort_order,
        "color": c.color,
        "bg_color": c.bg_color,
        "is_active": c.is_active,
        "is_public": bool(c.is_public) if c.is_public is not None else True,
        "course_count": course_counts.get(c.key, 0),
        "folder_count": folder_counts.get(c.key, 0),
        "created_at": str(c.created_at) if c.created_at else None,
    } for c in categories])


@router.get("/courses")
async def get_all_courses(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    branch_id: int = None,
    status: str = None,
    year: int = None,
    month: int = None,
    category: str = None,
    folder_id: int = None,
    search: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 전체 강좌 목록
    - folder_id=None: 모든 강좌 (폴더 연결 여부 무관)
    - folder_id=특정ID: 해당 폴더의 강좌만 조회
    """
    conditions = []

    if folder_id is not None:
        # 특정 폴더에 연결된 강좌만
        subq = select(CourseFolderItem.course_id).where(
            CourseFolderItem.folder_id == folder_id
        ).subquery()
        conditions.append(Course.id.in_(select(subq.c.course_id)))
    else:
        # 전체: 폴더 연결 여부 무관 — 모든 강좌 표시
        pass

    if branch_id:
        conditions.append(Course.branch_id == branch_id)
    if status:
        conditions.append(Course.status == status)
    if year:
        conditions.append(func.extract("year", Course.created_at) == year)
    if month:
        conditions.append(func.extract("month", Course.created_at) == month)
    if category:
        conditions.append(Course.category == category)
    if search:
        conditions.append(Course.name.ilike(f"%{search}%"))

    query = select(Course)
    count_query = select(func.count())

    if conditions:
        query = query.where(sa_and_(*conditions))
        count_query = count_query.where(sa_and_(*conditions))

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Course.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    courses = result.scalars().all()

    # Branch names
    branch_ids = list(set(c.branch_id for c in courses if c.branch_id))
    branches_map = {}
    if branch_ids:
        br_result = await db.execute(select(Branch).where(Branch.id.in_(branch_ids)))
        for b in br_result.scalars().all():
            branches_map[b.id] = b.name

    # Material counts per course
    course_ids = [c.id for c in courses]
    mat_counts = {}
    if course_ids:
        mat_count_result = await db.execute(
            select(CourseMaterial.course_id, func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id.in_(course_ids), CourseMaterial.is_active == True)
            .group_by(CourseMaterial.course_id)
        )
        for cid, cnt in mat_count_result.all():
            mat_counts[cid] = cnt

    return PaginatedResponse(
        data=[{
            "id": c.id,
            "name": c.name,
            "title": c.name,
            "description": c.description,
            "subject": c.subject,
            "category": c.category,
            "price": float(c.price) if c.price else 0,
            "max_capacity": c.max_capacity,
            "instructor": c.instructor,
            "status": c.status,
            "branch_id": c.branch_id,
            "branch_name": branches_map.get(c.branch_id, ""),
            "material_count": mat_counts.get(c.id, 0),
            "created_at": str(c.created_at) if c.created_at else None,
        } for c in courses],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/courses/stats/months")
async def get_course_month_stats(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 월별 강좌 통계 (폴더 연결 강좌 제외)"""
    subq = select(CourseFolderItem.course_id).distinct().subquery()

    result = await db.execute(
        select(
            func.DATE_FORMAT(Course.created_at, '%Y-%m').label("month"),
            func.count(Course.id).label("count"),
        )
        .where(~Course.id.in_(select(subq.c.course_id)))
        .group_by("month")
        .order_by("month")
    )
    rows = result.all()
    return ApiResponse(data=[{"month": r.month, "count": r.count} for r in rows])


@router.get("/courses/{course_id}")
async def get_course_detail(
    course_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 강좌 상세 (학습 자료 목록 포함)"""
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    # Branch name
    branch_name = ""
    if course.branch_id:
        branch = await db.get(Branch, course.branch_id)
        if branch:
            branch_name = branch.name

    # Materials list
    from app.models import CourseMaterial
    materials_result = await db.execute(
        select(CourseMaterial).where(
            CourseMaterial.course_id == course_id
        ).order_by(CourseMaterial.sort_order)
    )
    materials = materials_result.scalars().all()

    return ApiResponse(data={
        "id": course.id,
        "name": course.name,
        "title": course.name,
        "description": course.description,
        "subject": course.subject,
        "category": course.category,
        "price": float(course.price) if course.price else 0,
        "max_capacity": course.max_capacity,
        "instructor": course.instructor,
        "status": course.status,
        "branch_id": course.branch_id,
        "branch_name": branch_name,
        "created_at": str(course.created_at) if course.created_at else None,
        "materials": [{
            "id": m.id,
            "title": m.title,
            "material_type": m.material_type,
            "file_url": m.file_url,
            "embed_url": m.embed_url,
            "sort_order": m.sort_order,
            "is_active": m.is_active,
        } for m in materials],
    })


@router.post("/courses")
async def create_course(
    data: CourseCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 강좌 생성 (title→name 매핑)"""
    course = Course(
        name=data.title,
        description=data.description or "",
        category=data.category,
        status=data.status or "active",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    # 폴더 연결
    if data.folder_id:
        link = CourseFolderItem(folder_id=data.folder_id, course_id=course.id)
        db.add(link)
        await db.commit()

    return ApiResponse(data={
        "id": course.id,
        "name": course.name,
    }, message="강좌가 생성되었습니다.")


@router.put("/courses/{course_id}")
async def update_course(
    course_id: int,
    data: CourseUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 강좌 수정"""
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    old_category = course.category
    old_folder_link = await db.execute(
        select(CourseFolderItem).where(CourseFolderItem.course_id == course_id)
    )
    old_folder = old_folder_link.scalar_one_or_none()
    old_folder_id = old_folder.folder_id if old_folder else None

    if data.title is not None:
        course.name = data.title
    if data.description is not None:
        course.description = data.description
    if data.category is not None:
        course.category = data.category
    if data.status is not None:
        course.status = data.status

    # 폴더 연결 변경
    if data.folder_id is not None:
        # 기존 연결 제거
        old_link = await db.execute(
            select(CourseFolderItem).where(CourseFolderItem.course_id == course_id)
        )
        old = old_link.scalar_one_or_none()
        if old:
            await db.delete(old)
        if data.folder_id:
            # 새 연결 추가
            link = CourseFolderItem(folder_id=data.folder_id, course_id=course.id)
            db.add(link)

    await db.commit()
    await db.refresh(course)

    return ApiResponse(data={
        "id": course.id,
        "name": course.name,
    }, message="강좌가 수정되었습니다.")


@router.put("/courses/{course_id}/blocks")
async def update_course_blocks(
    course_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "super_admin", "director")),
):
    """Update course content_blocks JSON. Accepts {'blocks': [...]}."""
    from app.models import Course
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")
    blocks = data.get("blocks")
    chapters = data.get("chapters")

    # ── url 유효성 검증 (video/image/embed) — 쓰레기 값("2314213") 재발 방지 ──
    import re as _re
    if blocks is not None and isinstance(blocks, list):
        for _i, _blk in enumerate(blocks):
            _bt = _blk.get("type", "") if isinstance(_blk, dict) else ""
            if _bt not in ("video", "image", "embed"):
                continue
            _u = (_blk.get("url") or "").strip() if isinstance(_blk, dict) else ""
            if not _u:
                continue  # 빈 값은 허용 (프론트 fallback)
            if _re.match(r"^(https?://|data:|blob:)", _u, _re.I):
                continue
            if _u.startswith(("/uploads/", "/files/")):
                continue
            raise HTTPException(
                status_code=400,
                detail=f"블록 {_i + 1}({_bt})의 url이 올바르지 않습니다: '{_u}'. /uploads/ 경로 또는 http(s):// 주소만 허용됩니다."
            )

    if blocks is not None:
        # chapters 배열이 함께 전달되면, 각 블록의 chapter 필드를
        # 챕터 배열의 id에 맞는 title로 동기화하고,
        # 챕터 순서도 함께 반영한다.
        if chapters is not None and isinstance(chapters, list):
            # 챕터 id -> title 매핑
            _title_map = {}
            _order_map = {}
            for _i, _ch in enumerate(chapters):
                if isinstance(_ch, dict):
                    _cid = _ch.get("id", "")
                    _title = _ch.get("title", "")
                    _title_map[_cid] = _title
                    _order_map[_title] = _i
        course.content_blocks = blocks
    if chapters is not None:
        # 챕터 배열 정보를 각 블록의 chapter 필드에 반영
        # (프론트에서 이미 블록의 chapter를 새 이름으로 변경했으므로
        #  여기서는 특별히 추가 처리가 필요없지만, 안전을 위해
        #  챕터 배열에 없는 물리적 chapter 값이 있으면 정리)
        if isinstance(course.content_blocks, list):
            _valid_titles = set()
            for _ch in (chapters or []):
                if isinstance(_ch, dict):
                    _valid_titles.add(_ch.get("title", ""))
            # 유효하지 않은(찌꺼기) chapter 값을 가진 블록을 '미분류'로 처리
            for _blk in course.content_blocks:
                if isinstance(_blk, dict) and _blk.get("chapter"):
                    _ch_val = _blk["chapter"]
                    if _ch_val not in _valid_titles:
                        _blk["chapter"] = None
    await db.commit()
    await db.refresh(course)
    # 실시간 알림: 해당 강좌 권한자(원장/학생)에게 자료 변경 푸시+SSE
    try:
        from app.api.v1.push_notifications import notify_course_updated
        await notify_course_updated(db, course_id, action="수정")
    except Exception:
        pass
    return {"status": "success", "data": {"id": course.id, "content_blocks": course.content_blocks}}


@router.get("/courses/{course_id}/blocks")
async def get_course_blocks(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin", "super_admin", "director", "student", "branch_admin")),
):
    from app.models import Course, LearningProgress
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")
    content_blocks = course.content_blocks or []
    if not isinstance(content_blocks, list):
        content_blocks = []
    # 챕터 정보: 블록들의 chapter 필드에서 고유한 챕터 이름 추출
    # _morder 순서로 정렬하여 챕터 순서가 블록 표시 순서를 따르도록 함
    chapters = []
    seen = set()
    # content_blocks를 _morder 순서로 정렬한 복사본 사용
    sorted_blocks = []
    for blk in content_blocks:
        if isinstance(blk, dict):
            sorted_blocks.append(blk)
    try:
        sorted_blocks.sort(key=lambda b: b.get("_morder") if isinstance(b.get("_morder"), (int, float)) else 100000)
    except Exception:
        pass
    for blk in sorted_blocks:
        if isinstance(blk, dict) and blk.get("chapter"):
            ch = blk["chapter"]
            if ch not in seen:
                seen.add(ch)
                chapters.append({"id": "ch" + str(len(chapters) + 1), "title": ch})
    data = {"id": course.id, "content_blocks": content_blocks, "chapters": chapters}

    # 학생이면 블록별 진행 상태(완료/진행률) 포함
    if current_user.get("role") == "student":
        prog_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.student_id == current_user["id"],
                LearningProgress.course_id == course_id,
                LearningProgress.material_id.is_(None),
            )
        )
        block_progress = {}
        for p in prog_result.scalars().all():
            block_progress[p.block_index] = {
                "is_completed": bool(p.is_completed),
                "progress_percent": p.progress_percent or 0,
            }
        data["block_progress"] = block_progress

    return {"status": "success", "data": data}


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: int,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 강좌 삭제 (최고관리자 전용)

    강좌를 참조하는 자식 레코드를 먼저 정리한 뒤 강좌를 삭제한다.
    (기존 코드는 자식 정리 없이 삭제를 시도해 FK 위반으로 500을 반환했음)
    """
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    # courses.id 를 FK로 참조하는 테이블 목록 (information_schema 기준 17개)
    _child_tables = [
        "enrollments",
        "academy_courses",
        "class_courses",
        "branch_course_allocations",
        "course_folder_items",
        "course_materials",
        "videos",
        "remote_classes",
        "ai_messages",
        "ai_faq_knowledge",
        "payments",
        "exams",
        "arduino_codes",
        "portfolios",
        "class_schedules",
        "learning_progress",
        "portfolio_templates",
    ]

    from sqlalchemy import text as _sql_text

    # 존재하는 테이블만 추려서 삭제 (없는 테이블 참조로 트랜잭션이 깨지지 않도록)
    _existing = (await db.execute(_sql_text(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE()"
    ))).scalars().all()
    _existing = set(_existing)

    # 자식 → 부모 순서로 정리 (CASCADE 미설정 테이블이 있으므로 명시 삭제)
    for _tbl in _child_tables:
        if _tbl not in _existing:
            continue
        await db.execute(
            _sql_text(f"DELETE FROM `{_tbl}` WHERE course_id = :cid"),
            {"cid": course_id},
        )

    # folder 연결(secondary) 정리 후 강좌 삭제
    await db.delete(course)
    await db.commit()
    return ApiResponse(message="강좌가 삭제되었습니다.")


# ============================================================
# Section 7: User Approval (super_admin only)
# ============================================================


@router.get("/pending-users")
async def get_pending_users(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 승인 대기 사용자 목록 (메인 DB 미승인 + pending.db)"""
    users = []

    # 메인 DB 미승인 사용자
    result = await db.execute(
        select(User).where(User.is_active == False).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    # pending.db의 승인 대기 사용자 (branch_admin/director)
    from app.pending_db import get_all_pending_users
    pending_users = get_all_pending_users(status="pending")
    for pu in pending_users:
        users.append(PendingUserProxy(pu))

    return ApiResponse(data=[{
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "email": getattr(u, 'email', getattr(u, 'username', '')),
        "phone": u.phone or "",
        "role": u.role,
        "branch_id": u.branch_id,
        "created_at": str(getattr(u, 'requested_at', getattr(u, 'created_at', ''))),
        "pending": getattr(u, 'pending', False),
    } for u in users])


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 사용자 승인 (메인 DB + pending.db)"""
    import secrets, string

    # 1) 먼저 pending.db에서 조회
    from app.pending_db import approve_pending_user
    pending_data = approve_pending_user(user_id)
    if pending_data:
        # pending.db -> 메인 DB users로 이동
        exist = await db.execute(select(User).where(
            (User.username == pending_data["username"]) | (User.email == pending_data["email"])
        ))
        if exist.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="이미 존재하는 사용자명 또는 이메일입니다.")

        user = User(
            username=pending_data["username"],
            email=pending_data["email"],
            password_hash=pending_data["password_hash"],
            name=pending_data["name"],
            phone=pending_data.get("phone", "") or "",
            role=pending_data["role"],
            branch_id=pending_data.get("branch_id"),
            director_id=pending_data.get("director_id"),
            registration_code=pending_data.get("registration_code", "") or "",
            is_active=True,
            approved_by=current_user["id"],
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

        # branch_admin 승인 시 branches 자동 생성/연결
        #   ★ 자동 매핑 원칙: 승인된 branch_admin 은 반드시 "활성(active)" 지사에 연결되어야 한다.
        #     - branch_id 가 없거나, 가리키는 Branch 가 없거나 inactive/미승인이면 새로 생성한다.
        #     - 이렇게 하면 이후 원장/학생이 등록코드로 가입할 때 그 branch_id 로 자동 매핑된다.
        if user.role == "branch_admin":
            linked = await db.get(Branch, user.branch_id) if user.branch_id else None
            if not linked or linked.status != "active" or not linked.is_approved:
                code = ''.join(secrets.choice(string.digits) for _ in range(6))
                new_branch = Branch(
                    name=user.name or user.username,
                    code="#" + code,
                    address=user.phone or "",
                    phone=user.phone or "",
                    status="active",
                    is_approved=True,
                )
                db.add(new_branch)
                await db.flush()
                user.branch_id = new_branch.id
            elif not linked.name or linked.name.strip().lower() == linked.code.strip().lower():
                # 자동 생성된 레거시 지사명이 코드처럼 보이면 승인된 계정명으로 정리
                linked.name = user.name or user.username

        # director(원장) 승인 시 academies 자동 생성
        if user.role == "director":
            acode = ''.join(secrets.choice(string.digits) for _ in range(6))
            academy = Academy(
                name=user.name or user.username,
                code="A" + acode,
                branch_id=user.branch_id,
                address=user.phone or "",
                phone=user.phone or "",
                status="active",
                director_name=user.name,
            )
            db.add(academy)

        # 소속 지사의 정산 설정 기본값 보장 (없으면 생성)
        await _ensure_branch_setting(db, user.branch_id)

        await db.commit()
        await db.refresh(user)
        return ApiResponse(data={
            "id": user.id, "username": user.username,
            "branch_id": user.branch_id,
        }, message="사용자가 승인되었습니다.")

    # 2) pending.db에 없으면 메인 DB에서 처리
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.is_active = True
    user.approved_by = current_user["id"]

    # branch_admin 승인 시 branches 자동 생성/연결 (활성 지사 보장)
    if user.role == "branch_admin":
        linked = await db.get(Branch, user.branch_id) if user.branch_id else None
        if not linked or linked.status != "active" or not linked.is_approved:
            code = ''.join(secrets.choice(string.digits) for _ in range(6))
            new_branch = Branch(
                name=user.name or user.username,
                code="#" + code,
                address=user.phone or "",
                phone=user.phone or "",
                status="active",
                is_approved=True,
            )
            db.add(new_branch)
            await db.flush()
            user.branch_id = new_branch.id

    # director(원장) 승인 시 academies 자동 생성
    if user.role == "director":
        acode = ''.join(secrets.choice(string.digits) for _ in range(6))
        academy = Academy(
            name=user.name or user.username,
            code="A" + acode,
            branch_id=user.branch_id,
            address=user.phone or "",
            phone=user.phone or "",
            status="active",
            director_name=user.name,
        )
        db.add(academy)

    # 소속 지사의 정산 설정 기본값 보장 (없으면 생성)
    await _ensure_branch_setting(db, user.branch_id)

    await db.commit()
    return ApiResponse(data={
        "id": user.id,
        "username": user.username,
        "branch_id": user.branch_id,
    }, message="사용자가 승인되었습니다.")


@router.delete("/users/{user_id}/reject")
async def reject_user(
    user_id: int,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 사용자 승인 거절/삭제 (메인 DB + pending.db)"""
    # 1) 먼저 pending.db에서 처리
    from app.pending_db import delete_pending_user
    try:
        delete_pending_user(user_id)
    except Exception:
        pass  # pending.db에 없으면 무시

    # 2) 메인 DB에서 처리
    user = await db.get(User, user_id)
    if user:
        await db.delete(user)
        await db.commit()

    return ApiResponse(message="사용자 승인이 거절되었습니다.")


# ============================================================
# Section 8: Categories CRUD
# ============================================================


# ===== 원장별 카테고리 권한 =====

@router.get("/directors/{director_id}/categories")
async def get_director_categories(
    director_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 특정 원장의 카테고리 권한 조회"""
    from app.models import DirectorCategory

    director = await db.get(User, director_id)
    if not director or director.role != "director":
        raise HTTPException(status_code=404, detail="원장을 찾을 수 없습니다.")

    result = await db.execute(
        select(DirectorCategory).where(DirectorCategory.director_id == director_id)
    )
    cats = result.scalars().all()

    # 연결된 개별 강좌 ID (AcademyCourse)
    course_ids = []
    if director.branch_id:
        academy = await db.execute(
            select(Academy).where(
                Academy.branch_id == director.branch_id,
                Academy.name == director.name,
            )
        )
        academy = academy.scalars().first()
        if academy:
            ac_q = await db.execute(
                select(AcademyCourse.course_id).where(
                    AcademyCourse.academy_id == academy.id,
                    AcademyCourse.is_active == True,
                )
            )
            course_ids = [r[0] for r in ac_q.all()]

    return ApiResponse(data={
        "director_id": director_id,
        "director_name": director.name,
        "course_ids": course_ids,
        "categories": [{
            "id": c.id,
            "category_id": c.category_id,
            "key": c.category_key,
            "display_name": c.display_name,
            "color": c.color,
            "is_active": c.is_active,
        } for c in cats],
    })


@router.put("/directors/{director_id}/categories")
async def set_director_categories(
    director_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 원장의 카테고리 권한 저장"""
    from app.models import DirectorCategory

    director = await db.get(User, director_id)
    if not director or director.role != "director":
        raise HTTPException(status_code=404, detail="원장을 찾을 수 없습니다.")

    categories = data.get("categories", [])
    course_ids = data.get("courses")  # optional: 강좌 단위 선택 (이중 선택)
    for cat in categories:
        key = cat.get("key")
        is_active = cat.get("is_active", True)

        existing = await db.execute(
            select(DirectorCategory).where(
                DirectorCategory.director_id == director_id,
                DirectorCategory.category_key == key,
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            existing_row.is_active = is_active
        else:
            dc = DirectorCategory(
                director_id=director_id,
                category_id=cat.get("category_id"),
                category_key=key,
                is_active=is_active,
            )
            db.add(dc)

    # 체크된 카테고리의 강좌들만 AcademyCourse에 연결/해제
    if director.branch_id:
        academy = await db.execute(
            select(Academy).where(
                Academy.branch_id == director.branch_id,
                Academy.name == director.name,
            )
        )
        academy = academy.scalars().first()
        # Academy가 없으면 자동 생성 (원장 계정 생성 시 자동 생성됨)
        if academy:
            active_keys = [c.get("key") for c in categories if c.get("is_active")]
            # 이미 연결된 강좌들
            existing_ac = await db.execute(
                select(AcademyCourse).where(AcademyCourse.academy_id == academy.id)
            )
            existing_map = {ac.course_id: ac for ac in existing_ac.scalars().all()}

            if course_ids is not None:
                # ── 강좌 단위 선택 모드 (이중 선택: 카테고리 + 개별 강좌) ──
                # 비활성 카테고리의 강좌는 아예 제외 — 프론트에서 잘못 보내와도 안전
                all_courses_for_cats = await db.execute(
                    select(Course.id).where(Course.status == "active")
                )
                all_course_ids = {row[0] for row in all_courses_for_cats.all()}

                # 활성 카테고리의 course_id 집합 생성 (없으면 전부 허용 대신 DB 기준 체크)
                if active_keys:
                    active_cat_courses = await db.execute(
                        select(Course.id).where(
                            Course.category.in_(active_keys),
                            Course.status == "active",
                        )
                    )
                    allowed_ids = {row[0] for row in active_cat_courses.all()}
                else:
                    # 활성 카테고리가 없으면 목록 자체를 제한 — 아무 강좌도 선택 불가
                    allowed_ids = set()

                selected = set()
                for cid in course_ids:
                    try:
                        cid_int = int(cid)
                    except (TypeError, ValueError):
                        continue
                    # 비활성 카테고리 강좌는 무시
                    if allowed_ids and cid_int not in allowed_ids:
                        continue
                    selected.add(cid_int)
                for cid in selected:
                    if cid not in existing_map:
                        db.add(AcademyCourse(academy_id=academy.id, course_id=cid))
                    else:
                        existing_map.pop(cid, None)
                # 선택되지 않은 기존 연결은 해제
                for ac in existing_map.values():
                    await db.delete(ac)
            elif active_keys:
                # 체크된 카테고리의 모든 활성 강좌 (기존 레거시 동작)
                courses = await db.execute(
                    select(Course).where(
                        Course.category.in_(active_keys),
                        Course.status == "active",
                    )
                )
                for course in courses.scalars().all():
                    if course.id not in existing_map:
                        ac = AcademyCourse(academy_id=academy.id, course_id=course.id)
                        db.add(ac)
                    else:
                        existing_map.pop(course.id, None)

                # 나머지(체크 안 된 카테고리 강좌)는 연결 해제
                for ac in existing_map.values():
                    await db.delete(ac)

    await db.commit()
    return ApiResponse(message="카테고리 권한이 저장되었습니다.")


@router.get("/categories")
async def list_categories(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 카테고리 목록"""
    result = await db.execute(select(CatModel).order_by(CatModel.sort_order, CatModel.id))
    categories = result.scalars().all()

    # Course count per category (활성 강좌만 — 목록과 동일 기준)
    course_count_q = await db.execute(
        select(Course.category, func.count(Course.id)).where(Course.status == "active").group_by(Course.category)
    )
    course_counts = dict(course_count_q.all())

    # Folder count per category
    folder_count_q = await db.execute(
        select(CourseFolder.category, func.count(CourseFolder.id)).group_by(CourseFolder.category)
    )
    folder_counts = dict(folder_count_q.all())

    # Active courses grouped by category (for course-level dual selection)
    course_q = await db.execute(
        select(Course.id, Course.name, Course.category).where(Course.status == "active")
    )
    courses_by_cat = {}
    for cid, cname, ccat in course_q.all():
        courses_by_cat.setdefault(ccat, []).append({"id": cid, "name": cname})

    return ApiResponse(data=[{
        "id": c.id,
        "key": c.key,
        "name": c.name,
        "sort_order": c.sort_order,
        "color": c.color,
        "bg_color": c.bg_color,
        "is_active": c.is_active,
        "is_public": bool(c.is_public) if c.is_public is not None else True,
        "course_count": course_counts.get(c.key, 0),
        "folder_count": folder_counts.get(c.key, 0),
        "courses": courses_by_cat.get(c.key, []),
        "created_at": str(c.created_at) if c.created_at else None,
    } for c in categories])


@router.post("/categories")
async def create_category(
    data: CategoryCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 카테고리 생성"""
    existing = await db.execute(select(CatModel).where(CatModel.key == data.key))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 존재하는 카테고리 키입니다.")

    cat = CatModel(
        key=data.key,
        name=data.name,
        sort_order=data.sort_order or 0,
        color=data.color,
        bg_color=data.bg_color,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return ApiResponse(data={
        "id": cat.id,
        "key": cat.key,
        "name": cat.name,
    }, message="카테고리가 생성되었습니다.")


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 카테고리 수정"""
    cat = await db.get(CatModel, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cat, key, value)
    await db.commit()
    await db.refresh(cat)
    return ApiResponse(data={
        "id": cat.id,
        "key": cat.key,
        "name": cat.name,
    }, message="카테고리가 수정되었습니다.")


@router.patch("/categories/{category_id}/public")
async def toggle_category_public(
    category_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 카테고리 전체공개 토글 (원장/에듀케어 매출·인원 사용 허용 여부)

    is_public=0 이면 원장·에듀케어의 매출/인원 집계에서 이 카테고리가 제외됩니다.
    """
    cat = await db.get(CatModel, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    is_public = bool(data.get("is_public", True))
    cat.is_public = is_public
    await db.commit()
    await db.refresh(cat)
    return ApiResponse(data={
        "id": cat.id,
        "key": cat.key,
        "name": cat.name,
        "is_public": bool(cat.is_public),
    }, message=("전체 공개로 설정했습니다." if is_public else "사용 중지로 설정했습니다."))


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 카테고리 삭제 (강좌 연결 시 방지, 폴더는 NULL 처리)"""
    cat = await db.get(CatModel, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    # 강좌 연결 확인
    linked_courses = await db.execute(
        select(func.count(Course.id)).where(Course.category == cat.key)
    )
    if linked_courses.scalar() > 0:
        raise HTTPException(status_code=400, detail=f"'{cat.name}' 카테고리에 연결된 강좌가 있어 삭제할 수 없습니다.")

    # 폴더 NULL 처리
    await db.execute(
        update(CourseFolder).where(CourseFolder.category == cat.key).values(category=None)
    )

    await db.delete(cat)
    await db.commit()
    return ApiResponse(message="카테고리가 삭제되었습니다.")


# ============================================================
# Section 9: Education Programs CRUD
# ============================================================


@router.get("/programs")
async def list_programs(
    category: str = None,
    status: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 교육 프로그램 목록 (차시수/할당수 포함)"""
    query = select(EducationProgram)
    conditions = []
    if category:
        conditions.append(EducationProgram.category == category)
    if status:
        conditions.append(EducationProgram.status == status)
    if conditions:
        query = query.where(sa_and_(*conditions))
    query = query.order_by(EducationProgram.created_at.desc())

    result = await db.execute(query)
    programs = result.scalars().all()

    # Chapter count per program
    program_ids = [p.id for p in programs]
    chapter_counts = {}
    assignment_counts = {}
    if program_ids:
        ch_q = await db.execute(
            select(ProgramChapter.program_id, func.count(ProgramChapter.id)).where(
                ProgramChapter.program_id.in_(program_ids)
            ).group_by(ProgramChapter.program_id)
        )
        chapter_counts = dict(ch_q.all())

        as_q = await db.execute(
            select(ProgramAssignment.program_id, func.count(ProgramAssignment.id)).where(
                ProgramAssignment.program_id.in_(program_ids)
            ).group_by(ProgramAssignment.program_id)
        )
        assignment_counts = dict(as_q.all())

    return ApiResponse(data=[{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "status": p.status,
        "chapter_count": chapter_counts.get(p.id, 0),
        "assignment_count": assignment_counts.get(p.id, 0),
        "created_at": str(p.created_at) if p.created_at else None,
    } for p in programs])


@router.post("/programs")
async def create_program(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 교육 프로그램 생성"""
    program = EducationProgram(
        name=data.get("name", ""),
        description=data.get("description", ""),
        category=data.get("category", "maker_coding"),
        status=data.get("status", "active"),
        created_by=current_user["id"],
    )
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return ApiResponse(data={
        "id": program.id,
        "name": program.name,
    }, message="교육 프로그램이 생성되었습니다.")


@router.put("/programs/{program_id}")
async def update_program(
    program_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 교육 프로그램 수정"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")

    for key in ("name", "description", "category", "status"):
        if key in data:
            setattr(program, key, data[key])
    await db.commit()
    await db.refresh(program)
    return ApiResponse(data={
        "id": program.id,
        "name": program.name,
    }, message="교육 프로그램이 수정되었습니다.")


@router.delete("/programs/{program_id}")
async def delete_program(
    program_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 교육 프로그램 삭제"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")
    await db.delete(program)
    await db.commit()
    return ApiResponse(message="교육 프로그램이 삭제되었습니다.")


# ============================================================
# Section 10: Program Chapters
# ============================================================


@router.get("/programs/{program_id}/chapters")
async def list_chapters(
    program_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 프로그램 차시 목록"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")

    result = await db.execute(
        select(ProgramChapter).where(ProgramChapter.program_id == program_id)
        .order_by(ProgramChapter.sort_order)
    )
    chapters = result.scalars().all()

    return ApiResponse(data=[{
        "id": ch.id,
        "program_id": ch.program_id,
        "title": ch.title,
        "sort_order": ch.sort_order,
        "description": ch.description,
        "ppt_file": ch.ppt_file,
        "ppt_url": ch.ppt_url,
        "video_url": ch.video_url,
        "video_title": ch.video_title,
        "duration_minutes": ch.duration_minutes,
        "status": ch.status,
        "created_at": str(ch.created_at) if ch.created_at else None,
    } for ch in chapters])


@router.post("/programs/{program_id}/chapters")
async def create_chapter(
    program_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 프로그램 차시 생성"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")

    chapter = ProgramChapter(
        program_id=program_id,
        title=data.get("title", ""),
        sort_order=data.get("sort_order", 0),
        description=data.get("description", ""),
        ppt_file=data.get("ppt_file", ""),
        ppt_url=data.get("ppt_url", ""),
        video_url=data.get("video_url", ""),
        video_title=data.get("video_title", ""),
        duration_minutes=data.get("duration_minutes", 0),
        status=data.get("status", "active"),
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return ApiResponse(data={
        "id": chapter.id,
        "title": chapter.title,
    }, message="차시가 생성되었습니다.")


@router.put("/programs/chapters/{chapter_id}")
async def update_chapter(
    chapter_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 차시 수정"""
    chapter = await db.get(ProgramChapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="차시를 찾을 수 없습니다.")

    for key in ("title", "sort_order", "description", "ppt_file", "ppt_url", "video_url", "video_title", "duration_minutes", "status"):
        if key in data:
            setattr(chapter, key, data[key])
    await db.commit()
    await db.refresh(chapter)
    return ApiResponse(data={
        "id": chapter.id,
        "title": chapter.title,
    }, message="차시가 수정되었습니다.")


@router.delete("/programs/chapters/{chapter_id}")
async def delete_chapter(
    chapter_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 차시 삭제"""
    chapter = await db.get(ProgramChapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="차시를 찾을 수 없습니다.")
    await db.delete(chapter)
    await db.commit()
    return ApiResponse(message="차시가 삭제되었습니다.")


# ============================================================
# Section 11: Program Assignments
# ============================================================


@router.get("/programs/{program_id}/assignments")
async def list_assignments(
    program_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 프로그램 할당 목록 (할당 대상명/지사명 포함)"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")

    result = await db.execute(
        select(ProgramAssignment).where(ProgramAssignment.program_id == program_id)
    )
    assignments = result.scalars().all()

    # Resolve assignee names
    assignee_data = []
    for a in assignments:
        assignee_name = ""
        branch_name = ""
        if a.assignee_type == "branch":
            branch = await db.get(Branch, a.assignee_id)
            if branch:
                assignee_name = branch.name
                branch_name = branch.name
        elif a.assignee_type == "director":
            director = await db.get(User, a.assignee_id)
            if director:
                assignee_name = director.name
                if director.branch_id:
                    br = await db.get(Branch, director.branch_id)
                    if br:
                        branch_name = br.name

        assignee_data.append({
            "id": a.id,
            "program_id": a.program_id,
            "assignee_type": a.assignee_type,
            "assignee_id": a.assignee_id,
            "assignee_name": assignee_name,
            "branch_name": branch_name,
            "assigned_by": a.assigned_by,
            "created_at": str(a.created_at) if a.created_at else None,
        })

    return ApiResponse(data=assignee_data)


@router.post("/programs/{program_id}/assignments")
async def create_assignment(
    program_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 프로그램 할당 생성 (다중 할당 지원)"""
    program = await db.get(EducationProgram, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="교육 프로그램을 찾을 수 없습니다.")

    assignee_type = data.get("assignee_type", "branch")
    assignee_ids = data.get("assignee_ids", [])

    if not assignee_ids:
        raise HTTPException(status_code=400, detail="할당 대상을 선택해주세요.")

    created_ids = []
    for aid in assignee_ids:
        # 중복 체크
        existing = await db.execute(
            select(ProgramAssignment).where(
                ProgramAssignment.program_id == program_id,
                ProgramAssignment.assignee_type == assignee_type,
                ProgramAssignment.assignee_id == aid,
            )
        )
        if existing.scalar_one_or_none():
            continue

        assignment = ProgramAssignment(
            program_id=program_id,
            assignee_type=assignee_type,
            assignee_id=aid,
            assigned_by=current_user["id"],
        )
        db.add(assignment)
        await db.flush()
        created_ids.append(assignment.id)

    await db.commit()
    return ApiResponse(data={
        "created_count": len(created_ids),
        "assignment_ids": created_ids,
    }, message=f"{len(created_ids)}개 할당이 생성되었습니다.")


@router.delete("/programs/{program_id}/assignments/{assignment_id}")
async def delete_assignment(
    program_id: int,
    assignment_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 프로그램 할당 삭제"""
    assignment = await db.get(ProgramAssignment, assignment_id)
    if not assignment or assignment.program_id != program_id:
        raise HTTPException(status_code=404, detail="할당을 찾을 수 없습니다.")
    await db.delete(assignment)
    await db.commit()
    return ApiResponse(message="할당이 삭제되었습니다.")


# ============================================================
# Section 11.5: Regions
# ============================================================


@router.get("/regions")
async def list_regions(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 등록된 지역 목록 (강좌 카테고리 권한 필터용)"""
    result = await db.execute(
        select(User.region)
        .where(User.role == "director", User.is_active == True, User.region.isnot(None), User.region != "")
        .distinct()
        .order_by(User.region)
    )
    regions = [r[0] for r in result.all() if r[0]]
    return ApiResponse(data=regions)


# ============================================================
# Section 12: Branch/Director Lists for Assignments
# ============================================================


@router.get("/directors/list")
async def list_directors_for_assign(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 원장 목록 (할당 드롭다운용)"""
    result = await db.execute(
        select(User.id, User.name, User.branch_id)
        .where(User.role == "director", User.is_active == True)
        .order_by(User.name)
    )
    directors = result.all()
    branch_ids = list(set(d.branch_id for d in directors if d.branch_id))
    branches_map = {}
    if branch_ids:
        br_result = await db.execute(select(Branch).where(Branch.id.in_(branch_ids)))
        for b in br_result.scalars().all():
            branches_map[b.id] = b.name

    return ApiResponse(data=[{
        "id": d.id,
        "name": d.name,
        "branch_id": d.branch_id,
        "branch_name": branches_map.get(d.branch_id, ""),
    } for d in directors])


# ============================================================
# Section 13: Contracts
# ============================================================


@router.get("/contracts")
async def list_contracts(
    contract_type: str = None,
    status: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 원장 계약 목록"""
    query = select(DirectorContract)
    conditions = []
    if contract_type:
        conditions.append(DirectorContract.contract_type == contract_type)
    if status:
        conditions.append(DirectorContract.status == status)
    if conditions:
        query = query.where(sa_and_(*conditions))
    query = query.order_by(DirectorContract.created_at.desc())

    result = await db.execute(query)
    contracts = result.scalars().all()

    # Resolve names
    director_ids = list(set(c.director_id for c in contracts))
    branch_ids = list(set(c.branch_id for c in contracts if c.branch_id))
    directors_map = {}
    branches_map = {}
    if director_ids:
        d_res = await db.execute(select(User).where(User.id.in_(director_ids)))
        for u in d_res.scalars().all():
            directors_map[u.id] = u.name
    if branch_ids:
        b_res = await db.execute(select(Branch).where(Branch.id.in_(branch_ids)))
        for b in b_res.scalars().all():
            branches_map[b.id] = b.name

    return ApiResponse(data=[{
        "id": c.id,
        "director_id": c.director_id,
        "director_name": directors_map.get(c.director_id, ""),
        "contract_type": c.contract_type,
        "branch_id": c.branch_id,
        "branch_name": branches_map.get(c.branch_id, ""),
        "contract_start": str(c.contract_start) if c.contract_start else None,
        "contract_end": str(c.contract_end) if c.contract_end else None,
        "monthly_fee": float(c.monthly_fee) if c.monthly_fee else 0,
        "royalty_rate": float(c.royalty_rate) if c.royalty_rate else 0,
        "status": c.status,
        "memo": c.memo,
        "created_at": str(c.created_at) if c.created_at else None,
    } for c in contracts])


@router.post("/contracts")
async def create_contract(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 원장 계약 생성"""
    contract = DirectorContract(
        director_id=data.get("director_id"),
        contract_type=data.get("contract_type", "direct"),
        branch_id=data.get("branch_id"),
        contract_start=datetime.strptime(data["contract_start"], "%Y-%m-%d").date() if data.get("contract_start") else None,
        contract_end=datetime.strptime(data["contract_end"], "%Y-%m-%d").date() if data.get("contract_end") else None,
        monthly_fee=data.get("monthly_fee", 0),
        royalty_rate=data.get("royalty_rate", 0),
        status=data.get("status", "active"),
        memo=data.get("memo", ""),
        created_by=current_user["id"],
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return ApiResponse(data={
        "id": contract.id,
    }, message="계약이 생성되었습니다.")


@router.put("/contracts/{contract_id}")
async def update_contract(
    contract_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 계약 수정"""
    contract = await db.get(DirectorContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="계약을 찾을 수 없습니다.")

    for key in ("director_id", "contract_type", "branch_id", "monthly_fee", "royalty_rate", "status", "memo"):
        if key in data:
            setattr(contract, key, data[key])
    if "contract_start" in data and data["contract_start"]:
        contract.contract_start = datetime.strptime(data["contract_start"], "%Y-%m-%d").date()
    if "contract_end" in data and data["contract_end"]:
        contract.contract_end = datetime.strptime(data["contract_end"], "%Y-%m-%d").date()

    await db.commit()
    await db.refresh(contract)
    return ApiResponse(data={
        "id": contract.id,
    }, message="계약이 수정되었습니다.")


@router.put("/contracts/{contract_id}/status")
async def update_contract_status(
    contract_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 계약 상태 변경 (active/expired/terminated)"""
    contract = await db.get(DirectorContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="계약을 찾을 수 없습니다.")

    new_status = data.get("status")
    if new_status not in ("active", "expired", "terminated"):
        raise HTTPException(status_code=400, detail="유효하지 않은 상태값입니다.")
    contract.status = new_status
    await db.commit()
    return ApiResponse(data={
        "id": contract.id,
        "status": contract.status,
    }, message="계약 상태가 변경되었습니다.")


@router.delete("/contracts/{contract_id}")
async def delete_contract(
    contract_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 계약 삭제"""
    contract = await db.get(DirectorContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="계약을 찾을 수 없습니다.")
    await db.delete(contract)
    await db.commit()
    return ApiResponse(data={"id": contract_id}, message="계약이 삭제되었습니다.")


@router.get("/contracts/stats")
async def contract_stats(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 계약 통계"""
    direct_count = (await db.execute(
        select(func.count(DirectorContract.id)).where(DirectorContract.contract_type == "direct")
    )).scalar() or 0
    franchise_count = (await db.execute(
        select(func.count(DirectorContract.id)).where(DirectorContract.contract_type == "franchise")
    )).scalar() or 0

    # Expiring soon: within 30 days
    today = date.today()
    thirty_days = today + timedelta(days=30)
    expiring_soon = (await db.execute(
        select(func.count(DirectorContract.id)).where(
            DirectorContract.contract_end >= today,
            DirectorContract.contract_end <= thirty_days,
            DirectorContract.status == "active",
        )
    )).scalar() or 0

    return ApiResponse(data={
        "direct_count": direct_count,
        "franchise_count": franchise_count,
        "expiring_soon_count": expiring_soon,
    })


# ============================================================
# Section 14: Branch Types
# ============================================================


@router.put("/branches/{branch_id}/type")
async def update_branch_type(
    branch_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 지사 유형 변경 (direct/franchise)"""
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    new_type = data.get("type")
    if new_type not in ("direct", "franchise"):
        raise HTTPException(status_code=400, detail="유효하지 않은 지사 유형입니다.")

    # Update the associated director contract type
    contract = await db.execute(
        select(DirectorContract).where(
            DirectorContract.branch_id == branch_id,
            DirectorContract.status == "active",
        )
    )
    contract_obj = contract.scalar_one_or_none()
    if contract_obj:
        contract_obj.contract_type = new_type
    else:
        # Create a default contract if none exists
        contract_obj = DirectorContract(
            director_id=0,
            contract_type=new_type,
            branch_id=branch_id,
            status="active",
            created_by=current_user["id"],
        )
        db.add(contract_obj)

    await db.commit()
    return ApiResponse(data={
        "branch_id": branch_id,
        "type": new_type,
    }, message="지사 유형이 변경되었습니다.")


# ============================================================
# Section 15: Folder Course Toggle (db BEFORE current_user)
# ============================================================


@router.put("/folders/{folder_id}/toggle")
async def toggle_folder_courses_hq(
    folder_id: int,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """본사 — 폴더 내 모든 강좌 일괄 활성화/비활성화 (자식 폴더 포함)"""
    folder = await db.get(CourseFolder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

    new_status = data.get("status", "active")
    if new_status not in ("active", "inactive"):
        raise HTTPException(status_code=400, detail="status는 'active' 또는 'inactive'만 가능합니다.")

    # 1) 이 폴더에 연결된 강좌 ID
    items = await db.execute(
        select(CourseFolderItem.course_id).where(CourseFolderItem.folder_id == folder_id)
    )
    course_ids = [row[0] for row in items.all()]

    # 2) 자식 폴더 처리
    children = await db.execute(
        select(CourseFolder).where(CourseFolder.parent_id == folder_id)
    )
    child_ids = [c.id for c in children.scalars().all()]
    for cid in child_ids:
        child_items = await db.execute(
            select(CourseFolderItem.course_id).where(CourseFolderItem.folder_id == cid)
        )
        course_ids.extend(row[0] for row in child_items.all())

    if not course_ids:
        return ApiResponse(message="이 폴더에 강좌가 없습니다.", data={"updated": 0})

    stmt = update(Course).where(Course.id.in_(course_ids)).values(status=new_status)
    await db.execute(stmt)
    await db.commit()

    return ApiResponse(
        message=f"폴더 내 {len(course_ids)}개 강좌가 {'활성화' if new_status == 'active' else '비활성화'}되었습니다.",
        data={"updated": len(course_ids), "status": new_status},
    )


# ============================================================
# Section 16: Payments Consolidated
# ============================================================


@router.get("/payments/consolidated")
async def get_consolidated_payments(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 에듀케어별 통합 결제 현황 (Payment + 원장 매출 DirectorReport)"""
    # 1) 모든 활성 에듀케어 조회
    branches_result = await db.execute(select(Branch).order_by(Branch.name))
    branches = branches_result.scalars().all()
    if not branches:
        return ApiResponse(data={"branches": []})

    branch_data = []
    for b in branches:
        # 1-a) Payment 집계 (수강 납부)
        pay_result = await db.execute(
            select(
                func.count(Payment.id),
                func.sum(Payment.amount),
            ).where(Payment.branch_id == b.id)
        )
        pay_count, pay_amount = pay_result.one()
        pay_count = pay_count or 0
        pay_amount = float(pay_amount or 0)

        # 상태별 Payment 카운트
        comp_result = await db.execute(
            select(func.count(Payment.id)).where(Payment.branch_id == b.id, Payment.status == "completed")
        )
        completed_count = comp_result.scalar() or 0
        pend_result = await db.execute(
            select(func.count(Payment.id)).where(Payment.branch_id == b.id, Payment.status == "pending")
        )
        pending_count = pend_result.scalar() or 0

        # 납부/미납 수강생 (Enrollment → Course → branch_id)
        enr_result = await db.execute(
            select(
                func.count(Enrollment.id),
                func.sum(case((Enrollment.payment_status == "paid", 1), else_=0)),
            ).where(
                Enrollment.course_id == Course.id,
                Course.branch_id == b.id,
                Enrollment.status == "active",
            )
        )
        enr_total, enr_paid = enr_result.one()
        enr_total = enr_total or 0
        enr_paid = enr_paid or 0
        enr_unpaid = enr_total - enr_paid

        # 1-b) DirectorReport 집계 (원장 매출 — submitted 상태)
        dr_result = await db.execute(
            select(
                func.count(DirectorReport.id),
                func.sum(DirectorReport.result_monthly_revenue),
            ).where(
                DirectorReport.branch_id == b.id,
                DirectorReport.status.in_(["submitted", "confirmed_by_branch", "confirmed_by_hq"]),
            )
        )
        dr_count, dr_amount = dr_result.one()
        dr_count = dr_count or 0
        dr_amount = float(dr_amount or 0)

        # 1-c) Revenue 집계 (원장 일별 매출)
        rev_result = await db.execute(
            select(
                func.count(Revenue.id),
                func.sum(Revenue.amount),
            ).where(Revenue.branch_id == b.id)
        )
        rev_count, rev_amount = rev_result.one()
        rev_count = rev_count or 0
        rev_amount = float(rev_amount or 0)

        # 1-d) Revenue 기준 월별 집계 (이번 달)
        from datetime import datetime
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_rev_result = await db.execute(
            select(
                func.count(Revenue.id),
                func.sum(Revenue.amount),
            ).where(
                Revenue.branch_id == b.id,
                Revenue.created_at >= month_start,
            )
        )
        m_rev_count, m_rev_amount = month_rev_result.one()
        m_rev_count = m_rev_count or 0
        m_rev_amount = float(m_rev_amount or 0)

        # Revenue 기준 본사 순이익 (수익률 = 기본 5%)
        branch_setting_result = await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == b.id)
        )
        bs = branch_setting_result.scalar_one_or_none()
        profit_rate = 5
        if bs and bs.payment_config:
            pr = bs.payment_config.get("profit_rate")
            if pr is not None:
                profit_rate = int(pr)
        hq_profit = round(m_rev_amount * profit_rate / 100)

        branch_data.append({
            "branch_id": b.id,
            "branch_name": b.name or b.code or f"에듀케어 {b.id}",
            "payment_count": pay_count,
            "completed_count": completed_count,
            "pending_count": pending_count,
            "total_amount": pay_amount + dr_amount,
            "revenue_amount": rev_amount,
            "revenue_count": rev_count,
            "month_revenue_amount": m_rev_amount,
            "month_revenue_count": m_rev_count,
            "profit_rate": profit_rate,
            "hq_profit": hq_profit,
            "enrollment_paid": enr_paid,
            "enrollment_unpaid": enr_unpaid,
        })

    return ApiResponse(data={"branches": branch_data})


# ============================================================
# Section 17-A: HQ Overview — 본사 정산 통합 현황 (결제관리 페이지)
# ============================================================
@router.get("/payments/hq-overview")
async def get_payments_hq_overview(
    period_ym: Optional[str] = Query(None, description="YYYY-MM (미지정 시 이번 달)"),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 결제관리 — 에듀케어별 정산 통합 현황.

    반환:
      - summary : 전체 요약 (총 학생수 + 교육과정별 인원 + 총 정산금액)
      - branches: 에듀케어별
          · students        : 소속 학생수
          · categories      : 강좌 카테고리별 수강 인원 (동적)
          · director_revenue: 소속 원장 전체 매출 (해당 월)
          · royalty_due     : 본사가 받아야 할 로열티 (과세표준 × 45%)
          · royalty_paid    : 승인 완료된 로열티
          · royalty_unpaid  : 미수금 (로열티 − 승인분)
          · net_deposit     : 본사가 에듀케어에 입금해야 할 금액
    """
    # ---- 정산 기준 (branch.py 와 동일 공식) ----
    VAT_FACTOR = 1.1            # 부가세 10% 제외 → 과세표준 = 매출 / 1.1
    HQ_ROYALTY_RATE = 45.0      # 본사 로열티율 %
    PROFIT_RATE = 7.0           # 에듀케어 순수익율 % (과세표준 기준)
    INCOME_TAX_RATE = 3.3       # 순수익 공제율 % (기본)

    # ---- 기간 ----
    now = datetime.utcnow()
    ym = (period_ym or f"{now.year}-{now.month:02d}").strip()
    try:
        y_str, m_str = ym.split("-")
        ym_year, ym_month = int(y_str), int(m_str)
    except Exception:
        ym_year, ym_month = now.year, now.month
        ym = f"{ym_year}-{ym_month:02d}"

    # ---- 활성 에듀케어 ----
    b_res = await db.execute(select(Branch).where(Branch.status == "active").order_by(Branch.name))
    branches = b_res.scalars().all()

    # ---- 카테고리 표시명 맵 (categories 테이블이 authority) ----
    cat_res = await db.execute(select(CatModel))
    cat_name_map = {}
    cat_public = {}
    for c in cat_res.scalars().all():
        cat_name_map[(c.key or "").strip()] = c.name or c.key
        cat_public[(c.key or "").strip()] = (True if c.is_public is None else bool(c.is_public))

    def _cat_label(key: str) -> str:
        k = (key or "").strip()
        if k in cat_name_map and cat_name_map[k]:
            return cat_name_map[k]
        return k.replace("_", " ").title() if k else "기타"

    branch_out = []
    global_students = set()                    # 전체 학생 (중복 제거)
    global_cat_students = {}                   # 교육과정별 전체 학생 set

    for b in branches:
        # ---- 소속 원장 ----
        d_res = await db.execute(
            select(User.id).where(User.role == "director", User.branch_id == b.id)
        )
        director_ids = [x for (x,) in d_res.all() if x]

        # ---- 소속 학생 (branch_id 직접 + 소속 원장의 반 학생) ----
        student_ids = set()
        s_res = await db.execute(
            select(User.id).where(
                User.role == "student", User.is_active == True, User.branch_id == b.id
            )
        )
        student_ids.update(x for (x,) in s_res.all() if x)

        class_ids = []
        if director_ids:
            c_res = await db.execute(
                select(SchoolClass.id).where(SchoolClass.director_id.in_(director_ids))
            )
            class_ids = [x for (x,) in c_res.all() if x]
        if class_ids:
            cs_res = await db.execute(
                select(ClassStudent.student_id).where(
                    ClassStudent.class_id.in_(class_ids), ClassStudent.status == "active"
                )
            )
            student_ids.update(x for (x,) in cs_res.all() if x)
        student_ids = {s for s in student_ids if s}

        # ---- 강좌 카테고리별 수강 인원 (개인 enrollment + 반 수강 union) ----
        #  수강 경로가 두 가지다:
        #   (a) enrollments : 학생이 직접 수강 신청한 강좌 (status='active')
        #   (b) class_courses: 학생이 소속된 '반'에 연결된 강좌 — 반 배정만으로 수강
        #  DB 실태상 개인 enrollment 가 cancelled 로 남아 있어도 반으로 듣는 경우가
        #  많으므로(예: gkrtod1 → Start-Kit반 → 피지컬 AI 지도사) 두 경로를 union 한다.
        cat_students = {}
        if student_ids:
            e_res = await db.execute(
                select(Course.category, Enrollment.student_id)
                .join(Course, Course.id == Enrollment.course_id)
                .where(
                    Enrollment.student_id.in_(list(student_ids)),
                    Enrollment.status == "active",
                )
            )
            for cat, sid in e_res.all():
                k = (cat or "").strip() or "uncategorized"
                cat_students.setdefault(k, set()).add(sid)

        # (b) 반(class_courses) 경로 — 이 에듀케어 소속 반의 강좌를 수강하는 학생
        if class_ids:
            cc_res = await db.execute(
                select(Course.category, ClassStudent.student_id)
                .select_from(ClassStudent)
                .join(ClassCourse, ClassCourse.class_id == ClassStudent.class_id)
                .join(Course, Course.id == ClassCourse.course_id)
                .where(ClassStudent.class_id.in_(class_ids), ClassStudent.status == "active")
            )
            for cat, sid in cc_res.all():
                k = (cat or "").strip() or "uncategorized"
                cat_students.setdefault(k, set()).add(sid)

        # ※ 강좌관리에서 체크 해제(is_public=0)된 카테고리는 '사용 중지' 상태이므로
        #    본사 정산 화면을 포함해 어디에도 집계·표시하지 않는다.
        #    (강좌관리 체크박스 = 카테고리 사용 여부 마스터 스위치)
        categories = [
            {"key": k, "label": _cat_label(k), "count": len(v)}
            for k, v in cat_students.items()
            if cat_public.get(k, True)
        ]
        categories.sort(key=lambda c: (-c["count"], c["label"]))

        # 전체 집계 누적 (공개 카테고리만)
        #  총 학생수도 '공개 카테고리를 수강 중인' 학생만 센다 → 강좌관리 체크 해제된
        #  과목만 듣는 학생은 어디에도 잡히지 않도록 일관성 유지.
        for k, v in cat_students.items():
            if cat_public.get(k, True):
                global_students.update(v)
                global_cat_students.setdefault(k, set()).update(v)

        # ---- 소속 원장 전체 매출 (해당 월, tuition_payments 납부 기준) ----
        rev_amount = 0.0
        if director_ids:
            tp_res = await db.execute(
                select(func.sum(TuitionPayment.amount)).where(
                    TuitionPayment.director_id.in_(director_ids),
                    TuitionPayment.period_ym == ym,
                    TuitionPayment.paid == True,
                )
            )
            rev_amount = float(tp_res.scalar() or 0)
            # 납부 기록이 없으면 기대매출(전체)로 대체 표기용
            if rev_amount == 0:
                tp_all = await db.execute(
                    select(func.sum(TuitionPayment.amount)).where(
                        TuitionPayment.director_id.in_(director_ids),
                        TuitionPayment.period_ym == ym,
                    )
                )
                rev_amount = float(tp_all.scalar() or 0)

        # ---- 정산 계산 (branch.py 공식 동일) ----
        tax_base = round(rev_amount / VAT_FACTOR)
        royalty_due = round(tax_base * HQ_ROYALTY_RATE / 100)
        edu_profit = round(tax_base * PROFIT_RATE / 100)

        # 에듀케어별 순수익 공제율 (BranchSetting)
        it_rate = INCOME_TAX_RATE
        bs_res = await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == b.id)
        )
        bs = bs_res.scalar_one_or_none()
        if bs and bs.payment_config:
            try:
                it = bs.payment_config.get("income_tax_rate")
                if it is not None:
                    it_rate = float(it)
            except Exception:
                pass
        income_tax = round(edu_profit * it_rate / 100)
        net_deposit = edu_profit - income_tax

        # ---- 로열티 승인/미수금 (revenue_approvals) ----
        royalty_paid = 0.0
        if director_ids:
            ap_res = await db.execute(
                select(func.sum(RevenueApproval.total_amount)).where(
                    RevenueApproval.director_id.in_(director_ids),
                    RevenueApproval.status == "approved",
                    RevenueApproval.period_start >= date(ym_year, ym_month, 1),
                )
            )
            royalty_paid = float(ap_res.scalar() or 0)
        royalty_paid = min(royalty_paid, royalty_due) if royalty_due else 0.0
        royalty_unpaid = max(0.0, royalty_due - royalty_paid)

        branch_out.append({
            "branch_id": b.id,
            "branch_name": b.name or b.code or f"에듀케어 {b.id}",
            "branch_code": b.code or "",
            "director_count": len(director_ids),
            "student_count": len(student_ids),
            "categories": categories,
            "director_revenue": round(rev_amount),
            "tax_base": tax_base,
            "royalty_due": royalty_due,
            "royalty_paid": round(royalty_paid),
            "royalty_unpaid": round(royalty_unpaid),
            "edu_profit": edu_profit,
            "income_tax_rate": it_rate,
            "income_tax": income_tax,
            "net_deposit": net_deposit,
        })

    # ---- 전체 요약 ----
    total_royalty_due = sum(x["royalty_due"] for x in branch_out)
    total_royalty_paid = sum(x["royalty_paid"] for x in branch_out)
    total_royalty_unpaid = sum(x["royalty_unpaid"] for x in branch_out)
    total_net_deposit = sum(x["net_deposit"] for x in branch_out)
    total_revenue = sum(x["director_revenue"] for x in branch_out)

    global_categories = [
        {"key": k, "label": _cat_label(k), "count": len(v)}
        for k, v in global_cat_students.items()
    ]
    global_categories.sort(key=lambda c: (-c["count"], c["label"]))

    return ApiResponse(data={
        "period_ym": ym,
        "summary": {
            "branch_count": len(branch_out),
            "total_students": len(global_students),
            "categories": global_categories,
            "total_director_revenue": round(total_revenue),
            "total_royalty_due": total_royalty_due,
            "total_royalty_paid": total_royalty_paid,
            "total_royalty_unpaid": total_royalty_unpaid,
            "total_net_deposit": total_net_deposit,
        },
        "branches": branch_out,
        "rates": {
            "vat_rate": 10,
            "hq_royalty_rate": HQ_ROYALTY_RATE,
            "profit_rate": PROFIT_RATE,
            "income_tax_rate": INCOME_TAX_RATE,
        },
    })


# ============================================================
# Section 17: Revenue Approvals
# ============================================================


@router.get("/revenue-approvals")
async def get_revenue_approvals(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 수익금 승인 요청 목록"""
    query = select(RevenueApproval)
    count_query = select(func.count(RevenueApproval.id))
    conditions = []
    if status:
        conditions.append(RevenueApproval.status == status)
    if conditions:
        query = query.where(sa_and_(*conditions))
        count_query = count_query.where(sa_and_(*conditions))

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(RevenueApproval.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    approvals = result.scalars().all()

    # Resolve names
    director_ids = list(set(a.director_id for a in approvals))
    branch_ids = list(set(a.branch_id for a in approvals if a.branch_id))
    directors_map = {}
    branches_map = {}
    if director_ids:
        d_res = await db.execute(select(User).where(User.id.in_(director_ids)))
        for u in d_res.scalars().all():
            directors_map[u.id] = u.name
    if branch_ids:
        b_res = await db.execute(select(Branch).where(Branch.id.in_(branch_ids)))
        for b in b_res.scalars().all():
            branches_map[b.id] = b.name

    return PaginatedResponse(
        data=[{
            "id": a.id,
            "director_id": a.director_id,
            "director_name": directors_map.get(a.director_id, ""),
            "branch_id": a.branch_id,
            "branch_name": branches_map.get(a.branch_id, ""),
            "period_start": str(a.period_start) if a.period_start else None,
            "period_end": str(a.period_end) if a.period_end else None,
            "total_amount": float(a.total_amount or 0),
            "hq_account_number": a.hq_account_number,
            "status": a.status,
            "director_note": a.director_note,
            "approved_at": str(a.approved_at) if a.approved_at else None,
            "paid_at": str(a.paid_at) if a.paid_at else None,
            "created_at": str(a.created_at) if a.created_at else None,
        } for a in approvals],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.post("/revenue-approvals/{approval_id}/approve")
async def approve_revenue(
    approval_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 수익금 승인"""
    approval = await db.get(RevenueApproval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="승인 요청을 찾을 수 없습니다.")

    approval.status = "approved"
    approval.approved_at = datetime.now(timezone.utc)
    approval.approved_by = current_user["id"]
    await db.commit()
    return ApiResponse(data={
        "id": approval.id,
        "status": approval.status,
    }, message="수익금이 승인되었습니다.")


@router.post("/revenue-approvals/{approval_id}/reject")
async def reject_revenue(
    approval_id: int,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 수익금 반려"""
    approval = await db.get(RevenueApproval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="승인 요청을 찾을 수 없습니다.")

    approval.status = "rejected"
    _prev_note = approval.director_note or ""
    _reason = (data.get("reason") or "").strip()
    if _reason:
        approval.director_note = f"{_prev_note} | 반려사유: {_reason}" if _prev_note else _reason
    await db.commit()
    return ApiResponse(data={
        "id": approval.id,
        "status": approval.status,
    }, message="수익금이 반려되었습니다.")


# ============================================================
# Section 18: Settings (if exists in frontend)
# ============================================================


@router.get("/settings")
async def get_settings(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 설정 조회"""
    return ApiResponse(data={
        "headquarters_name": "누비다플랫폼 본사",
        "settings": {},
    })


# ============================================================
# Section 19: SEO 설정 (네이버/구글 서치어드바이저)
# ============================================================

@router.get("/seo-settings")
async def get_seo_settings(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — SEO 설정 조회 (네이버/구글 서치어드바이저 코드)"""
    from app.models import AppSetting
    result = await db.execute(select(AppSetting).where(AppSetting.key == "seo"))
    row = result.scalar_one_or_none()
    data = row.value if row and row.value else {"naver_search_code": "", "google_search_code": ""}
    return ApiResponse(data=data)


@router.put("/seo-settings")
async def set_seo_settings(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — SEO 설정 저장 (대표자 super_admin 전용)"""
    from app.models import AppSetting
    import re
    naver = re.sub(r'[<>"\']', '', (data.get("naver_search_code") or "").strip())
    google = re.sub(r'[<>"\']', '', (data.get("google_search_code") or "").strip())
    result = await db.execute(select(AppSetting).where(AppSetting.key == "seo"))
    row = result.scalar_one_or_none()
    if row:
        row.value = {"naver_search_code": naver, "google_search_code": google}
    else:
        db.add(AppSetting(key="seo", value={"naver_search_code": naver, "google_search_code": google}))
    await db.commit()
    return ApiResponse(message="SEO 설정이 저장되었습니다.")


# ============================================================
# Section 20: 누비다머신 블루투스 설정 (아두이노 전송 접두어)
# ============================================================

_ML_PRESET_ACTIONS = {"led_on", "led_off", "servo", "buzzer", "none"}
_ML_DEFAULT_PRESETS = [{"action": "none", "target_value": ""} for _ in range(10)]


def _normalize_ml_presets(presets):
    """본사 동작 프리셋 정규화 — 항상 10개 (클래스 1~10번 = index 0~9)."""
    if not isinstance(presets, list):
        return _ML_DEFAULT_PRESETS
    out = []
    for i in range(10):
        p = presets[i] if i < len(presets) else {}
        if not isinstance(p, dict):
            p = {}
        action = str(p.get("action") or "none").strip()
        tv = str(p.get("target_value") or "").strip()[:60]
        if action not in _ML_PRESET_ACTIONS:
            # 무효 action → none 처리 시 target_value도 초기화 (의도치 않은 페이로드 차단)
            action = "none"
            tv = ""
        out.append({"action": action, "target_value": tv})
    return out


@router.get("/ml-bt-settings")
async def get_ml_bt_settings(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 누비다머신 연동 설정 조회 (블루투스 접두어 + 클래스별 동작 프리셋)"""
    from app.models import AppSetting
    result = await db.execute(select(AppSetting).where(AppSetting.key == "ml_bt"))
    row = result.scalar_one_or_none()
    data = {"bt_prefix": "NubidaAi", "presets": _ML_DEFAULT_PRESETS}
    if row and row.value:
        try:
            raw = row.value if isinstance(row.value, dict) else json.loads(row.value)
            if isinstance(raw, dict):
                data["bt_prefix"] = raw.get("bt_prefix") or "NubidaAi"
                data["presets"] = _normalize_ml_presets(raw.get("presets"))
        except Exception:
            pass
    return ApiResponse(data=data)


@router.put("/ml-bt-settings")
async def set_ml_bt_settings(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 누비다머신 연동 설정 저장 (접두어 + 프리셋, 대표자 super_admin 전용)"""
    from app.models import AppSetting
    import re
    prefix = re.sub(r"[^A-Za-z0-9가-힣]", "", (data.get("bt_prefix") or "NubidaAi").strip())[:20] or "NubidaAi"
    presets = _normalize_ml_presets(data.get("presets"))
    result = await db.execute(select(AppSetting).where(AppSetting.key == "ml_bt"))
    row = result.scalar_one_or_none()
    if row:
        prev = row.value
        prev = prev if isinstance(prev, dict) else {}
        row.value = {**(prev or {}), "bt_prefix": prefix, "presets": presets}
    else:
        db.add(AppSetting(key="ml_bt", value={"bt_prefix": prefix, "presets": presets}))
    await db.commit()
    return ApiResponse(message="누비다머신 연동 설정이 저장되었습니다.")


# ============================================================
# Section 21: 공개사이트 콘텐츠 (네비/푸터/상담정보/페이지 본문)
# ============================================================

@router.get("/site-content")
async def get_hq_site_content(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공개사이트 콘텐츠 조회 (없으면 기본 시드 삽입 후 반환)"""
    from app.services.site_content import get_site_content
    data = await get_site_content(db)
    return ApiResponse(data=data)


@router.put("/site-content")
async def set_hq_site_content(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공개사이트 콘텐츠 저장 (HTML/스크립트 자동 제거)"""
    from app.services.site_content import save_site_content
    await save_site_content(db, data)
    return ApiResponse(message="공개사이트 콘텐츠가 저장되었습니다.")


@router.get("/site-content/pages/{slug}")
async def get_hq_site_page(
    slug: str,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공개페이지 단일 조회 (위지윅 에디터) — blocks 형식 보장"""
    from app.services.site_content import get_site_page
    page = await get_site_page(db, slug)
    if page is None:
        raise HTTPException(404, "페이지를 찾을 수 없습니다.")
    return ApiResponse(data=page)


@router.put("/site-content/pages/{slug}")
async def set_hq_site_page(
    slug: str,
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공개페이지 단일 저장 (위지윅 에디터) — nav/footer/contact 등 다른 영역 보존"""
    from app.services.site_content import save_site_page
    npg = await save_site_page(db, slug, data)
    return ApiResponse(data={"slug": slug, "blocks": len(npg.get("blocks") or [])}, message="페이지가 저장되었습니다.")


@router.post("/site-content/pages")
async def create_hq_site_page(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 새 공개페이지 생성 (DB 시드 + 실제 HTML 파일 자동 생성)
    - slug 검증(영문 소문자·숫자·하이픈), 중복·예약 주소·정적 파일 충돌 시 4xx
    - file_created=False 이면 기존 동적 HTML에 DB 연결만 수행됨"""
    from app.services.site_content import create_site_page
    slug = str(data.get("slug") or "").strip().lower()
    title = str(data.get("title") or "").strip()
    desc = str(data.get("desc") or "").strip()
    try:
        info = await create_site_page(db, slug, title, desc)
    except ValueError as e:
        msg = str(e)
        status = 409 if msg.startswith(("이미", "사용할 수 없는", "사용 중인")) else 400
        raise HTTPException(status, msg)
    msg = "새 페이지가 생성되었습니다. [✎ 에디터 열기]로 본문을 편집하세요."
    if not info.get("file_created"):
        msg = "페이지 본문이 연결되었습니다."
    return ApiResponse(data=info, message=msg)


@router.delete("/site-content/pages/{slug}")
async def delete_hq_site_page(
    slug: str,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 공개페이지 삭제 (보호 페이지 제외 / 자동생성 HTML 삭제 / 네비·푸터 링크 정리)"""
    from app.services.site_content import delete_site_page
    try:
        info = await delete_site_page(db, slug)
    except ValueError as e:
        raise HTTPException(400, str(e))
    msg = "페이지가 삭제되었습니다."
    if info.get("removed_links"):
        msg += f" 연결된 네비/푸터 링크 {info['removed_links']}개도 함께 제거했습니다."
    return ApiResponse(data=info, message=msg)


@router.post("/site-content/upload")
async def upload_site_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """본사 — 공개페이지 에디터 이미지 업로드 → /uploads/site/ 저장, URL 반환"""
    import os
    import uuid

    import aiofiles

    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(400, "JPG, PNG, GIF, WEBP만 업로드 가능합니다.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "파일 크기는 10MB 이하여야 합니다.")

    # static /uploads 마운트 루트(UPLOADS_DIR=backend/uploads) 기준 site/ 하위 저장
    site_dir = os.path.join(settings.UPLOADS_DIR, "site")
    os.makedirs(site_dir, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    if ext.lower() not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(site_dir, filename)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)
    return ApiResponse(data={"url": f"/uploads/site/{filename}"}, message="이미지가 업로드되었습니다.")

@router.post("/settings")
async def save_settings(
    data: dict = Body(...),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 — 설정 저장"""
    return ApiResponse(data=data, message="설정이 저장되었습니다.")
