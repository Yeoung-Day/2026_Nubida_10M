"""
🎓 원격 수업 관리 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import RemoteClass, RemoteAttendance
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/classroom", tags=["원격수업"])


# ============================================================
# 원격 수업 생성 (teacher / admin)
# ============================================================

@router.post("")
async def create_remote_class(
    data: dict,
    current_user: dict = Depends(require_role("branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    remote_class = RemoteClass(
        title=data.get("title"),
        description=data.get("description"),
        course_id=data.get("course_id"),
        teacher_id=data.get("teacher_id"),
        scheduled_at=data.get("scheduled_at"),
        duration_minutes=data.get("duration_minutes", 60),
        room_url=data.get("room_url"),
        max_participants=data.get("max_participants", 30),
        recording_url=data.get("recording_url"),
    )
    db.add(remote_class)
    await db.commit()
    await db.refresh(remote_class)
    return ApiResponse(message="원격 수업이 생성되었습니다.", data={
        "id": remote_class.id,
        "title": remote_class.title,
        "course_id": remote_class.course_id,
        "teacher_id": remote_class.teacher_id,
        "scheduled_at": str(remote_class.scheduled_at) if remote_class.scheduled_at else None,
        "status": remote_class.status,
    })


# ============================================================
# 원격 수업 목록 조회 (필터 지원)
# ============================================================

@router.get("")
async def get_remote_classes(
    course_id: int = None,
    teacher_id: int = None,
    status: str = None,
    date_from: str = None,
    date_to: str = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(RemoteClass)

    if course_id is not None:
        query = query.where(RemoteClass.course_id == course_id)
    if teacher_id is not None:
        query = query.where(RemoteClass.teacher_id == teacher_id)
    if status is not None:
        query = query.where(RemoteClass.status == status)
    if date_from is not None:
        query = query.where(RemoteClass.scheduled_at >= date_from)
    if date_to is not None:
        query = query.where(RemoteClass.scheduled_at <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(RemoteClass.scheduled_at.desc(), RemoteClass.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    classes = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "course_id": c.course_id,
            "teacher_id": c.teacher_id,
            "scheduled_at": str(c.scheduled_at) if c.scheduled_at else None,
            "duration_minutes": c.duration_minutes,
            "status": c.status,
            "room_url": c.room_url,
            "max_participants": c.max_participants,
            "recording_url": c.recording_url,
            "created_at": str(c.created_at) if c.created_at else None,
            "updated_at": str(c.updated_at) if c.updated_at else None,
        } for c in classes],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 내 원격 수업 조회 (학생 — 내가 수강 중인 강좌의 예정 수업)
# ============================================================

@router.get("/my")
async def get_my_remote_classes(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자의 예정된 원격 수업 목록 (upcoming)"""
    query = (
        select(RemoteClass)
        .join(RemoteClass.course)
        .where(RemoteClass.teacher_id == current_user["id"])
    )

    # 학생이면 수강 중인 강좌의 수업만
    if current_user["role"] == "student":
        from app.models import Enrollment
        enrolled = await db.execute(
            select(Enrollment.course_id).where(
                Enrollment.student_id == current_user["id"],
                Enrollment.status == "active",
            )
        )
        course_ids = [row[0] for row in enrolled.all()]
        if not course_ids:
            return ApiResponse(data=[])
        query = select(RemoteClass).where(
            RemoteClass.course_id.in_(course_ids),
            RemoteClass.status.in_(["scheduled", "live"]),
        )

    query = query.order_by(RemoteClass.scheduled_at.asc())
    result = await db.execute(query)
    classes = result.scalars().all()

    return ApiResponse(data=[{
        "id": c.id,
        "title": c.title,
        "description": c.description,
        "course_id": c.course_id,
        "teacher_id": c.teacher_id,
        "scheduled_at": str(c.scheduled_at) if c.scheduled_at else None,
        "duration_minutes": c.duration_minutes,
        "status": c.status,
        "room_url": c.room_url,
        "max_participants": c.max_participants,
        "recording_url": c.recording_url,
        "created_at": str(c.created_at) if c.created_at else None,
        "updated_at": str(c.updated_at) if c.updated_at else None,
    } for c in classes])


# ============================================================
# 원격 수업 단건 조회
# ============================================================

@router.get("/{class_id}")
async def get_remote_class(
    class_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": remote_class.id,
        "title": remote_class.title,
        "description": remote_class.description,
        "course_id": remote_class.course_id,
        "teacher_id": remote_class.teacher_id,
        "scheduled_at": str(remote_class.scheduled_at) if remote_class.scheduled_at else None,
        "duration_minutes": remote_class.duration_minutes,
        "status": remote_class.status,
        "room_url": remote_class.room_url,
        "max_participants": remote_class.max_participants,
        "recording_url": remote_class.recording_url,
        "created_at": str(remote_class.created_at) if remote_class.created_at else None,
        "updated_at": str(remote_class.updated_at) if remote_class.updated_at else None,
    })


# ============================================================
# 원격 수업 수정 (teacher / admin)
# ============================================================

@router.put("/{class_id}")
async def update_remote_class(
    class_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    # 선생님은 자신의 수업만 수정 가능
    if current_user["role"] == "branch_admin" and remote_class.teacher_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="자신의 수업만 수정할 수 있습니다.")

    allowed_fields = {
        "title", "description", "course_id", "teacher_id", "scheduled_at",
        "duration_minutes", "status", "room_url", "max_participants", "recording_url",
    }
    for key, val in data.items():
        if key in allowed_fields:
            setattr(remote_class, key, val)

    await db.commit()
    await db.refresh(remote_class)
    return ApiResponse(message="원격 수업이 수정되었습니다.", data={
        "id": remote_class.id,
        "title": remote_class.title,
        "status": remote_class.status,
    })


