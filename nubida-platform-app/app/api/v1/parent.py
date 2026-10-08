"""
👨‍👩‍👧 학부모 모니터링 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    User, Course, Enrollment, Exam, Score, Attendance, Payment, Notification,
    LearningProgress, CourseMaterial, MembershipLink,
)
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/parent", tags=["학부모 모니터링"])


# ============================================================
# 자녀 목록
# ============================================================

@router.get("/children")
async def get_children(
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """학부모 계정에 연결된 자녀 목록 (super_admin은 전체 학생 조회)"""
    parent_id = current_user["id"]
    role = current_user.get("role", "")
    
    if role in ("super_admin", "admin"):
        # 본사/관리자는 전체 학생 목록 반환
        result = await db.execute(
            select(User).where(
                User.role == "student",
                User.is_active == True,
            ).order_by(User.name)
        )
        students = result.scalars().all()
        return ApiResponse(data=[{
            "id": s.id, "name": s.name, "username": s.username,
            "email": s.email, "phone": s.phone,
            "school": getattr(s, 'school', ''),
            "grade": getattr(s, 'grade', ''),
            "class_name": getattr(s, 'class_name', ''),
        } for s in students])
    
    # student_profiles 테이블에서 parent_id로 조회
    result = await db.execute(
        select(User).where(
            User.role == "student",
            User.is_active == True,
        )
    )
    students = result.scalars().all()

    return ApiResponse(data=[{
        "id": s.id, "name": s.name, "email": s.email,
        "phone": s.phone,
    } for s in students])


# ============================================================
# 자녀 학습 현황
# ============================================================

@router.get("/children/{child_id}/progress")
async def get_child_progress(
    child_id: int,
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    # 자녀 수강 강좌
    courses_result = await db.execute(
        select(Course).join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == child_id, Enrollment.status == "active")
    )
    courses = courses_result.scalars().all()

    # 전체 평균 성적
    avg_result = await db.execute(
        select(func.coalesce(func.avg(Score.score), 0))
        .where(Score.student_id == child_id)
    )
    avg_score = avg_result.scalar()

    course_data = []
    for c in courses:
        avg_c = await db.execute(
            select(func.coalesce(func.avg(Score.score), 0))
            .join(Exam, Exam.id == Score.exam_id)
            .where(Score.student_id == child_id, Exam.course_id == c.id)
        )
        # 학습 진행률
        total_materials = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == c.id, CourseMaterial.is_active == True)
        )).scalar() or 0
        completed = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.student_id == child_id,
                LearningProgress.course_id == c.id,
                LearningProgress.is_completed == True,
            )
        )).scalar() or 0
        in_progress = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.student_id == child_id,
                LearningProgress.course_id == c.id,
                LearningProgress.is_completed == False,
                LearningProgress.progress_percent > 0,
            )
        )).scalar() or 0
        completion_rate = round((completed / total_materials * 100)) if total_materials > 0 else 0

        course_data.append({
            "id": c.id, "name": c.name, "subject": c.subject, "category": c.category,
            "average_score": round(float(avg_c.scalar() or 0), 2),
            "total_materials": total_materials,
            "completed_materials": completed,
            "in_progress_materials": in_progress,
            "completion_rate": completion_rate,
        })

    return ApiResponse(data={
        "child_id": child_id,
        "average_score": round(float(avg_score or 0), 2),
        "courses": course_data,
    })


@router.get("/children/{child_id}/scores")
async def get_child_scores(
    child_id: int,
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Score, Exam)
        .join(Exam, Exam.id == Score.exam_id)
        .where(Score.student_id == child_id)
        .order_by(Exam.exam_date.desc())
    )
    rows = result.all()

    return ApiResponse(data=[{
        "exam_title": r.Exam.title, "exam_date": str(r.Exam.exam_date) if r.Exam.exam_date else None,
        "score": float(r.Score.score) if r.Score.score else None,
        "max_score": float(r.Exam.max_score) if r.Exam.max_score else None,
        "grade": "", "feedback": "",
    } for r in rows])


@router.get("/children/{child_id}/attendance")
async def get_child_attendance(
    child_id: int,
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Attendance).where(Attendance.student_id == child_id)
        .order_by(Attendance.date.desc()).limit(100)
    )
    records = result.scalars().all()

    return ApiResponse(data=[{
        "date": str(r.date), "status": r.status,
    } for r in records])


# ============================================================
# 결제 내역
# ============================================================

@router.get("/payments")
async def get_payments(
    child_id: int = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    parent_id = current_user["id"]

    # Get children linked to this parent
    child_result = await db.execute(
        select(MembershipLink.child_id).where(
            MembershipLink.parent_id == parent_id,
            MembershipLink.relationship == "parent_child",
            MembershipLink.status == "active",
        )
    )
    child_ids = [row[0] for row in child_result.all()]

    # Fallback: if no membership links, get all students
    if not child_ids:
        students_result = await db.execute(
            select(User).where(User.role == "student", User.is_active == True).limit(100)
        )
        child_ids = [s.id for s in students_result.scalars().all()]

    query = select(Payment).where(
        or_(
            Payment.parent_id == parent_id,
            Payment.student_id.in_(child_ids) if child_ids else False,
        )
    ).order_by(Payment.created_at.desc())

    if child_id:
        if child_id in child_ids:
            query = query.where(Payment.student_id == child_id)
        else:
            return PaginatedResponse(data=[], total=0, page=page, per_page=per_page, total_pages=0)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    payments = result.scalars().all()

    items = []
    for p in payments:
        student = await db.get(User, p.student_id) if p.student_id else None
        course = await db.get(Course, p.course_id) if p.course_id else None
        items.append({
            "id": p.id,
            "student_id": p.student_id,
            "student_name": student.name if student else None,
            "course_id": p.course_id,
            "course_name": course.name if course else None,
            "branch_id": p.branch_id,
            "amount": float(p.amount),
            "method": p.method,
            "status": p.status,
            "paid_at": str(p.paid_at) if p.paid_at else None,
            "receipt_number": p.receipt_number,
        })

    return PaginatedResponse(
        data=items,
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 알림
# ============================================================

@router.get("/notifications")
async def get_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("parent", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Notification).where(
        Notification.user_id == current_user["id"]
    ).order_by(Notification.created_at.desc())

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    notifs = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": n.id, "title": n.title, "content": n.content,
            "type": n.notif_type, "is_read": n.is_read,
            "created_at": str(n.created_at),
        } for n in notifs],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 상담 예약
# ============================================================

@router.post("/consultations")
async def create_consultation(
    data: dict,
    current_user: dict = Depends(require_role("parent")),
    db: AsyncSession = Depends(get_db),
):
    """상담 예약 (알림 시스템으로 전달)"""
    notif = Notification(
        user_id=data.get("director_id", 0),
        title="상담 신청",
        content=f"학부모({current_user['id']})가 자녀({data.get('child_id')}) 상담을 신청했습니다.\n"
                f"희망일시: {data.get('preferred_date')}\n내용: {data.get('message', '')}",
        notif_type="schedule",
    )
    db.add(notif)
    await db.commit()
    return ApiResponse(message="상담이 예약되었습니다.")
