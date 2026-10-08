"""
🏫 메이커 코딩 교육 시스템 — 원장(Admin) API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.core.database import get_db
from app.models import (
    MakerCourse, MakerStudent, MakerEnrollment,
    LessonProgress, MakerPortfolio, MakerStudent as MakerStudentModel,
)
from app.schemas import ApiResponse
from app.api.v1.maker_auth import get_maker_user
from app.services.point_service import award_points_for_portfolio_approve

router = APIRouter(prefix="/maker/admin", tags=["메이커 코딩 - 원장"])

security = HTTPBearer()


def _require_admin(user: dict):
    """원장 권한 확인"""
    if user["role"] != "maker_admin":
        raise HTTPException(403, detail="원장(admin)만 접근 가능합니다.")
    studio_id = user.get("studio_id")
    if not studio_id:
        raise HTTPException(400, detail="스튜디오 정보가 없습니다.")
    return studio_id


# ──────────────────────────────────────────────
# 1. 대시보드 — 스튜디오 통계
# ──────────────────────────────────────────────


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    스튜디오 대시보드 통계를 조회합니다.
    - 원장( maker_admin ) 권한 필요
    - 총 학생 수, 총 강좌 수, 승인 대기 포트폴리오 수
    """
    studio_id = _require_admin(current_user)

    # 총 학생 수
    result = await db.execute(
        select(func.count(MakerStudent.id)).where(
            MakerStudent.studio_id == studio_id,
            MakerStudent.is_active == True,
        )
    )
    total_students = result.scalar() or 0

    # 스튜디오 학생들의 수강신청을 통해 연결된 강좌 수 (중복 제거)
    result = await db.execute(
        select(MakerStudent.id).where(
            MakerStudent.studio_id == studio_id,
            MakerStudent.is_active == True,
        )
    )
    student_ids = result.scalars().all()

    total_courses = 0
    pending_portfolios = 0

    if student_ids:
        # 수강신청된 강좌 수 (중복 제거)
        result = await db.execute(
            select(func.count(func.distinct(MakerEnrollment.maker_course_id))).where(
                MakerEnrollment.student_id.in_(student_ids),
                MakerEnrollment.status == "active",
            )
        )
        total_courses = result.scalar() or 0

        # 승인 대기 포트폴리오 수
        result = await db.execute(
            select(func.count(MakerPortfolio.id))
            .select_from(MakerPortfolio)
            .join(MakerEnrollment, MakerEnrollment.id == MakerPortfolio.enrollment_id)
            .where(
                MakerEnrollment.student_id.in_(student_ids),
                MakerPortfolio.confirmed_by.is_(None),
            )
        )
        pending_portfolios = result.scalar() or 0

    return ApiResponse(data={
        "total_students": total_students,
        "total_courses": total_courses,
        "pending_portfolios": pending_portfolios,
    })


# ──────────────────────────────────────────────
# 2. 학생 목록
# ──────────────────────────────────────────────


