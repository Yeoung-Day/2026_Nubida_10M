"""
👨‍🎓 학생 학습 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    User, Course, ClassSchedule, Enrollment, Exam, Score, Attendance, Notification,
    CourseMaterial, LearningProgress, StudentSchedule,
)
from app.schemas import ApiResponse, PaginatedResponse, StudentScheduleCreate, StudentScheduleUpdate

router = APIRouter(prefix="/student", tags=["학생 학습"])


# ============================================================
# 내 대시보드
# ============================================================

@router.get("/dashboard")
async def get_dashboard(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 수업/일정/알림 요약 — 실제 수강 데이터 기반"""
    user_id = current_user["id"]

    # 수강 중인 강좌 수 + 목록 (비활성화 강좌 제외 + 소속 공부방만)
    enroll_result = await db.execute(
        select(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
            Course.status == "active",
        )
    )
    enrolled_courses = enroll_result.scalars().all()

    # 수강 강좌 목록 (recent_courses) — 학습 자료 기반 진행률
    recent_courses = []
    from datetime import date as dt_date
    for c in enrolled_courses:
        # Get enrollment payment_status for this course
        enr_result = await db.execute(
            select(Enrollment.payment_status).where(
                Enrollment.student_id == user_id,
                Enrollment.course_id == c.id,
                Enrollment.status == "active",
            )
        )
        pstatus = enr_result.scalar_one_or_none() or "pending"

        # 학습 자료 수
        mat_count = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == c.id, CourseMaterial.is_active == True)
        )).scalar() or 0

        # 완료한 학습 자료 수
        completed = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.course_id == c.id,
                LearningProgress.student_id == user_id,
                LearningProgress.is_completed == True,
            )
        )).scalar() or 0

        progress = round(completed / mat_count * 100) if mat_count > 0 else 0

        recent_courses.append({
            "id": c.id,
            "name": c.name,
            "teacher": c.instructor or "",
            "subject": c.subject or "",
            "category": c.category or "",
            "progress": progress,
            "payment_status": pstatus,
        })

    # 완료 수업 수 (출석 상태가 present인 수업)
    completed = (await db.execute(
        select(func.count(Attendance.id))
        .where(Attendance.student_id == user_id, Attendance.status == "present")
    )).scalar() or 0

    # 평균 성적
    avg_result = await db.execute(
        select(func.avg(Score.score))
        .where(Score.student_id == user_id)
    )
    avg_score = avg_result.scalar()
    avg_grade = f"{float(avg_score):.1f}" if avg_score else "-"

    # 출석률
    total_att = (await db.execute(
        select(func.count(Attendance.id))
        .where(Attendance.student_id == user_id)
    )).scalar() or 1
    present_att = (await db.execute(
        select(func.count(Attendance.id))
        .where(Attendance.student_id == user_id, Attendance.status == "present")
    )).scalar() or 0
    attendance_rate = round(present_att / total_att * 100) if total_att > 0 else 0

    # 오늘 시간표
    today = dt_date.today()
    day_of_week = today.weekday()  # 0=Mon, 6=Sun
    today_schedule_result = await db.execute(
        select(ClassSchedule, Course)
        .join(Course, Course.id == ClassSchedule.course_id)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
            ClassSchedule.day_of_week == day_of_week,
        )
        .order_by(ClassSchedule.start_time)
    )
    today_rows = today_schedule_result.all()
    today_schedule = [{
        "time": f"{str(r.ClassSchedule.start_time)[:5]}~{str(r.ClassSchedule.end_time)[:5]}",
        "course": r.Course.name,
        "teacher": r.Course.instructor or "",
        "room": r.ClassSchedule.room or "",
    } for r in today_rows]

    # 최근 성적 (최근 5개)
    recent_scores_result = await db.execute(
        select(Score, Exam, Course)
        .join(Exam, Exam.id == Score.exam_id)
        .join(Course, Course.id == Exam.course_id)
        .where(Score.student_id == user_id)
        .order_by(Exam.exam_date.desc())
        .limit(5)
    )
    recent_rows = recent_scores_result.all()
    recent_scores = [{
        "exam_name": r.Exam.title,
        "course_name": r.Course.name,
        "score": float(r.Score.score) if r.Score.score else None,
        "grade": "",
        "date": str(r.Exam.exam_date) if r.Exam.exam_date else "",
    } for r in recent_rows]

    return ApiResponse(data={
        "total_courses": len(enrolled_courses),
        "course_count": len(enrolled_courses),
        "completed_lessons": completed,
        "avg_grade": avg_grade,
        "attendance_rate": attendance_rate,
        "unread_notifications": 0,
        "recent_courses": recent_courses,
        "today_schedule": today_schedule,
        "recent_scores": recent_scores,
    })


