"""
👨‍🎓 메이커 코딩 교육 시스템 — 학생 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone

from app.core.database import get_db
from app.models import (
    MakerCourse, Lesson, MakerStudent, MakerEnrollment,
    LessonProgress, Coding, MakerPortfolio
)
from app.schemas import ApiResponse
from app.api.v1.maker_auth import get_maker_user

router = APIRouter(prefix="/maker/student", tags=["메이커 코딩 - 학생"])


@router.get("/courses")
async def list_courses(
    year: str = Query(None),
    month: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """월별 강좌 목록 조회"""
    query = select(MakerCourse).where(MakerCourse.status == "active").order_by(MakerCourse.month.desc())
    if year and month:
        ym = f"{year}-{month.zfill(2)}"
        query = query.where(MakerCourse.month == ym)
    result = await db.execute(query)
    courses = result.scalars().all()
    return ApiResponse(data=[{
        "id": c.id, "title": c.title, "month": c.month,
        "description": c.description, "thumbnail": c.thumbnail,
        "kit_name": c.kit_name, "created_at": str(c.created_at),
    } for c in courses])


@router.post("/courses/{course_id}/enroll")
async def enroll_course(
    course_id: int,
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌 수강신청"""
    if user["role"] != "maker_student":
        raise HTTPException(403, detail="학생만 수강신청 가능합니다.")

    # Check course exists
    result = await db.execute(select(MakerCourse).where(MakerCourse.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, detail="강좌를 찾을 수 없습니다.")

    # Check duplicate
    result = await db.execute(
        select(MakerEnrollment).where(
            MakerEnrollment.student_id == user["id"],
            MakerEnrollment.maker_course_id == course_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(409, detail="이미 수강신청한 강좌입니다.")

    enrollment = MakerEnrollment(student_id=user["id"], maker_course_id=course_id)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return ApiResponse(data={"id": enrollment.id, "status": enrollment.status})


@router.get("/mycourses")
async def my_courses(
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """내 수강 강좌 목록"""
    result = await db.execute(
        select(MakerEnrollment, MakerCourse)
        .join(MakerCourse, MakerEnrollment.maker_course_id == MakerCourse.id)
        .where(MakerEnrollment.student_id == user["id"])
        .order_by(MakerCourse.month.desc())
    )
    rows = result.all()

    data = []
    for enrollment, course in rows:
        # Count completed lessons
        lesson_count = await db.execute(
            select(func.count()).select_from(Lesson)
            .where(Lesson.maker_course_id == course.id)
        )
        total_lessons = lesson_count.scalar() or 0
        completed_count = await db.execute(
            select(func.count()).select_from(LessonProgress)
            .where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.completed == True,
            )
        )
        completed = completed_count.scalar() or 0

        data.append({
            "enrollment_id": enrollment.id,
            "course_id": course.id,
            "title": course.title,
            "month": course.month,
            "kit_name": course.kit_name,
            "total_lessons": total_lessons,
            "completed_lessons": completed,
            "progress_pct": round(completed / total_lessons * 100) if total_lessons > 0 else 0,
            "enrolled_at": str(enrollment.enrolled_at),
        })
    return ApiResponse(data=data)


@router.get("/learn/{course_id}")
async def get_lessons(
    course_id: int,
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌 차시별 목록 (진도 포함)"""
    # Get enrollment
    result = await db.execute(
        select(MakerEnrollment).where(
            MakerEnrollment.student_id == user["id"],
            MakerEnrollment.maker_course_id == course_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(403, detail="수강신청한 강좌만 접근 가능합니다.")

    # Get lessons
    result = await db.execute(
        select(Lesson).where(Lesson.maker_course_id == course_id)
        .order_by(Lesson.order_num)
    )
    lessons = result.scalars().all()

    # Get progress
    result = await db.execute(
        select(LessonProgress).where(LessonProgress.enrollment_id == enrollment.id)
    )
    progress_map = {p.lesson_id: p for p in result.scalars().all()}

    return ApiResponse(data=[{
        "id": l.id,
        "order_num": l.order_num,
        "title": l.title,
        "content_type": l.content_type,
        "ppt_url": l.ppt_url,
        "video_url": l.video_url,
        "duration_minutes": l.duration_minutes,
        "description": l.description,
        "completed": progress_map.get(l.id) and progress_map[l.id].completed,
        "completed_at": str(progress_map[l.id].completed_at) if progress_map.get(l.id) and progress_map[l.id].completed_at else None,
    } for l in lessons])


@router.post("/progress/{lesson_id}")
async def mark_progress(
    lesson_id: int,
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """차시 학습 완료 표시"""
    result = await db.execute(
        select(MakerEnrollment).where(MakerEnrollment.student_id == user["id"])
    )
    enrollments = result.scalars().all()
    enrollment_ids = [e.id for e in enrollments]
    if not enrollment_ids:
        raise HTTPException(403, detail="수강신청한 강좌가 없습니다.")

    result = await db.execute(
        select(LessonProgress).where(
            LessonProgress.enrollment_id.in_(enrollment_ids),
            LessonProgress.lesson_id == lesson_id,
        )
    )
    progress = result.scalar_one_or_none()

    if progress:
        progress.completed = True
        progress.completed_at = datetime.now(timezone.utc)
    else:
        # Find which enrollment this lesson belongs to
        result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
        lesson = result.scalar_one_or_none()
        if not lesson:
            raise HTTPException(404, detail="차시를 찾을 수 없습니다.")

        # Find matching enrollment
        result = await db.execute(
            select(MakerEnrollment).where(
                MakerEnrollment.student_id == user["id"],
                MakerEnrollment.maker_course_id == lesson.maker_course_id,
            )
        )
        enrollment = result.scalar_one_or_none()
        if not enrollment:
            raise HTTPException(403, detail="해당 강좌에 수강신청하지 않았습니다.")

        progress = LessonProgress(
            enrollment_id=enrollment.id,
            lesson_id=lesson_id,
            completed=True,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(progress)

    await db.commit()
    return ApiResponse(data={"lesson_id": lesson_id, "completed": True})


@router.post("/coding/{lesson_id}")
async def save_coding(
    lesson_id: int,
    data: dict,
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """학생 코드 저장"""
    code = data.get("code", "")
    result = await db.execute(
        select(MakerEnrollment).where(MakerEnrollment.student_id == user["id"])
    )
    enrollments = result.scalars().all()
    if not enrollments:
        raise HTTPException(403, detail="수강신청한 강좌가 없습니다.")

    # Check if coding exists
    from app.models import Coding
    result = await db.execute(
        select(Coding).where(
            Coding.enrollment_id.in_([e.id for e in enrollments]),
            Coding.lesson_id == lesson_id,
        )
    )
    coding = result.scalar_one_or_none()

    if coding:
        coding.code_content = code
        coding.submitted_at = datetime.now(timezone.utc)
    else:
        # Find the right enrollment
        result = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
        lesson = result.scalar_one_or_none()
        if not lesson:
            raise HTTPException(404, detail="차시를 찾을 수 없습니다.")
        result = await db.execute(
            select(MakerEnrollment).where(
                MakerEnrollment.student_id == user["id"],
                MakerEnrollment.maker_course_id == lesson.maker_course_id,
            )
        )
        enrollment = result.scalar_one_or_none()
        if not enrollment:
            raise HTTPException(403, detail="수강신청한 강좌가 아닙니다.")
        coding = Coding(enrollment_id=enrollment.id, lesson_id=lesson_id, code_content=code)
        db.add(coding)

    await db.commit()
    return ApiResponse(data={"lesson_id": lesson_id, "saved": True})


@router.post("/portfolio/{enroll_id}")
async def submit_portfolio(
    enroll_id: int,
    data: dict,
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """포트폴리오 제출 (1차/2차)"""
    portfolio_type = data.get("type", "1차")
    files = data.get("files", [])
    description = data.get("description", "")

    # Verify enrollment belongs to student
    result = await db.execute(
        select(MakerEnrollment).where(
            MakerEnrollment.id == enroll_id,
            MakerEnrollment.student_id == user["id"],
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(403, detail="해당 수강 내역이 없습니다.")

    portfolio = MakerPortfolio(
        enrollment_id=enroll_id,
        portfolio_type=portfolio_type,
        files=files,
        description=description,
        content=data.get("content", ""),
    )
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return ApiResponse(data={"id": portfolio.id, "type": portfolio_type, "submitted_at": str(portfolio.submitted_at)})


@router.get("/portfolios")
async def my_portfolios(
    user: dict = Depends(get_maker_user),
    db: AsyncSession = Depends(get_db),
):
    """내 포트폴리오 목록"""
    result = await db.execute(
        select(MakerPortfolio)
        .join(MakerEnrollment, MakerPortfolio.enrollment_id == MakerEnrollment.id)
        .where(MakerEnrollment.student_id == user["id"])
        .order_by(MakerPortfolio.submitted_at.desc())
    )
    portfolios = result.scalars().all()
    return ApiResponse(data=[{
        "id": p.id,
        "enrollment_id": p.enrollment_id,
        "type": p.portfolio_type,
        "files": p.files,
        "description": p.description,
        "content": p.content,
        "submitted_at": str(p.submitted_at) if p.submitted_at else None,
        "confirmed": p.confirmed_by is not None,
    } for p in portfolios])