@router.get("/students")
async def list_students(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    소속 학생 목록을 조회합니다.
    - 원장( maker_admin ) 권한 필요
    - 해당 스튜디오의 모든 학생 반환
    """
    studio_id = _require_admin(current_user)

    result = await db.execute(
        select(MakerStudent)
        .where(MakerStudent.studio_id == studio_id)
        .order_by(MakerStudent.created_at.desc())
    )
    students = result.scalars().all()

    return ApiResponse(data=[
        {
            "id": s.id,
            "name": s.name,
            "login_id": s.login_id,
            "grade": s.grade,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in students
    ])


# ──────────────────────────────────────────────
# 3. 학생 상세 (진도 포함)
# ──────────────────────────────────────────────


@router.get("/students/{student_id}")
async def student_detail(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 학생의 상세 정보와 진도 현황을 조회합니다.
    - 원장( maker_admin ) 권한 필요
    - 해당 스튜디오 소속 학생만 조회 가능
    """
    studio_id = _require_admin(current_user)

    result = await db.execute(
        select(MakerStudent).where(
            MakerStudent.id == student_id,
            MakerStudent.studio_id == studio_id,
        )
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, detail="학생을 찾을 수 없습니다.")

    # 수강신청 목록 + 진도
    result = await db.execute(
        select(MakerEnrollment).where(
            MakerEnrollment.student_id == student_id,
        )
    )
    enrollments = result.scalars().all()

    courses_data = []
    total_completed = 0

    for enrollment in enrollments:
        # 강좌 정보
        result = await db.execute(
            select(MakerCourse).where(MakerCourse.id == enrollment.maker_course_id)
        )
        course = result.scalar_one_or_none()
        if not course:
            continue

        # 전체 차시 수
        from app.models import Lesson
        result = await db.execute(
            select(func.count(Lesson.id)).where(
                Lesson.maker_course_id == course.id,
            )
        )
        total_lessons = result.scalar() or 0

        # 완료한 차시 수
        result = await db.execute(
            select(func.count(LessonProgress.id)).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.completed == True,
            )
        )
        completed_lessons = result.scalar() or 0
        total_completed += completed_lessons

        courses_data.append({
            "enrollment_id": enrollment.id,
            "course_id": course.id,
            "title": course.title,
            "month": course.month,
            "description": course.description,
            "status": enrollment.status,
            "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "progress_percent": round(
                (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0, 1
            ),
        })

    return ApiResponse(data={
        "student": {
            "id": student.id,
            "name": student.name,
            "login_id": student.login_id,
            "grade": student.grade,
            "start_date": student.start_date.isoformat() if student.start_date else None,
            "is_active": student.is_active,
            "created_at": student.created_at.isoformat() if student.created_at else None,
        },
        "enrolled_courses": courses_data,
        "total_completed_lessons": total_completed,
    })


# ──────────────────────────────────────────────
# 4. 포트폴리오 목록
# ──────────────────────────────────────────────