# ============================================================
# 수강 강좌
# ============================================================

# ============================================================
# 전체 강좌 카탈로그 — 소속 학급(Class)에 연결된 강좌만
# ============================================================

@router.get("/catalog")
async def get_course_catalog(
    category: str = None,
    subject: str = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌 카탈로그 — 학생이 현재 수강 중인(Enrollment active) 강좌만 노출"""
    user_id = current_user["id"]

    # Enrollment가 active인 강좌만 필터 (원장이 해지하면 자동 제외)
    query = (
        select(Course, Enrollment.payment_status)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
            Course.status == "active",
        )
        .order_by(Course.id.desc())
    )

    if category:
        query = query.where(Course.category == category)
    if subject:
        query = query.where(Course.subject == subject)

    result = await db.execute(query)
    rows = result.all()

    # Get material count for each course
    user_id = current_user["id"]
    data = []
    for c, pstatus in rows:
        mat_count = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == c.id, CourseMaterial.is_active == True)
        )).scalar() or 0

        # 학생별 학습 진도
        completed = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.course_id == c.id,
                LearningProgress.student_id == user_id,
                LearningProgress.is_completed == True,
            )
        )).scalar() or 0
        in_progress = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.course_id == c.id,
                LearningProgress.student_id == user_id,
                LearningProgress.is_completed == False,
            )
        )).scalar() or 0

        data.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "subject": c.subject,
            "category": c.category,
            "status": c.status,
            "material_count": mat_count,
            "completed_count": completed,
            "in_progress_count": in_progress,
            "progress_pct": round(completed / mat_count * 100) if mat_count > 0 else 0,
            "payment_status": pstatus or "pending",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return ApiResponse(data=data)


# ============================================================
# 수강 중인 강좌
# ============================================================

@router.get("/courses")
@router.get("/my_courses")
async def get_my_courses(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["id"]
    result = await db.execute(
        select(Course, Enrollment.payment_status).join(Enrollment, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
            Course.status == "active",
        )
    )
    rows = result.all()

    # 각 강좌별 진행률 계산
    course_list = []
    for c, pstatus in rows:
        # 학습 자료 수
        mat_count = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == c.id, CourseMaterial.is_active == True)
        )).scalar() or 0
        # 완료한 학습 자료 수
        completed = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.course_id == c.id,
                LearningProgress.student_id == user_id,
                LearningProgress.is_completed == True,
            )
        )).scalar() or 0
        course_list.append({
            "id": c.id, "name": c.name, "subject": c.subject,
            "category": c.category, "status": c.status,
            "instructor": c.instructor, "description": c.description,
            "payment_status": pstatus or "pending",
            "total_lessons": mat_count,
            "completed_lessons": completed,
        })

    return ApiResponse(data=course_list)


@router.get("/courses/{course_id}/materials")
async def get_course_materials(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌별 학습 자료 목록 — is_active=true만 반환"""
    materials_result = await db.execute(
        select(CourseMaterial)
        .where(
            CourseMaterial.course_id == course_id,
            CourseMaterial.is_active == True,
        )
        .order_by(CourseMaterial.sort_order, CourseMaterial.id)
    )
    materials = materials_result.scalars().all()

    return ApiResponse(data=[{
        "id": m.id,
        "title": m.title,
        "description": m.description,
        "material_type": m.material_type,
        "file_url": m.file_url,
        "embed_url": m.embed_url,
        "file_size": m.file_size,
        "duration_minutes": m.duration_minutes,
        "sort_order": m.sort_order,
        "created_at": str(m.created_at) if m.created_at else None,
    } for m in materials])


# ============================================================
# 전체 과제 목록 (수강 중인 모든 강좌의 과제)
# ============================================================

@router.get("/assignments")
async def get_all_assignments(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """수강 중인 모든 강좌의 과제 목록"""
    user_id = current_user["id"]

    # 수강 중인 강좌 ID 목록
    enrollment_result = await db.execute(
        select(Enrollment.course_id).where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
        )
    )
    course_ids = [r[0] for r in enrollment_result.all()]
    if not course_ids:
        return ApiResponse(data=[])

    # 모든 과제 조회 (해당 강좌의 assignment 타입 시험)
    result = await db.execute(
        select(Exam, Course.name)
        .join(Course, Course.id == Exam.course_id)
        .where(
            Exam.course_id.in_(course_ids),
            Exam.exam_type == "assignment",
        )
        .order_by(Exam.exam_date.desc())
    )
    rows = result.all()

    data = []
    for exam, course_name in rows:
        score_result = await db.execute(
            select(Score).where(
                Score.exam_id == exam.id, Score.student_id == user_id
            )
        )
        score = score_result.scalar_one_or_none()
        is_submitted = score is not None
        data.append({
            "id": exam.id,
            "title": exam.title,
            "course_name": course_name,
            "due_date": str(exam.exam_date) if exam.exam_date else None,
            "status": "graded" if (score and score.score is not None) else ("submitted" if is_submitted else "pending"),
            "score": float(score.score) if score and score.score is not None else None,
            "max_score": float(exam.max_score) if exam.max_score else None,
        })

    return ApiResponse(data=data)


@router.get("/courses/{course_id}/assignments")
async def get_assignments(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """과제 목록 (exam_type='assignment'인 시험)"""
    result = await db.execute(
        select(Exam).where(
            Exam.course_id == course_id, Exam.exam_type == "assignment"
        ).order_by(Exam.exam_date.desc())
    )
    assignments = result.scalars().all()

    user_id = current_user["id"]
    data = []
    for a in assignments:
        score_result = await db.execute(
            select(Score).where(
                Score.exam_id == a.id, Score.student_id == user_id
            )
        )
        score = score_result.scalar_one_or_none()
        data.append({
            "id": a.id, "title": a.title, "exam_date": str(a.exam_date) if a.exam_date else None,
            "max_score": float(a.max_score) if a.max_score else None,
            "submitted": score is not None,
            "score": float(score.score) if score else None,
        })

    return ApiResponse(data=data)


# ============================================================
# 내 성적
# ============================================================

@router.get("/scores")
async def get_my_scores(
    course_id: int = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["id"]
    query = (
        select(Score, Exam)
        .join(Exam, Exam.id == Score.exam_id)
        .where(Score.student_id == user_id)
    )
    if course_id:
        query = query.where(Exam.course_id == course_id)

    result = await db.execute(query)
    rows = result.all()

    return ApiResponse(data=[{
        "exam_id": r.Exam.id, "exam_title": r.Exam.title,
        "exam_type": r.Exam.exam_type,
        "score": float(r.Score.score) if r.Score.score else None,
        "max_score": float(r.Exam.max_score) if r.Exam.max_score else None,
        "grade": "",
        "feedback": "",
        "exam_date": str(r.Exam.exam_date) if r.Exam.exam_date else None,
    } for r in rows])


# ============================================================
# 내 시간표
# ============================================================

@router.get("/schedule")
async def get_my_schedule(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["id"]
    result = await db.execute(
        select(ClassSchedule, Course)
        .join(Course, Course.id == ClassSchedule.course_id)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
            Course.status == "active",
        )
        .order_by(ClassSchedule.day_of_week, ClassSchedule.start_time)
    )
    rows = result.all()

    return ApiResponse(data=[{
            "course_id": r.Course.id, "course_name": r.Course.name,
            "subject": r.Course.subject, "category": r.Course.category,
        "day_of_week": r.ClassSchedule.day_of_week,
        "start_time": str(r.ClassSchedule.start_time),
        "end_time": str(r.ClassSchedule.end_time),
        "room": r.ClassSchedule.room,
    } for r in rows])


# ============================================================
# 내 출결
# ============================================================

@router.get("/attendance")
async def get_my_attendance(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["id"]
    result = await db.execute(
        select(Attendance).where(Attendance.student_id == user_id)
        .order_by(Attendance.date.desc()).limit(100)
    )
    records = result.scalars().all()

    return ApiResponse(data=[{
        "id": r.id, "date": str(r.date), "status": r.status,
        "schedule_id": r.schedule_id,
    } for r in records])


# ============================================================
# 개인 일정 (StudentSchedule) — 학생이 직접 등록
# ============================================================

from datetime import time as dt_time


@router.get("/my-schedule")
async def get_my_schedule(
    start_date: str = None,
    end_date: str = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 개인 일정 목록 (선택적 날짜 필터)"""
    from datetime import date as dt_date
    user_id = current_user["id"]
    query = select(StudentSchedule).where(
        StudentSchedule.student_id == user_id
    )
    if start_date:
        query = query.where(StudentSchedule.date >= dt_date.fromisoformat(start_date))
    if end_date:
        query = query.where(StudentSchedule.date <= dt_date.fromisoformat(end_date))
    query = query.order_by(StudentSchedule.date, StudentSchedule.start_time)
    result = await db.execute(query)
    schedules = result.scalars().all()
    return ApiResponse(data=[{
        "id": s.id,
        "title": s.title,
        "date": str(s.date),
        "start_time": str(s.start_time)[:5] if s.start_time else None,
        "end_time": str(s.end_time)[:5] if s.end_time else None,
        "memo": s.memo or "",
        "color": s.color or "#0891B2",
        "created_at": str(s.created_at) if s.created_at else None,
    } for s in schedules])


@router.post("/my-schedule")
async def create_my_schedule(
    data: StudentScheduleCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """개인 일정 추가"""
    user_id = current_user["id"]
    start_t = dt_time.fromisoformat(data.start_time) if data.start_time else None
    end_t = dt_time.fromisoformat(data.end_time) if data.end_time else None
    schedule = StudentSchedule(
        student_id=user_id,
        title=data.title,
        date=data.date,
        start_time=start_t,
        end_time=end_t,
        memo=data.memo or "",
        color=data.color or "#0891B2",
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return ApiResponse(data={
        "id": schedule.id,
        "title": schedule.title,
        "date": str(schedule.date),
        "start_time": str(schedule.start_time)[:5] if schedule.start_time else None,
        "end_time": str(schedule.end_time)[:5] if schedule.end_time else None,
        "memo": schedule.memo or "",
        "color": schedule.color or "#0891B2",
    }, message="일정이 추가되었습니다.")


@router.put("/my-schedule/{schedule_id}")
async def update_my_schedule(
    schedule_id: int,
    data: StudentScheduleUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """개인 일정 수정"""
    user_id = current_user["id"]
    result = await db.execute(
        select(StudentSchedule).where(
            StudentSchedule.id == schedule_id,
            StudentSchedule.student_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")
    if data.title is not None:
        schedule.title = data.title
    if data.date is not None:
        schedule.date = data.date
    if data.start_time is not None:
        schedule.start_time = dt_time.fromisoformat(data.start_time)
    if data.end_time is not None:
        schedule.end_time = dt_time.fromisoformat(data.end_time)
    if data.memo is not None:
        schedule.memo = data.memo
    if data.color is not None:
        schedule.color = data.color
    await db.commit()
    await db.refresh(schedule)
    return ApiResponse(data={
        "id": schedule.id,
        "title": schedule.title,
        "date": str(schedule.date),
        "start_time": str(schedule.start_time)[:5] if schedule.start_time else None,
        "end_time": str(schedule.end_time)[:5] if schedule.end_time else None,
        "memo": schedule.memo or "",
        "color": schedule.color or "#0891B2",
    }, message="일정이 수정되었습니다.")


@router.delete("/my-schedule/{schedule_id}")
async def delete_my_schedule(
    schedule_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """개인 일정 삭제"""
    user_id = current_user["id"]
    result = await db.execute(
        select(StudentSchedule).where(
            StudentSchedule.id == schedule_id,
            StudentSchedule.student_id == user_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")
    await db.delete(schedule)
    await db.commit()
    return ApiResponse(message="일정이 삭제되었습니다.")