# ============================================================
# 원격 수업 삭제 (admin only)
# ============================================================

@router.delete("/{class_id}")
async def delete_remote_class(
    class_id: int,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    # 관련 출석 기록도 삭제
    await db.execute(
        select(RemoteAttendance).where(RemoteAttendance.class_id == class_id)
    )
    attendance_result = await db.execute(
        select(RemoteAttendance).where(RemoteAttendance.class_id == class_id)
    )
    for record in attendance_result.scalars().all():
        await db.delete(record)

    await db.delete(remote_class)
    await db.commit()
    return ApiResponse(message="원격 수업이 삭제되었습니다.")


# ============================================================
# 원격 수업 시작 (teacher / admin)
# ============================================================

@router.post("/{class_id}/start")
async def start_remote_class(
    class_id: int,
    current_user: dict = Depends(require_role("branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    if remote_class.status != "scheduled":
        raise HTTPException(status_code=400, detail=f"현재 상태({remote_class.status})에서 수업을 시작할 수 없습니다.")

    # 선생님은 자신의 수업만 시작 가능
    if current_user["role"] == "branch_admin" and remote_class.teacher_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="자신의 수업만 시작할 수 있습니다.")

    remote_class.status = "live"
    await db.commit()
    await db.refresh(remote_class)
    return ApiResponse(message="수업이 시작되었습니다.", data={
        "id": remote_class.id,
        "status": remote_class.status,
    })


# ============================================================
# 원격 수업 종료 (teacher / admin)
# ============================================================

@router.post("/{class_id}/end")
async def end_remote_class(
    class_id: int,
    current_user: dict = Depends(require_role("branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    if remote_class.status != "live":
        raise HTTPException(status_code=400, detail=f"현재 상태({remote_class.status})에서 수업을 종료할 수 없습니다.")

    # 선생님은 자신의 수업만 종료 가능
    if current_user["role"] == "branch_admin" and remote_class.teacher_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="자신의 수업만 종료할 수 있습니다.")

    remote_class.status = "completed"
    await db.commit()
    await db.refresh(remote_class)
    return ApiResponse(message="수업이 종료되었습니다.", data={
        "id": remote_class.id,
        "status": remote_class.status,
    })


# ============================================================
# 학생 수업 참여 (출석 기록 생성)
# ============================================================

@router.post("/{class_id}/join")
async def join_remote_class(
    class_id: int,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    # 수업 확인
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    if remote_class.status not in ("scheduled", "live"):
        raise HTTPException(status_code=400, detail="현재 참여할 수 없는 수업입니다.")

    # 이미 출석 기록이 있는지 확인
    existing = await db.execute(
        select(RemoteAttendance).where(
            RemoteAttendance.class_id == class_id,
            RemoteAttendance.student_id == current_user["id"],
            RemoteAttendance.leave_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="이미 수업에 참여 중입니다.")

    from datetime import datetime, timezone
    attendance = RemoteAttendance(
        class_id=class_id,
        student_id=current_user["id"],
        join_at=datetime.now(timezone.utc),
        status="attended",
    )
    db.add(attendance)
    await db.commit()
    await db.refresh(attendance)
    return ApiResponse(message="수업에 참여했습니다.", data={
        "id": attendance.id,
        "class_id": attendance.class_id,
        "student_id": attendance.student_id,
        "join_at": str(attendance.join_at) if attendance.join_at else None,
        "status": attendance.status,
    })


# ============================================================
# 학생 수업 퇴장 (leave_at 업데이트)
# ============================================================

@router.post("/{class_id}/leave")
async def leave_remote_class(
    class_id: int,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    # 수업 확인
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    # 활성 출석 기록 찾기
    existing = await db.execute(
        select(RemoteAttendance).where(
            RemoteAttendance.class_id == class_id,
            RemoteAttendance.student_id == current_user["id"],
            RemoteAttendance.leave_at.is_(None),
        )
    )
    attendance = existing.scalar_one_or_none()
    if not attendance:
        raise HTTPException(status_code=400, detail="참여 중인 수업이 없습니다.")

    from datetime import datetime, timezone
    attendance.leave_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(attendance)
    return ApiResponse(message="수업에서 퇴장했습니다.", data={
        "id": attendance.id,
        "class_id": attendance.class_id,
        "student_id": attendance.student_id,
        "join_at": str(attendance.join_at) if attendance.join_at else None,
        "leave_at": str(attendance.leave_at) if attendance.leave_at else None,
        "status": attendance.status,
    })


# ============================================================
# 출석 목록 조회
# ============================================================

@router.get("/{class_id}/attendance")
async def get_remote_class_attendance(
    class_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 수업 확인
    result = await db.execute(select(RemoteClass).where(RemoteClass.id == class_id))
    remote_class = result.scalar_one_or_none()
    if not remote_class:
        raise HTTPException(status_code=404, detail="원격 수업을 찾을 수 없습니다.")

    query = select(RemoteAttendance).where(RemoteAttendance.class_id == class_id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(RemoteAttendance.join_at.asc())
    result = await db.execute(query)
    records = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": r.id,
            "class_id": r.class_id,
            "student_id": r.student_id,
            "join_at": str(r.join_at) if r.join_at else None,
            "leave_at": str(r.leave_at) if r.leave_at else None,
            "status": r.status,
        } for r in records],
        total=total,
        page=1,
        per_page=total if total > 0 else 20,
        total_pages=1,
    )