@router.get("/portfolios")
async def list_portfolios(
    status: str = Query(None, description="필터: pending(승인대기) / confirmed(승인완료)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    스튜디오 소속 학생들의 포트폴리오 목록을 조회합니다.
    - 원장( maker_admin ) 권한 필요
    - `?status=pending`으로 승인 대기 건만 필터링 가능
    """
    studio_id = _require_admin(current_user)

    # 스튜디오 소속 학생 ID 목록
    result = await db.execute(
        select(MakerStudent.id).where(MakerStudent.studio_id == studio_id)
    )
    student_ids = result.scalars().all()

    if not student_ids:
        return ApiResponse(data=[])

    # 포트폴리오 JOIN 수강신청 → 학생
    query = (
        select(MakerPortfolio, MakerEnrollment, MakerStudent)
        .join(MakerEnrollment, MakerEnrollment.id == MakerPortfolio.enrollment_id)
        .join(MakerStudent, MakerStudent.id == MakerEnrollment.student_id)
        .where(MakerEnrollment.student_id.in_(student_ids))
        .order_by(MakerPortfolio.submitted_at.desc())
    )

    if status == "pending":
        query = query.where(MakerPortfolio.confirmed_by.is_(None))
    elif status == "confirmed":
        query = query.where(MakerPortfolio.confirmed_by.isnot(None))

    result = await db.execute(query)
    rows = result.all()

    portfolios_data = []
    for portfolio, enrollment, student in rows:
        # 강좌명 추가
        result = await db.execute(
            select(MakerCourse).where(MakerCourse.id == enrollment.maker_course_id)
        )
        course = result.scalar_one_or_none()

        portfolios_data.append({
            "id": portfolio.id,
            "enrollment_id": portfolio.enrollment_id,
            "student_id": student.id,
            "student_name": student.name,
            "course_title": course.title if course else None,
            "course_month": course.month if course else None,
            "portfolio_type": portfolio.portfolio_type,
            "files": portfolio.files,
            "description": portfolio.description,
            "submitted_at": portfolio.submitted_at.isoformat() if portfolio.submitted_at else None,
            "confirmed_by": portfolio.confirmed_by,
            "confirmed_at": portfolio.confirmed_at.isoformat() if portfolio.confirmed_at else None,
        })

    return ApiResponse(data=portfolios_data)


# ──────────────────────────────────────────────
# 5. 포트폴리오 상세
# ──────────────────────────────────────────────


@router.get("/portfolios/{portfolio_id}")
async def portfolio_detail(
    portfolio_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 포트폴리오의 상세 정보를 조회합니다.
    - 원장( maker_admin ) 권한 필요
    - 해당 스튜디오 소속 학생의 포트폴리오만 조회 가능
    """
    studio_id = _require_admin(current_user)

    # 포트폴리오 JOIN 수강신청 → 학생 (스튜디오 필터)
    result = await db.execute(
        select(MakerPortfolio, MakerEnrollment, MakerStudent)
        .join(MakerEnrollment, MakerEnrollment.id == MakerPortfolio.enrollment_id)
        .join(MakerStudent, MakerStudent.id == MakerEnrollment.student_id)
        .where(
            MakerPortfolio.id == portfolio_id,
            MakerStudent.studio_id == studio_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, detail="포트폴리오를 찾을 수 없습니다.")

    portfolio, enrollment, student = row

    # 강좌 정보
    result = await db.execute(
        select(MakerCourse).where(MakerCourse.id == enrollment.maker_course_id)
    )
    course = result.scalar_one_or_none()

    return ApiResponse(data={
        "id": portfolio.id,
        "enrollment_id": portfolio.enrollment_id,
        "student": {
            "id": student.id,
            "name": student.name,
            "grade": student.grade,
            "login_id": student.login_id,
        },
        "course": {
            "id": course.id if course else None,
            "title": course.title if course else None,
            "month": course.month if course else None,
        },
        "portfolio_type": portfolio.portfolio_type,
        "files": portfolio.files,
        "description": portfolio.description,
        "submitted_at": portfolio.submitted_at.isoformat() if portfolio.submitted_at else None,
        "confirmed_by": portfolio.confirmed_by,
        "confirmed_at": portfolio.confirmed_at.isoformat() if portfolio.confirmed_at else None,
    })


# ──────────────────────────────────────────────
# 6. 포트폴리오 승인
# ──────────────────────────────────────────────


@router.post("/portfolios/{portfolio_id}/confirm")
async def confirm_portfolio(
    portfolio_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    포트폴리오를 승인 처리합니다.
    - 원장( maker_admin ) 권한 필요
    - 해당 스튜디오 소속 학생의 포트폴리오만 승인 가능
    - confirmed_by에 스튜디오 ID, confirmed_at에 현재 시간 기록
    """
    studio_id = _require_admin(current_user)

    # 포트폴리오 + 소속 학생 확인
    result = await db.execute(
        select(MakerPortfolio, MakerEnrollment, MakerStudent)
        .join(MakerEnrollment, MakerEnrollment.id == MakerPortfolio.enrollment_id)
        .join(MakerStudent, MakerStudent.id == MakerEnrollment.student_id)
        .where(
            MakerPortfolio.id == portfolio_id,
            MakerStudent.studio_id == studio_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, detail="포트폴리오를 찾을 수 없거나 권한이 없습니다.")

    portfolio = row[0]

    if portfolio.confirmed_by is not None:
        raise HTTPException(409, detail="이미 승인된 포트폴리오입니다.")

    portfolio.confirmed_by = studio_id
    portfolio.confirmed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(portfolio)

    # 포인트 지급
    maker_student = row[2]
    maker_enrollment = row[1]
    maker_course_id = maker_enrollment.maker_course_id
    await award_points_for_portfolio_approve(
        db,
        student_id=maker_student.user_id or maker_student.id,
        portfolio_id=portfolio_id,
        course_id=maker_course_id,
    )

    return ApiResponse(data={
        "id": portfolio.id,
        "confirmed_by": portfolio.confirmed_by,
        "confirmed_at": portfolio.confirmed_at.isoformat() if portfolio.confirmed_at else None,
    }, message="포트폴리오가 승인되었습니다.")
