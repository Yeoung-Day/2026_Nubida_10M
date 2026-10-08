"""
👨‍🏫 원장 관리 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, or_
from datetime import date, datetime

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import (
    User, Course, ClassSchedule, Enrollment, Exam, Score, Attendance,
    SchoolClass, ClassCourse, ClassStudent, LearningProgress, CourseMaterial,
    EducationProgram, ProgramChapter, ProgramAssignment,
    Revenue, RevenueApproval, Payment, Branch, WithdrawnStudent,
    Academy, AcademyCourse, TuitionPayment, AppSetting,
)
from app.schemas import ApiResponse, PaginatedResponse, DirectorReportCreate

router = APIRouter(prefix="/director", tags=["원장 관리"])


# ============================================================
# 헬퍼: 학급-학생-강좌 연결 동기화 → Enrollment 자동 생성/취소
# ============================================================
async def _sync_enrollments_for_class(
    db: AsyncSession,
    class_id: int,
    *,
    added_student_ids: list[int] = None,
    removed_student_ids: list[int] = None,
    added_course_ids: list[int] = None,
    removed_course_ids: list[int] = None,
):
    """
    ClassStudent / ClassCourse 변경 시 Enrollment를 자동 동기화.
    - 학생이 학급에 추가되면 → 학급의 모든 강좌에 Enrollment 생성
    - 학생이 학급에서 제거되면 → 해당 학급 강좌의 Enrollment 취소
    - 강좌가 학급에 연결되면 → 학급의 모든 학생에게 Enrollment 생성
    - 강좌가 학급에서 제거되면 → 해당 학생들의 Enrollment 취소
    """
    from datetime import datetime, timezone

    # 1. 동기화 대상 조합 계산
    target_pairs = set()

    # 추가된 학생 × 학급의 모든 강좌
    if added_student_ids:
        course_result = await db.execute(
            select(ClassCourse.course_id).where(ClassCourse.class_id == class_id)
        )
        course_ids = [r[0] for r in course_result.all()]
        for sid in added_student_ids:
            for cid in course_ids:
                target_pairs.add((sid, cid))

    # 추가된 강좌 × 학급의 모든 학생
    if added_course_ids:
        student_result = await db.execute(
            select(ClassStudent.student_id).where(
                ClassStudent.class_id == class_id,
                ClassStudent.status == "active",
            )
        )
        student_ids = [r[0] for r in student_result.all()]
        for cid in added_course_ids:
            for sid in student_ids:
                target_pairs.add((sid, cid))

    # 제거된 학생 × 학급의 모든 강좌 → 기존 Enrollment 취소
    if removed_student_ids:
        course_result = await db.execute(
            select(ClassCourse.course_id).where(ClassCourse.class_id == class_id)
        )
        course_ids = [r[0] for r in course_result.all()]
        for sid in removed_student_ids:
            for cid in course_ids:
                result = await db.execute(
                    select(Enrollment).where(
                        Enrollment.student_id == sid,
                        Enrollment.course_id == cid,
                    )
                )
                enr = result.scalar_one_or_none()
                if enr:
                    enr.status = "cancelled"

    # 제거된 강좌 × 학급의 모든 학생 → 기존 Enrollment 취소
    if removed_course_ids:
        student_result = await db.execute(
            select(ClassStudent.student_id).where(
                ClassStudent.class_id == class_id,
                ClassStudent.status == "active",
            )
        )
        student_ids = [r[0] for r in student_result.all()]
        for cid in removed_course_ids:
            for sid in student_ids:
                result = await db.execute(
                    select(Enrollment).where(
                        Enrollment.student_id == sid,
                        Enrollment.course_id == cid,
                    )
                )
                enr = result.scalar_one_or_none()
                if enr:
                    enr.status = "cancelled"

    # 2. 새 Enrollment 생성 또는 취소된 Enrollment 재활성화
    for sid, cid in target_pairs:
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.student_id == sid,
                Enrollment.course_id == cid,
            )
        )
        enr = result.scalar_one_or_none()
        if enr:
            # 이미 존재하면 status를 active로 재활성화
            if enr.status != "active":
                enr.status = "active"
        else:
            # 없으면 새로 생성
            enr = Enrollment(
                student_id=sid,
                course_id=cid,
                status="active",
            )
            db.add(enr)


# ============================================================
# 대시보드
# ============================================================


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    user_id = current_user.get("id", 0)
    is_director = current_user.get("role") == "director"
    class_filter = [SchoolClass.branch_id == branch_id, SchoolClass.status == "active"]
    class_filter_exams = [SchoolClass.branch_id == branch_id]
    if is_director:
        class_filter.append(SchoolClass.director_id == user_id)
        class_filter_exams.append(SchoolClass.director_id == user_id)
    user_id = current_user.get("id", 0)
    is_director = current_user.get("role") == "director"

    # Base class filter: by branch. If director, also by own ID for data isolation
    class_filter = [SchoolClass.branch_id == branch_id, SchoolClass.status == "active"]
    class_filter_exams = [SchoolClass.branch_id == branch_id]
    if is_director:
        class_filter.append(SchoolClass.director_id == user_id)
        class_filter_exams.append(SchoolClass.director_id == user_id)

    total_classes = (
        await db.execute(
            select(func.count(SchoolClass.id)).where(*class_filter)
        )
    ).scalar() or 0
    total_students = (
        await db.execute(
            select(func.count(ClassStudent.id))
            .join(SchoolClass, SchoolClass.id == ClassStudent.class_id)
            .where(*class_filter)
        )
    ).scalar() or 0
    total_exams = (
        await db.execute(
            select(func.count(Exam.id))
            .join(ClassCourse, ClassCourse.course_id == Exam.course_id)
            .join(SchoolClass, SchoolClass.id == ClassCourse.class_id)
            .where(*class_filter_exams)
        )
    ).scalar() or 0
    today_attendance = (
        await db.execute(
            select(func.count(Attendance.id)).where(
                func.date(Attendance.date) == func.date("now")
            )
        )
    ).scalar() or 0

    return ApiResponse(data={
        "total_classes": total_classes,
        "total_students": total_students,
        "total_exams": total_exams,
        "today_attendance": today_attendance,
        "recent_exams": [],
        "recent_activities": [],
    })


# ============================================================
# 학급 관리 (SchoolClass CRUD)
# ============================================================


@router.get("/classes")
async def get_classes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str = None,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """학급 목록"""
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    if status:
        query = query.where(SchoolClass.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(SchoolClass.id.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    classes = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": c.id,
            "name": c.name,
            "grade": c.grade,
            "branch_id": c.branch_id,
            "director_id": c.director_id,
            "status": c.status,
            "student_count": c.student_count,
            "created_at": str(c.created_at) if c.created_at else None,
        } for c in classes],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.post("/classes")
async def create_class(
    data: dict,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    if not branch_id:
        raise HTTPException(status_code=400, detail="원장 계정에 지사 정보가 없습니다.")

    school_class = SchoolClass(
        name=data.get("name", ""),
        grade=data.get("grade"),
        branch_id=branch_id,
        director_id=current_user.get("id"),
        status=data.get("status", "active"),
    )
    db.add(school_class)
    await db.commit()
    await db.refresh(school_class)
    return ApiResponse(message="학급이 생성되었습니다.", data={
        "id": school_class.id,
        "name": school_class.name,
        "grade": school_class.grade,
    })


@router.put("/classes/{class_id}")
async def update_class(
    class_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    result = await db.execute(query)
    school_class = result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    for field in ["name", "grade", "status"]:
        if field in data:
            setattr(school_class, field, data[field])
    await db.commit()
    return ApiResponse(message="학급이 수정되었습니다.")


@router.delete("/classes/{class_id}")
async def delete_class(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    result = await db.execute(query)
    school_class = result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    await db.delete(school_class)
    await db.commit()
    return ApiResponse(message="학급이 삭제되었습니다.")


# ============================================================
# 학급 → 강좌 연결 관리
# ============================================================


@router.get("/classes/{class_id}/courses")
async def get_class_courses(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class belongs to director's branch
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    school_class = cls_result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    query = (
        select(ClassCourse, Course)
        .join(Course, Course.id == ClassCourse.course_id)
        .where(ClassCourse.class_id == class_id)
    )
    result = await db.execute(query)
    rows = result.all()

    return ApiResponse(data=[{
        "link_id": cc.id,
        "course_id": course.id,
        "course_name": course.name,
        "subject": course.subject,
        "category": course.category,
        "grade_level": getattr(course, 'grade_level', ''),
        "price": float(course.price) if course.price else None,
        "status": course.status,
        "instructor": course.instructor,
        "created_at": str(cc.created_at) if cc.created_at else None,
    } for cc, course in rows])


@router.post("/classes/{class_id}/courses")
async def link_course_to_class(
    class_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    course_id = data.get("course_id")
    if not course_id:
        raise HTTPException(status_code=400, detail="course_id가 필요합니다.")

    # Check for duplicate
    existing = await db.execute(
        select(ClassCourse).where(
            ClassCourse.class_id == class_id,
            ClassCourse.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 연결된 강좌입니다.")

    link = ClassCourse(class_id=class_id, course_id=course_id)
    db.add(link)

    # 🔄 Enrollment 자동 생성 (학급의 모든 학생 × 추가된 강좌)
    await _sync_enrollments_for_class(db, class_id, added_course_ids=[course_id])

    await db.commit()
    await db.refresh(link)
    return ApiResponse(message="강좌가 학급에 연결되었습니다.", data={"id": link.id})


@router.delete("/classes/{class_id}/courses/{course_id}")
async def unlink_course_from_class(
    class_id: int,
    course_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    result = await db.execute(
        select(ClassCourse).where(
            ClassCourse.class_id == class_id,
            ClassCourse.course_id == course_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="연결된 강좌를 찾을 수 없습니다.")

    await db.delete(link)

    # 🔄 Enrollment 자동 취소 (학급의 모든 학생 × 제거된 강좌)
    await _sync_enrollments_for_class(db, class_id, removed_course_ids=[course_id])

    await db.commit()
    return ApiResponse(message="강좌 연결이 해제되었습니다.")


# ============================================================
# 학급 → 페이지(학습자료) 연결
# ============================================================


@router.get("/classes/{class_id}/materials")
async def get_class_materials(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models import ClassMaterial, CourseMaterial
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")
    result = await db.execute(
        select(CourseMaterial)
        .join(ClassMaterial, ClassMaterial.material_id == CourseMaterial.id)
        .where(ClassMaterial.class_id == class_id)
        .order_by(CourseMaterial.sort_order, CourseMaterial.id)
    )
    materials = result.scalars().all()
    return [{"id": m.id, "title": m.title, "material_type": m.material_type, "description": m.description, "course_id": m.course_id, "file_url": m.file_url, "embed_url": m.embed_url} for m in materials]


@router.post("/classes/{class_id}/materials")
async def link_material_to_class(
    class_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models import ClassMaterial, CourseMaterial
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")
    material = await db.get(CourseMaterial, data["material_id"])
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    existing = await db.execute(
        select(ClassMaterial).where(ClassMaterial.class_id == class_id, ClassMaterial.material_id == data["material_id"])
    )
    if existing.scalar_one_or_none():
        return ApiResponse(message="이미 학급에 연결된 자료입니다.")
    link = ClassMaterial(class_id=class_id, material_id=data["material_id"])
    db.add(link)
    await db.commit()
    return ApiResponse(message="자료가 학급에 연결되었습니다.")


@router.delete("/classes/{class_id}/materials/{material_id}")
async def unlink_material_from_class(
    class_id: int,
    material_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models import ClassMaterial
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")
    result = await db.execute(
        select(ClassMaterial).where(ClassMaterial.class_id == class_id, ClassMaterial.material_id == material_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="연결된 자료를 찾을 수 없습니다.")
    await db.delete(link)
    await db.commit()
    return ApiResponse(message="자료 연결이 해제되었습니다.")


# ============================================================
# 학급 → 학생 관리
# ============================================================


@router.get("/classes/{class_id}/students")
async def get_class_students(
    class_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("director", "admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    query = (
        select(User, ClassStudent)
        .join(ClassStudent, ClassStudent.student_id == User.id)
        .where(ClassStudent.class_id == class_id, ClassStudent.status == "active")
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(User.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    return PaginatedResponse(
        data=[{
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "username": user.username,
            "enrolled_at": str(cs.enrolled_at) if cs.enrolled_at else None,
            "status": cs.status,
        } for user, cs in rows],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.post("/classes/{class_id}/students")
async def add_students_to_class(
    class_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    school_class = cls_result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    student_ids = data.get("student_ids", [])
    if not student_ids:
        raise HTTPException(status_code=400, detail="student_ids가 필요합니다.")

    added = 0
    skipped = 0
    for sid in student_ids:
        # Check if already in class
        existing = await db.execute(
            select(ClassStudent).where(
                ClassStudent.class_id == class_id,
                ClassStudent.student_id == sid,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        cs = ClassStudent(class_id=class_id, student_id=sid, status="active")
        db.add(cs)
        added += 1

        # ✨ 학생의 branch_id가 없으면(자체회원가입 등) 원장의 지사로 자동 설정
        stu_result = await db.execute(select(User).where(User.id == sid))
        student = stu_result.scalar_one_or_none()
        if student and student.branch_id is None:
            student.branch_id = branch_id
        # ✨ 재배정 보호: 퇴소(반이동)로 is_active=False 된 경우 재배정 시 다시 활성화 + 원장 연결 보장
        if student:
            if not student.is_active:
                student.is_active = True
            if student.withdrawn_at is not None:
                # 탈퇴했던 학생이 재배정되면 탈퇴 표시도 해제
                student.withdrawn_at = None
            if student.director_id is None or student.director_id == 0:
                student.director_id = current_user.get("id")

    # Update student_count on SchoolClass
    count_result = await db.execute(
        select(func.count(ClassStudent.id)).where(
            ClassStudent.class_id == class_id,
            ClassStudent.status == "active",
        )
    )
    school_class.student_count = count_result.scalar() or 0

    # 🔄 Enrollment 자동 생성 (추가된 학생 × 학급의 모든 강좌)
    if added > 0:
        await _sync_enrollments_for_class(db, class_id, added_student_ids=student_ids)

    await db.commit()
    return ApiResponse(
        message=f"{added}명이 추가되었습니다. (중복: {skipped}명)",
        data={"added": added, "skipped": skipped},
    )


@router.delete("/classes/{class_id}/students/{student_id}")
async def remove_student_from_class(
    class_id: int,
    student_id: int,
    reason: str = Query("", description="퇴소 사유"),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    cls_result = await db.execute(query)
    school_class = cls_result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    result = await db.execute(
        select(ClassStudent).where(
            ClassStudent.class_id == class_id,
            ClassStudent.student_id == student_id,
        )
    )
    cs = result.scalar_one_or_none()
    if not cs:
        raise HTTPException(status_code=404, detail="학급에 등록된 학생이 아닙니다.")

    await db.delete(cs)

    # 🔄 Enrollment 자동 취소
    await _sync_enrollments_for_class(db, class_id, removed_student_ids=[student_id])

    # 📝 탈퇴 히스토리 기록
    student = await db.get(User, student_id)
    branch = None
    if branch_id:
        try:
            branch = await db.get(Branch, branch_id)
        except Exception:
            branch = None
    withdrawn = WithdrawnStudent(
        student_id=student_id,
        student_name=student.name if student else "",
        student_username=student.username if student else "",
        student_email=student.email if student else "",
        course_name=school_class.name,
        branch_name=branch.name if branch else "",
        director_name=current_user.get("name", ""),
        reason=reason or "학급 제거",
        withdrawn_by=current_user["id"],
    )
    db.add(withdrawn)

    # Update student_count
    count_result = await db.execute(
        select(func.count(ClassStudent.id)).where(
            ClassStudent.class_id == class_id,
            ClassStudent.status == "active",
        )
    )
    school_class.student_count = count_result.scalar() or 0

    # 🚫 학생 계정 비활성화 제거 (퇴소는 반 이동이므로 계정과 원장 연결은 유지)
    # NOTE: is_active 는 절대 False 로 설정하지 않는다. 퇴소(=반이동) 여전히 로그인과 재배정이 가능해야 함.
    # student = await db.get(User, student_id)
    # if student:
    #     student.is_active = False

    await db.commit()
    return ApiResponse(message="학생이 학급에서 제거되었습니다(반 이동). 학생 계정과 원장 연결은 유지됩니다.")


@router.post("/classes/{class_id}/students/transfer")
async def transfer_student_to_class(
    class_id: int,
    student_id: int = Query(..., description="이동할 학생 ID"),
    target_class_id: int = Query(..., description="이동 대상 학급 ID (-1: 대기/반 미배정)"),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 — 학생을 다른 학급으로 이동 또는 대기 상태로 전환"""
    branch_id = current_user.get("branch_id", 0)

    # 현재 학급 확인
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    cls_result = await db.execute(query)
    school_class = cls_result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="현재 학급을 찾을 수 없습니다.")

    # 현재 학급에서 학생 제거
    result = await db.execute(
        select(ClassStudent).where(
            ClassStudent.class_id == class_id,
            ClassStudent.student_id == student_id,
        )
    )
    cs = result.scalar_one_or_none()
    if cs:
        await db.delete(cs)
        await _sync_enrollments_for_class(db, class_id, removed_student_ids=[student_id])

    if target_class_id == -1:
        # ⏸️ 대기 처리: 학급에서 제거만, 계정 유지, WithdrawnStudent 기록 없음
        for cid in [class_id]:
            cl = school_class
            cnt = await db.execute(
                select(func.count(ClassStudent.id)).where(
                    ClassStudent.class_id == cid,
                    ClassStudent.status == "active",
                )
            )
            cl.student_count = cnt.scalar() or 0
        await db.commit()
        student = await db.get(User, student_id)
        student_name = student.name if student else f"ID:{student_id}"
        return ApiResponse(message=f"{student_name} 님이 [{school_class.name}]에서 제외되어 대기 상태가 되었습니다.")

    # 대상 학급 확인
    tgt_query = select(SchoolClass).where(SchoolClass.id == target_class_id, SchoolClass.branch_id == branch_id)
    tgt_result = await db.execute(tgt_query)
    target_class = tgt_result.scalar_one_or_none()
    if not target_class:
        raise HTTPException(status_code=404, detail="대상 학급을 찾을 수 없습니다.")
    dup = await db.execute(
        select(ClassStudent).where(
            ClassStudent.class_id == target_class_id,
            ClassStudent.student_id == student_id,
        )
    )
    if not dup.scalar_one_or_none():
        db.add(ClassStudent(class_id=target_class_id, student_id=student_id))
        await _sync_enrollments_for_class(db, target_class_id, added_student_ids=[student_id])

    # 학생 카운트 업데이트
    for cid in [class_id, target_class_id]:
        cl = school_class if cid == class_id else target_class
        cnt = await db.execute(
            select(func.count(ClassStudent.id)).where(
                ClassStudent.class_id == cid,
                ClassStudent.status == "active",
            )
        )
        cl.student_count = cnt.scalar() or 0

    await db.commit()

    student = await db.get(User, student_id)
    student_name = student.name if student else f"ID:{student_id}"
    return ApiResponse(message=f"{student_name} 님이 [{school_class.name}] → [{target_class.name}](으)로 이동되었습니다.")


@router.get("/classes/{class_id}/attendance")
async def get_class_attendance(
    class_id: int,
    date_str: str = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    # Get students in this class
    student_ids_subq = (
        select(ClassStudent.student_id)
        .where(ClassStudent.class_id == class_id, ClassStudent.status == "active")
    ).subquery()

    # Get schedules linked via ClassCourse → course → ClassSchedule
    schedule_subq = (
        select(ClassSchedule.id)
        .join(ClassCourse, ClassCourse.course_id == ClassSchedule.course_id)
        .where(ClassCourse.class_id == class_id)
    ).subquery()

    query = (
        select(Attendance, User)
        .join(User, User.id == Attendance.student_id)
        .where(
            Attendance.student_id.in_(select(student_ids_subq.c.student_id)),
            or_(Attendance.schedule_id.in_(select(schedule_subq.c.id)), Attendance.schedule_id.is_(None)),
        )
    )
    if date_str:
        query = query.where(Attendance.date == date_str)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Attendance.date.desc(), User.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    return PaginatedResponse(
        data=[{
            "id": r.id,
            "student_id": r.student_id,
            "student_name": user.name,
            "schedule_id": r.schedule_id,
            "date": str(r.date),
            "status": r.status,
        } for r, user in rows],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/students/available")
async def get_available_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    해당 지사의 모든 학생 중 아직 어떤 SchoolClass에도 속하지 않은 학생 목록
    """
    branch_id = current_user.get("branch_id", 0)

    # Students already in a class at this branch (exclude from available list)
    class_filter = [SchoolClass.branch_id == branch_id]
    if current_user.get("role") == "director":
        class_filter.append(SchoolClass.director_id == current_user["id"])

    subquery = (
        select(ClassStudent.student_id)
        .distinct()
        .join(SchoolClass, SchoolClass.id == ClassStudent.class_id)
        .where(*class_filter)
    ).subquery()

    query = (
        select(User)
        .distinct()
        .outerjoin(Enrollment, Enrollment.student_id == User.id)
        .outerjoin(Course, Course.id == Enrollment.course_id)
        .where(
            User.role == "student",
            User.is_active == True,
            User.id.notin_(select(subquery.c.student_id)),
            or_(
                User.branch_id == branch_id,
                Course.branch_id == branch_id,
                User.branch_id.is_(None),
            ),
        )
    )
    if current_user.get("role") == "director":
        query = query.where(User.director_id == current_user["id"])

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(User.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    students = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": s.id, "name": s.name, "email": s.email,
            "phone": s.phone, "username": s.username,
            "registration_code": s.registration_code,
        } for s in students],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/students/all")
async def get_all_branch_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """해당 지사의 모든 승인된 학생 목록"""
    branch_id = current_user.get("branch_id", 0)
    query = select(User).where(
        User.role == "student",
        User.is_active == True,
    )
    if branch_id:
        query = query.where(User.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(User.director_id == current_user["id"])
    query = query.order_by(User.created_at.desc())
    
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page-1)*per_page).limit(per_page))).scalars().all()
    
    return ApiResponse(
        data=[{
            "id": s.id, "name": s.name, "username": s.username,
            "email": s.email, "phone": s.phone,
            "registration_code": s.registration_code,
            "created_at": str(s.created_at) if s.created_at else None,
            "is_active": s.is_active,
        } for s in rows],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/parents/all")
async def get_all_branch_parents(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """해당 지사의 모든 승인된 학부모 목록"""
    branch_id = current_user.get("branch_id", 0)
    query = select(User).where(
        User.role == "parent",
        User.is_active == True,
    )
    if branch_id:
        query = query.where(User.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(User.director_id == current_user["id"])
    query = query.order_by(User.created_at.desc())
    
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(query.offset((page-1)*per_page).limit(per_page))).scalars().all()
    
    return ApiResponse(
        data=[{
            "id": p.id, "name": p.name, "username": p.username,
            "email": p.email, "phone": p.phone,
            "registration_code": p.registration_code,
            "created_at": str(p.created_at) if p.created_at else None,
            "is_active": p.is_active,
        } for p in rows],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/folders/available")
async def get_available_folders(
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models import CourseFolder, CourseFolderItem, CourseMaterial, Academy, AcademyCourse
    branch_id = current_user.get("branch_id", 0)

    # 해당 학원에 연결된 강좌 ID 목록 (branch_id → academy → academy_courses)
    academy_course_ids = set()
    if branch_id:
        # 현재 사용자의 branch_id로 Academy 찾기
        academy_result = await db.execute(
            select(Academy.id).where(Academy.branch_id == branch_id)
        )
        academy_ids = [row[0] for row in academy_result.all()]
        if academy_ids:
            ac_result = await db.execute(
                select(AcademyCourse.course_id).where(
                    AcademyCourse.academy_id.in_(academy_ids),
                    AcademyCourse.is_active == True,
                )
            )
            academy_course_ids = {row[0] for row in ac_result.all()}

    # 학원 연결 강좌가 없으면 빈 결과 반환 (연결 안 된 강좌 노출 방지)
    if branch_id and not academy_course_ids:
        return ApiResponse(data=[])

    result = await db.execute(
        select(CourseFolder).order_by(CourseFolder.sort_order, CourseFolder.id)
    )
    all_folders = result.scalars().all()
    folder_map = {}
    roots = []
    for f in all_folders:
        entry = {"id": f.id, "name": f.name, "parent_id": f.parent_id, "children": [], "courses": [], "pages": []}
        folder_map[f.id] = entry
        if f.parent_id is None:
            roots.append(entry)
    for f in all_folders:
        if f.parent_id and f.parent_id in folder_map:
            folder_map[f.parent_id]["children"].append(folder_map[f.id])

    # 연결된 강좌만 필터링
    courses_query = (
        select(CourseFolderItem.folder_id, Course)
        .join(Course, Course.id == CourseFolderItem.course_id)
        .where(Course.status == "active")
        .order_by(CourseFolderItem.sort_order, Course.name)
    )
    if academy_course_ids:
        courses_query = courses_query.where(Course.id.in_(academy_course_ids))
    courses_result = await db.execute(courses_query)
    course_ids_by_folder = {}
    for folder_id, course in courses_result.all():
        if folder_id in folder_map:
            folder_map[folder_id]["courses"].append({
                "id": course.id, "name": course.name, "subject": course.subject,
                "category": course.category, "instructor": course.instructor,
                "price": float(course.price) if course.price else None,
            })
            course_ids_by_folder.setdefault(folder_id, set()).add(course.id)
    if course_ids_by_folder:
        all_course_ids = set()
        for cids in course_ids_by_folder.values():
            all_course_ids.update(cids)
        materials_result = await db.execute(
            select(CourseMaterial)
            .where(CourseMaterial.course_id.in_(all_course_ids))
            .where(CourseMaterial.is_active == True)
            .order_by(CourseMaterial.sort_order, CourseMaterial.id)
        )
        all_materials = materials_result.scalars().all()
        material_by_course = {}
        for m in all_materials:
            material_by_course.setdefault(m.course_id, []).append({
                "id": m.id, "title": m.title, "description": m.description,
                "material_type": m.material_type, "course_id": m.course_id,
            })
        for folder_id, cids in course_ids_by_folder.items():
            folder_pages = []
            for cid in cids:
                if cid in material_by_course:
                    folder_pages.extend(material_by_course[cid])
            if folder_pages:
                folder_map[folder_id]["pages"] = folder_pages

    # 빈 폴더 제거 (courses와 pages가 모두 없는 폴더는 제외)
    def _prune_empty(folder_list):
        i = 0
        while i < len(folder_list):
            f = folder_list[i]
            if f["children"]:
                f["children"] = _prune_empty(f["children"])
            has_courses = len(f["courses"]) > 0
            has_pages = len(f.get("pages", [])) > 0
            has_children = len(f["children"]) > 0
            if not has_courses and not has_pages and not has_children:
                folder_list.pop(i)
            else:
                i += 1
        return folder_list

    roots = _prune_empty(roots)
    return ApiResponse(data=roots)


@router.post("/classes/{class_id}/attendance")
async def auto_generate_attendance(
    class_id: int,
    data: dict = None,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    학급의 모든 학생에 대해 오늘 날짜로 출석 기록을 자동 생성합니다.
    선택적으로 특정 날짜(date)와 기본 상태(status)를 지정할 수 있습니다.
    """
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    target_date = date.today()
    if data and data.get("date"):
        try:
            target_date = datetime.strptime(str(data["date"]), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    default_status = (data or {}).get("status", "present")

    # Get all active students in class
    students_result = await db.execute(
        select(ClassStudent).where(
            ClassStudent.class_id == class_id,
            ClassStudent.status == "active",
        )
    )
    class_students = students_result.scalars().all()

    if not class_students:
        raise HTTPException(status_code=400, detail="학급에 등록된 학생이 없습니다.")

    # Get all schedules linked to this class's courses
    schedules_result = await db.execute(
        select(ClassSchedule)
        .join(ClassCourse, ClassCourse.course_id == ClassSchedule.course_id)
        .where(ClassCourse.class_id == class_id)
    )
    schedules = schedules_result.scalars().all()

    created = 0
    skipped = 0
    seen_keys = set()  # ★ in-memory dedup (student_id, schedule_id_or_null, date)

    if not schedules:
        # ★ 시간표 없음 → 학생별 1건씩만 생성 (schedule_id=null)
        for cs in class_students:
            dedup = (cs.student_id, -1, str(target_date))
            if dedup in seen_keys:
                skipped += 1
                continue
            seen_keys.add(dedup)
            existing = await db.execute(
                select(Attendance).where(
                    Attendance.student_id == cs.student_id,
                    Attendance.date == target_date,
                    Attendance.schedule_id.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            att = Attendance(
                student_id=cs.student_id,
                schedule_id=None,
                date=target_date,
                status=default_status,
            )
            db.add(att)
            created += 1
    else:
        for cs in class_students:
            for schedule in schedules:
                # ★ in-memory dedup
                dedup = (cs.student_id, schedule.id, str(target_date))
                if dedup in seen_keys:
                    skipped += 1
                    continue
                seen_keys.add(dedup)
                # Check for duplicate
                existing = await db.execute(
                    select(Attendance).where(
                        Attendance.student_id == cs.student_id,
                        Attendance.schedule_id == schedule.id,
                        Attendance.date == target_date,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                att = Attendance(
                    student_id=cs.student_id,
                    schedule_id=schedule.id,
                    date=target_date,
                    status=default_status,
                )
                db.add(att)
                created += 1

    await db.commit()
    return ApiResponse(
        message=f"출석 기록이 생성되었습니다. (생성: {created}, 중복: {skipped})",
        data={"created": created, "skipped": skipped, "date": str(target_date)},
    )


@router.post("/classes/{class_id}/attendance/auto")
async def auto_generate_attendance_today(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    오늘 날짜의 출석부를 자동 생성합니다.
    GET 방식으로 프론트에서 쉽게 호출 가능.
    """
    branch_id = current_user.get("branch_id", 0)
    # Verify class
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    cls_result = await db.execute(query)
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    target_date = date.today()

    # Get all active students
    students_result = await db.execute(
        select(ClassStudent).where(
            ClassStudent.class_id == class_id,
            ClassStudent.status == "active",
        )
    )
    class_students = students_result.scalars().all()

    # Get all schedules
    schedules_result = await db.execute(
        select(ClassSchedule)
        .join(ClassCourse, ClassCourse.course_id == ClassSchedule.course_id)
        .where(ClassCourse.class_id == class_id)
    )
    schedules = schedules_result.scalars().all()

    created = 0
    skipped = 0

    if not class_students:
        raise HTTPException(status_code=400, detail="학급에 등록된 학생이 없습니다.")

    if not schedules:
        # ★ 시간표 없음 → 학생별 1건씩만 생성 (schedule_id=null)
        for cs in class_students:
            existing = await db.execute(
                select(Attendance).where(
                    Attendance.student_id == cs.student_id,
                    Attendance.date == target_date,
                    Attendance.schedule_id.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            att = Attendance(
                student_id=cs.student_id,
                schedule_id=None,
                date=target_date,
                status="present",
            )
            db.add(att)
            created += 1
    else:
        for cs in class_students:
            for schedule in schedules:
                existing = await db.execute(
                    select(Attendance).where(
                        Attendance.student_id == cs.student_id,
                        Attendance.schedule_id == schedule.id,
                        Attendance.date == target_date,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue
                att = Attendance(
                    student_id=cs.student_id,
                    schedule_id=schedule.id,
                    date=target_date,
                    status="present",
                )
                db.add(att)
                created += 1

    await db.commit()

    # Return the attendance records for today
    student_ids = [cs.student_id for cs in class_students]

    records_query = (
        select(Attendance, User)
        .join(User, User.id == Attendance.student_id)
        .where(
            Attendance.date == target_date,
            Attendance.student_id.in_(student_ids),
        )
        .order_by(User.name)
    )
    result = await db.execute(records_query)
    rows = result.all()

    return ApiResponse(data={
        "date": str(target_date),
        "records": [{
            "id": r.id,
            "student_id": r.student_id,
            "student_name": user.name,
            "schedule_id": r.schedule_id,
            "status": r.status,
        } for r, user in rows],
        "created": created,
        "skipped": skipped,
    })


# ============================================================
# 성적 관리
# ============================================================

@router.get("/scores")
async def get_scores(
    course_id: int = None,
    exam_id: int = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("director", "teacher", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Score)
    if current_user.get("role") == "director":
        query = query.join(Exam, Exam.id == Score.exam_id)
        query = query.join(ClassCourse, ClassCourse.course_id == Exam.course_id)
        query = query.join(SchoolClass, SchoolClass.id == ClassCourse.class_id)
        query = query.where(SchoolClass.director_id == current_user["id"])
    if exam_id:
        query = query.where(Score.exam_id == exam_id)
    elif course_id:
        query = query.join(Exam, Exam.id == Score.exam_id).where(Exam.course_id == course_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Score.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    scores = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": s.id, "student_id": s.student_id, "exam_id": s.exam_id,
            "score": float(s.score) if s.score else None,
            "grade": s.grade, "feedback": s.feedback,
        } for s in scores],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.post("/scores")
async def create_score(
    data: dict,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Score).where(
            Score.student_id == data["student_id"],
            Score.exam_id == data["exam_id"],
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="해당 시험의 성적이 이미 입력되었습니다.")

    score = Score(
        student_id=data["student_id"],
        exam_id=data["exam_id"],
        score=data.get("score"),
        feedback=data.get("feedback"),
    )
    db.add(score)
    await db.commit()
    await db.refresh(score)
    return ApiResponse(message="성적이 입력되었습니다.", data={"id": score.id})


@router.put("/scores/{score_id}")
async def update_score(
    score_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Score).where(Score.id == score_id))
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="성적을 찾을 수 없습니다.")

    for field in ["score", "feedback", "grade"]:
        if field in data:
            setattr(score, field, data[field])
    await db.commit()
    return ApiResponse(message="성적이 수정되었습니다.")


# ============================================================
# 시험 관리
# ============================================================

@router.get("/exams")
async def get_exams(
    course_id: int = None,
    current_user: dict = Depends(require_role("director", "teacher", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Exam)
    if current_user.get("role") == "director":
        query = query.join(ClassCourse, ClassCourse.course_id == Exam.course_id)
        query = query.join(SchoolClass, SchoolClass.id == ClassCourse.class_id)
        query = query.where(SchoolClass.director_id == current_user["id"])
    if course_id:
        query = query.where(Exam.course_id == course_id)
    query = query.order_by(Exam.exam_date.desc())
    result = await db.execute(query)
    exams = result.scalars().all()

    return ApiResponse(data=[{
        "id": e.id, "course_id": e.course_id, "title": e.title,
        "exam_date": str(e.exam_date) if e.exam_date else None,
        "max_score": float(e.max_score) if e.max_score else None,
        "exam_type": e.exam_type,
    } for e in exams])


@router.post("/exams")
async def create_exam(
    data: dict,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    # 프론트엔드 필드명 매핑 (pages-director.js saveExam())
    # {name, class_id, subject, exam_date, max_score, description}

    # class_id가 주어지면 class_schedules에서 course_id 조회
    course_id = data.get("course_id")
    class_id = data.get("class_id")
    if not course_id and class_id:
        cls_result = await db.execute(
            select(ClassSchedule).where(ClassSchedule.id == class_id)
        )
        cls = cls_result.scalar_one_or_none()
        if cls:
            course_id = cls.course_id

    if not course_id:
        course_id = 2  # 기본 course_id (2 = 첫 번째 강좌)

    # exam_date 문자열 → date 객체 변환
    exam_date = None
    raw_date = data.get("exam_date")
    if raw_date:
        try:
            if isinstance(raw_date, str):
                exam_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            else:
                exam_date = raw_date
        except (ValueError, TypeError):
            exam_date = None

    exam = Exam(
        course_id=course_id,
        title=data.get("name") or data.get("title", "시험"),
        exam_date=exam_date,
        max_score=data.get("max_score"),
        exam_type=data.get("subject") or data.get("exam_type", "quiz"),
    )
    db.add(exam)
    await db.commit()
    await db.refresh(exam)
    return ApiResponse(message="시험이 생성되었습니다.", data={"id": exam.id})


# ============================================================
# 학생 상세
# ============================================================

@router.get("/students/{student_id}")
async def get_student_detail(
    student_id: int,
    current_user: dict = Depends(require_role("director", "teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")

    # 원장: 자신의 학생만 조회 가능
    if current_user.get("role") == "director" and student.director_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="해당 학생에 접근할 수 없습니다.")

    # 수강 중인 강좌
    courses_result = await db.execute(
        select(Course).join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == student_id, Enrollment.status == "active")
    )
    courses = courses_result.scalars().all()

    # 속한 학급
    classes_result = await db.execute(
        select(SchoolClass)
        .join(ClassStudent, ClassStudent.class_id == SchoolClass.id)
        .where(ClassStudent.student_id == student_id, ClassStudent.status == "active")
    )
    school_classes = classes_result.scalars().all()

    return ApiResponse(data={
        "id": student.id, "name": student.name, "email": student.email,
        "phone": student.phone, "created_at": str(student.created_at),
        "enrolled_courses": [{"id": c.id, "name": c.name, "subject": c.subject, "category": c.category} for c in courses],
        "school_classes": [{"id": c.id, "name": c.name, "grade": c.grade} for c in school_classes],
    })


# ============================================================
# 학습 진도 추적
# ============================================================

@router.get("/classes/{class_id}/progress")
async def get_class_progress(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
):
    """학급 내 모든 학생의 강좌별 학습 진도"""
    branch_id = current_user.get("branch_id", 0)

    # 학생 목록
    students_result = await db.execute(
        select(User)
        .join(ClassStudent, ClassStudent.student_id == User.id)
        .where(ClassStudent.class_id == class_id, ClassStudent.status == "active")
        .order_by(User.name)
    )
    students = students_result.scalars().all()

    # 학급에 연결된 강좌
    courses_result = await db.execute(
        select(Course)
        .join(ClassCourse, ClassCourse.course_id == Course.id)
        .where(ClassCourse.class_id == class_id, Course.status == "active")
    )
    courses = courses_result.scalars().all()

    course_data = []
    for c in courses:
        # 전체 자료 수
        total = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == c.id, CourseMaterial.is_active == True)
        )).scalar() or 0

        student_progress = []
        for s in students:
            completed = (await db.execute(
                select(func.count(LearningProgress.id))
                .where(
                    LearningProgress.student_id == s.id,
                    LearningProgress.course_id == c.id,
                    LearningProgress.is_completed == True,
                )
            )).scalar() or 0
            in_progress = (await db.execute(
                select(func.count(LearningProgress.id))
                .where(
                    LearningProgress.student_id == s.id,
                    LearningProgress.course_id == c.id,
                    LearningProgress.is_completed == False,
                    LearningProgress.progress_percent > 0,
                )
            )).scalar() or 0

            student_progress.append({
                "student_id": s.id, "student_name": s.name,
                "completed": completed, "in_progress": in_progress,
                "completion_rate": round((completed / total * 100)) if total > 0 else 0,
            })

        course_data.append({
            "course_id": c.id, "course_name": c.name,
            "total_materials": total,
            "students": student_progress,
        })

    return ApiResponse(data={
        "class_id": class_id,
        "total_students": len(students),
        "total_courses": len(courses),
        "courses": course_data,
    })


# ============================================================
# 출결 관리 (전체)
# ============================================================

@router.get("/attendance")
async def get_attendance(
    class_id: int = None,
    date: str = None,
    status: str = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("director", "teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)

    query = (
        select(Attendance, User.name.label("student_name"), SchoolClass.name.label("class_name"))
        .join(User, User.id == Attendance.student_id)
        .outerjoin(ClassStudent, ClassStudent.student_id == Attendance.student_id)
        .outerjoin(SchoolClass, SchoolClass.id == ClassStudent.class_id)
        .where(SchoolClass.branch_id == branch_id)
    )
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])

    if class_id:
        query = query.where(ClassStudent.class_id == class_id)
    if date:
        query = query.where(Attendance.date == date)
    if status:
        query = query.where(Attendance.status == status)

    query = query.order_by(Attendance.date.desc(), User.name)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    return PaginatedResponse(
        data=[{
            "id": r.id,
            "student_id": r.student_id,
            "student_name": sname or "-",
            "class_name": cname or "-",
            "schedule_id": r.schedule_id,
            "date": str(r.date),
            "status": r.status,
            "remark": r.remark or "",
        } for r, sname, cname in rows],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.post("/attendance")
async def mark_attendance(
    data: list[dict],
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    """일괄 출석 체크 (멱등: 중복 요청 방지)"""
    from datetime import date as date_type, datetime
    created = []
    seen = set()  # ★ in-memory dedup set for within-request
    
    for entry in data:
        s_id = entry.get("schedule_id")
        # 날짜 변환 (string → date 객체)
        entry_date = entry.get("date")
        if isinstance(entry_date, str):
            entry_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
        
        # ★ in-memory dedup key: (student_id, schedule_id or -1, date_str)
        dedup_key = (entry["student_id"], s_id or -1, str(entry_date))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        
        # DB 중복 확인: schedule_id가 있으면 schedule도 검사, 없으면 student+date만 검사
        dup_filters = [Attendance.student_id == entry["student_id"], Attendance.date == entry_date]
        if s_id is not None:
            dup_filters.append(Attendance.schedule_id == s_id)
        else:
            dup_filters.append(Attendance.schedule_id.is_(None))
            
        existing = await db.execute(
            select(Attendance).where(*dup_filters)
        )
        if existing.scalar_one_or_none():
            continue  # 이미 기록 있음
        
        att = Attendance(
            student_id=entry["student_id"],
            schedule_id=s_id,
            date=entry_date,
            status=entry.get("status", "present"),
            remark=entry.get("remark", "") or "",
        )
        db.add(att)
        created.append(att)

    await db.commit()
    return ApiResponse(message=f"{len(created)}명 출석이 기록되었습니다.")


# ============================================================
# 학급 보고서
# ============================================================

@router.get("/reports/class/{class_id}")
async def get_class_report(
    class_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id", 0)
    query = select(SchoolClass).where(SchoolClass.id == class_id, SchoolClass.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(SchoolClass.director_id == current_user["id"])
    result = await db.execute(query)
    school_class = result.scalar_one_or_none()
    if not school_class:
        raise HTTPException(status_code=404, detail="학급을 찾을 수 없습니다.")

    # Get linked course IDs
    course_ids_result = await db.execute(
        select(ClassCourse.course_id).where(ClassCourse.class_id == class_id)
    )
    course_ids = [row[0] for row in course_ids_result.all()]

    # Average score across all linked courses
    avg_score = 0
    if course_ids:
        avg_result = await db.execute(
            select(func.coalesce(func.avg(Score.score), 0))
            .join(Exam, Exam.id == Score.exam_id)
            .where(Exam.course_id.in_(course_ids))
        )
        avg_score = avg_result.scalar() or 0

    return ApiResponse(data={
        "class_id": class_id,
        "class_name": school_class.name,
        "grade": school_class.grade,
        "student_count": school_class.student_count,
        "average_score": round(float(avg_score), 2),
    })


# ============================================================
# 시험 수정 / 삭제
# ============================================================

@router.put("/exams/{exam_id}")
async def update_exam(
    exam_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다.")
    name = data.get("name") or data.get("title")
    if name:
        exam.title = name
    if "subject" in data:
        exam.exam_type = data["subject"]
    if "exam_date" in data and data["exam_date"]:
        try:
            exam.exam_date = datetime.strptime(data["exam_date"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass
    if "max_score" in data:
        exam.max_score = data["max_score"]
    if "description" in data:
        exam.feedback = data["description"] if hasattr(exam, "feedback") else None
    if "class_id" in data:
        exam.course_id = data["class_id"]
    if "course_id" in data:
        exam.course_id = data["course_id"]
    if "status" in data:
        pass
    await db.commit()
    return ApiResponse(message="시험이 수정되었습니다.")


@router.delete("/exams/{exam_id}")
async def delete_exam(
    exam_id: int,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다.")
    await db.delete(exam)
    await db.commit()
    return ApiResponse(message="시험이 삭제되었습니다.")


# ============================================================
# 성적 삭제
# ============================================================

@router.delete("/scores/{score_id}")
async def delete_score(
    score_id: int,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Score).where(Score.id == score_id))
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="성적을 찾을 수 없습니다.")
    await db.delete(score)
    await db.commit()
    return ApiResponse(message="성적이 삭제되었습니다.")


# ============================================================
# 출결 수정 / 삭제
# ============================================================

@router.put("/attendance/{attendance_id}")
async def update_attendance(
    attendance_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="출결 기록을 찾을 수 없습니다.")
    for field in ["status", "date", "remark", "student_id", "schedule_id"]:
        if field in data:
            setattr(record, field, data[field])
    await db.commit()
    return ApiResponse(message="출결 정보가 수정되었습니다.")


@router.delete("/attendance/{attendance_id}")
async def delete_attendance(
    attendance_id: int,
    current_user: dict = Depends(require_role("director", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="출결 기록을 찾을 수 없습니다.")
    await db.delete(record)
    await db.commit()
    return ApiResponse(message="출결 기록이 삭제되었습니다.")


# ============================================================
# 회원가입 승인 관리 (원장)
# ============================================================


@router.get("/pending-students")
async def get_pending_students(
    current_user: dict = Depends(require_role("director", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    """원장 승인 대기 중인 학생/학부모 목록 (해당 원장 소속)"""
    branch_id = current_user.get("branch_id")
    if not branch_id:
        if current_user.get("role") == "super_admin":
            branch_id = 0

    target_roles = ["student", "parent"]
    query = select(User).where(
        User.role.in_(target_roles),
        User.is_active == False,
        User.withdrawn_at.is_(None),  # 탈퇴생 제외 — 승인 대기만
    )
    if branch_id and current_user.get("role") == "director":
        # 원장: 자신의 director_id로 등록된 학생만 조회
        query = query.where(User.director_id == current_user["id"])
    elif branch_id:
        query = query.where(User.branch_id == branch_id)
    result = await db.execute(query.order_by(User.created_at.desc()))
    users = result.scalars().all()

    return ApiResponse(data=[{
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "email": u.email,
        "phone": u.phone or "",
        "role": u.role,
        "branch_id": u.branch_id,
        "director_id": u.director_id,
        "registration_code": u.registration_code,
        "created_at": str(u.created_at),
    } for u in users])


@router.post("/students/{user_id}/approve")
async def approve_student(
    user_id: int,
    current_user: dict = Depends(require_role("director", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    """원장에서 회원가입 승인"""
    branch_id = current_user.get("branch_id")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    allowed_roles = {"student", "parent"}
    if target.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="원장에서 승인할 수 없는 역할입니다.")

    # director_id 기반 검증 (같은 branch 내 다른 원장의 학생 승인 방지)
    current_role = current_user.get("role")
    if current_role == "director":
        target_director_id = int(target.director_id) if target.director_id is not None else None
        current_id = int(current_user["id"])
        if target_director_id is not None and target_director_id != current_id:
            raise HTTPException(status_code=403, detail="다른 원장님의 학생은 승인할 수 없습니다.")
        if target.director_id is None:
            target.director_id = current_user["id"]

    if branch_id and target.branch_id != branch_id:
        # branch_id가 없는 학생이 원장이 보유한 branch_id로 등록 시도한 경우 자동 할당
        if target.branch_id is None:
            target.branch_id = branch_id
        else:
            raise HTTPException(status_code=403, detail="소속 지사의 사용자만 승인할 수 있습니다.")

    target.is_active = True
    target.withdrawn_at = None  # 재승인 시 탈퇴 표시 제거
    target.approved_by = current_user["id"]
    if current_role == "director":
        target.director_id = current_user["id"]
    await db.commit()

    return ApiResponse(
        message=f"{target.name}({target.username}) 님의 계정이 승인되었습니다.",
        data={"id": target.id, "is_active": True}
    )


@router.delete("/students/{user_id}/reject")
async def reject_student(
    user_id: int,
    current_user: dict = Depends(require_role("director", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    """원장에서 회원가입 거절 (사용자 삭제)"""
    branch_id = current_user.get("branch_id")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # director_id 기반 검증
    if current_user.get("role") == "director":
        target_director_id = int(target.director_id) if target.director_id is not None else None
        current_id = int(current_user["id"])
        if target_director_id is not None and target_director_id != current_id:
            raise HTTPException(status_code=403, detail="다른 원장님의 학생은 거절할 수 없습니다.")

    if branch_id and target.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="소속 지사의 사용자만 거절할 수 있습니다.")

    if target.is_active:
        raise HTTPException(status_code=400, detail="이미 승인된 사용자는 거절할 수 없습니다.")

    await db.delete(target)
    await db.commit()

    return ApiResponse(message=f"{target.name}({target.username}) 님의 가입 신청이 거절되었습니다.")


# ============================================================
# 학생 탈퇴 (완전 탈퇴)
# ============================================================


@router.delete("/students/{user_id}/withdraw")
async def withdraw_student(
    user_id: int,
    data: dict = None,
    current_user: dict = Depends(require_role("director", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장에서 학생/학부모 탈퇴 처리 (비활성화)"""
    reason = (data or {}).get("reason", "")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if current_user.get("role") == "director":
        target_director_id = int(target.director_id) if target.director_id is not None else None
        current_id = int(current_user["id"])
        if target_director_id is not None and target_director_id != current_id:
            raise HTTPException(status_code=403, detail="다른 원장님의 학생은 탈퇴 처리할 수 없습니다.")

    if not target.is_active:
        raise HTTPException(status_code=400, detail="이미 비활성화된 계정입니다.")

    from app.models import Branch, ClassStudent
    from datetime import datetime, timezone

    # 1️⃣ 학급에서 제거 (ClassStudent)
    class_student_result = await db.execute(
        select(ClassStudent).where(
            ClassStudent.student_id == user_id,
            ClassStudent.status == "active",
        )
    )
    class_students = class_student_result.scalars().all()
    removed_class_ids = []
    for cs in class_students:
        removed_class_ids.append(cs.class_id)
        cs.status = "inactive"
        cs.left_at = datetime.now(timezone.utc)

    # 2️⃣ Enrollment 취소
    enr_result = await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == user_id,
            Enrollment.status == "active",
        )
    )
    enrollments = enr_result.scalars().all()
    for enr in enrollments:
        enr.status = "cancelled"

    # 3️⃣ 학급 student_count 업데이트
    for cid in removed_class_ids:
        count_result = await db.execute(
            select(func.count(ClassStudent.id)).where(
                ClassStudent.class_id == cid,
                ClassStudent.status == "active",
            )
        )
        school_class = await db.get(SchoolClass, cid)
        if school_class:
            school_class.student_count = count_result.scalar() or 0

    target.is_active = False
    # 탈퇴 시각 기록 — 승인 대기(is_active=False, withdrawn_at=NULL)와 구분
    target.withdrawn_at = datetime.now(timezone.utc)
    # 학급명 수집
    class_names = []
    for cid in removed_class_ids:
        sc = await db.get(SchoolClass, cid)
        if sc:
            class_names.append(sc.name)
    
    branch = None
    if current_user.get("branch_id"):
        branch = await db.get(Branch, current_user["branch_id"])
    withdrawn = WithdrawnStudent(
        student_id=target.id,
        student_name=target.name or "",
        student_username=target.username or "",
        student_email=target.email,
        course_name=", ".join(class_names) if class_names else "",
        branch_name=branch.name if branch else "",
        director_name=current_user.get("name", ""),
        reason=reason or "",
        withdrawn_by=current_user["id"],
    )
    db.add(withdrawn)
    await db.commit()

    return ApiResponse(message=f"{target.name}({target.username}) 님의 계정이 탈퇴 처리되었습니다.")


# ============================================================
# 보고서 생성 및 관리
# ============================================================


@router.post("/reports")
async def create_report(
    data: dict,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """보고서 생성 — PDF 파일 생성 후 DB 저장"""
    from app.models import ReportHistory
    from app.schemas import ReportCreate
    import os
    from pathlib import Path
    from datetime import date, datetime, timezone
    import random

    report_type = data.get("report_type", "학생 성적 보고서")
    date_range_start = data.get("date_range_start")
    date_range_end = data.get("date_range_end")

    if isinstance(date_range_start, str):
        try:
            date_range_start = datetime.strptime(date_range_start[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            date_range_start = None
    if isinstance(date_range_end, str):
        try:
            date_range_end = datetime.strptime(date_range_end[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            date_range_end = None

    now = datetime.now()
    director_name = current_user.get("username", "원장")
    report_labels = {
        "학생 성적 보고서": "성적",
        "출결 현황 보고서": "출결",
        "수업 통계 보고서": "통계",
    }
    short_label = report_labels.get(report_type, "보고서")

    # 기간 문자열
    period_str = ""
    if date_range_start and date_range_end:
        period_str = f" ({date_range_start} ~ {date_range_end})"
    elif date_range_start:
        period_str = f" ({date_range_start}~)"
    elif date_range_end:
        period_str = f" (~{date_range_end})"

    title = f"{short_label} 보고서{period_str}"

    # ===== PDF 생성 (fpdf2) =====
    try:
        from fpdf import FPDF
    except ImportError:
        raise HTTPException(status_code=500, detail="PDF 라이브러리(fpdf2)가 설치되지 않았습니다.")

    from app.core.config import settings
    uploads_dir = Path(settings.UPLOADS_DIR)
    reports_dir = uploads_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%Y%m%d_%H%M%S")
    rand_suffix = random.randint(1000, 9999)
    filename = f"report_{current_user['id']}_{timestamp}_{rand_suffix}.pdf"
    filepath = reports_dir / filename

    # ── 폰트 로드 ──
    FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"

    class PDF(FPDF):
        ACCENT = (8, 145, 178)        # #0891B2 teal
        ACCENT_DARK = (6, 111, 138)   # #066F8A
        BG_LIGHT = (236, 254, 255)    # #ECFEFF
        TEXT_MAIN = (30, 41, 59)      # #1E293B
        TEXT_SUB = (100, 116, 139)    # #64748B
        TEXT_WHITE = (255, 255, 255)
        BORDER = (226, 232, 240)      # #E2E8F0
        ROW_HOVER = (248, 250, 252)   # #F8FAFC

        def header(self):
            self.set_font("NanumG", "", 8)
            # 상단 컬러 바
            self.set_fill_color(*self.ACCENT)
            self.rect(0, 0, self.w, 3, 'F')
            self.set_y(8)
            self.set_text_color(*self.TEXT_SUB)
            self.cell(0, 6, "Nubida Platform Education Report", new_x="LMARGIN", new_y="NEXT", align="C")
            self.ln(3)
            # 구분선
            self.set_draw_color(*self.BORDER)
            self.set_line_width(0.5)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(5)

        def footer(self):
            self.set_y(-18)
            # 하단 구분선
            self.set_draw_color(*self.BORDER)
            self.set_line_width(0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(3)
            self.set_font("NanumG", "", 7)
            self.set_text_color(*self.TEXT_SUB)
            self.cell(0, 10, f"누비다플랫폼 · {now.strftime('%Y-%m-%d %H:%M')} · Page {self.page_no()}/{{nb}}", align="C")

        def section_title(self, text: str):
            self.ln(4)
            self.set_font("NanumG", "", 12)
            self.set_text_color(*self.ACCENT_DARK)
            self.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*self.ACCENT)
            self.set_line_width(0.6)
            self.line(self.l_margin, self.get_y(), self.l_margin + 60, self.get_y())
            self.ln(5)

        def body_text(self, text: str):
            self.set_font("NanumG", "", 9)
            self.set_text_color(*self.TEXT_MAIN)
            self.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

        def styled_table(self, headers: list, col_widths: list, rows: list):
            """전문적인 스타일의 테이블 출력"""
            # 헤더 행
            self.set_font("NanumG", "", 9)
            self.set_fill_color(*self.ACCENT)
            self.set_text_color(*self.TEXT_WHITE)
            for i, h in enumerate(headers):
                self.cell(col_widths[i], 8, f"  {h}", border=0, fill=True)
            self.ln()
            # 데이터 행
            self.set_text_color(*self.TEXT_MAIN)
            for idx, row in enumerate(rows):
                if idx % 2 == 0:
                    self.set_fill_color(*self.ROW_HOVER)
                else:
                    self.set_fill_color(255, 255, 255)
                self.set_font("NanumG", "", 8.5)
                for i, val in enumerate(row):
                    self.cell(col_widths[i], 7, f"  {val}", border=0, fill=True)
                self.ln()
            # 하단 라인
            self.set_draw_color(*self.BORDER)
            self.line(self.l_margin, self.get_y(), self.l_margin + sum(col_widths), self.get_y())
            self.ln(3)

        def meta_row(self, label: str, value: str):
            self.set_font("NanumG", "", 9)
            self.set_text_color(*self.TEXT_SUB)
            self.cell(30, 6, label)
            self.set_text_color(*self.TEXT_MAIN)
            self.cell(60, 6, value, new_x="LMARGIN", new_y="NEXT")

    pdf = PDF()
    pdf.alias_nb_pages()

    # 폰트 로드 (NanumBarunGothic TTF — 100% 한글 호환)
    if os.path.exists(FONT_PATH):
        pdf.add_font("NanumG", "", FONT_PATH, uni=True)
        pdf.add_font("NanumG", "B", FONT_PATH, uni=True)  # bold fallback
    else:
        pdf.set_auto_page_break(auto=True, margin=15)

    pdf.add_page()

    # ── 헤더 영역 ──
    pdf.set_fill_color(*pdf.ACCENT)
    pdf.rect(10, 25, pdf.w - 20, 28, 'F')
    pdf.set_y(28)
    pdf.set_font("NanumG", "", 16)
    pdf.set_text_color(*pdf.TEXT_WHITE)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("NanumG", "", 9)
    pdf.cell(0, 7, f"{report_type}  |  생성자: {director_name}  |  {now.strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_y(pdf.get_y() + 8)

    # ── 메타 정보 ──
    pdf.set_font("NanumG", "", 9)
    pdf.set_text_color(*pdf.TEXT_SUB)
    meta_items = [f"보고서 유형: {report_type}"]
    if date_range_start:
        meta_items.append(f"시작일: {date_range_start}")
    if date_range_end:
        meta_items.append(f"종료일: {date_range_end}")
    pdf.set_x(20)
    pdf.cell(0, 6, "  |  ".join(meta_items), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ── 본문 내용 ──
    if report_type == "학생 성적 보고서":
        pdf.section_title("1. 성적 현황")
        pdf.body_text("선택한 기간의 학생 성적 현황입니다.")

        branch_id = current_user.get("branch_id", 0)
        query = (
            select(Score, User.name.label("student_name"), Exam.title.label("exam_name"))
            .join(Exam, Exam.id == Score.exam_id)
            .join(User, User.id == Score.student_id)
        )
        if current_user.get("role") == "director":
            query = query.join(ClassCourse, ClassCourse.course_id == Exam.course_id)
            query = query.join(SchoolClass, SchoolClass.id == ClassCourse.class_id)
            query = query.where(SchoolClass.director_id == current_user["id"])
        if date_range_start:
            query = query.where(Exam.exam_date >= date_range_start)
        if date_range_end:
            query = query.where(Exam.exam_date <= date_range_end)

        scores_result = await db.execute(query.order_by(Exam.exam_date.desc()).limit(50))
        score_rows = scores_result.all()

        if score_rows:
            data_rows = []
            for score_rec, sname, ename in score_rows:
                exam_date_str = str(score_rec.exam_date) if hasattr(score_rec, 'exam_date') and score_rec.exam_date else "-"
                score_val = str(float(score_rec.score)) if score_rec.score else "-"
                data_rows.append([sname or "-", ename or "-", score_val, exam_date_str])
            pdf.styled_table(
                headers=["학생명", "시험명", "점수", "날짜"],
                col_widths=[50, 45, 25, 30],
                rows=data_rows,
            )
        else:
            pdf.body_text("해당 기간의 성적 데이터가 없습니다.")

    elif report_type == "출결 현황 보고서":
        pdf.section_title("1. 출결 현황")
        pdf.body_text("선택한 기간의 출결 현황입니다.")

        branch_id = current_user.get("branch_id", 0)
        query = (
            select(Attendance, User.name.label("student_name"))
            .join(User, User.id == Attendance.student_id)
        )
        if date_range_start:
            query = query.where(Attendance.date >= date_range_start)
        if date_range_end:
            query = query.where(Attendance.date <= date_range_end)

        att_result = await db.execute(query.order_by(Attendance.date.desc()).limit(50))
        att_rows = att_result.all()

        if att_rows:
            status_map = {"present": "출석", "late": "지각", "absent": "결석", "excused": "공결"}
            data_rows = []
            for att_rec, sname in att_rows:
                att_date = str(att_rec.date) if hasattr(att_rec, 'date') and att_rec.date else "-"
                status_label = status_map.get(att_rec.status, att_rec.status)
                data_rows.append([sname or "-", att_date, status_label])
            pdf.styled_table(
                headers=["학생명", "날짜", "상태"],
                col_widths=[50, 45, 30],
                rows=data_rows,
            )
        else:
            pdf.body_text("해당 기간의 출결 데이터가 없습니다.")

    elif report_type == "수업 통계 보고서":
        pdf.section_title("1. 수업 통계")
        pdf.body_text("선택한 기간의 수업 통계입니다.")

        branch_id = current_user.get("branch_id", 0)
        class_filter = [SchoolClass.branch_id == branch_id]
        if current_user.get("role") == "director":
            class_filter.append(SchoolClass.director_id == current_user["id"])
        class_result = await db.execute(
            select(SchoolClass).where(*class_filter)
        )
        classes = class_result.scalars().all()

        if classes:
            data_rows = []
            for c in classes:
                created = str(c.created_at)[:10] if c.created_at else "-"
                data_rows.append([c.name or "-", str(c.student_count or 0), "-", created])
            pdf.styled_table(
                headers=["학급명", "인원", "강좌수", "생성일"],
                col_widths=[50, 25, 25, 40],
                rows=data_rows,
            )
        else:
            pdf.body_text("등록된 학급이 없습니다.")

    pdf.output(str(filepath))

    file_size = filepath.stat().st_size if filepath.exists() else 0
    relative_path = f"uploads/reports/{filename}"

    report = ReportHistory(
        director_id=current_user["id"],
        title=title,
        report_type=report_type,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        file_path=relative_path,
        file_size=file_size,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return ApiResponse(
        message=f"보고서가 생성되었습니다: {title}",
        data={
            "id": report.id,
            "title": report.title,
            "report_type": report.report_type,
            "date_range_start": str(report.date_range_start) if report.date_range_start else None,
            "date_range_end": str(report.date_range_end) if report.date_range_end else None,
            "file_path": report.file_path,
            "file_size": report.file_size,
            "created_at": str(report.created_at) if report.created_at else None,
        },
    )


@router.get("/reports")
async def get_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """보고서 목록 조회"""
    from app.models import ReportHistory

    query = select(ReportHistory).where(ReportHistory.director_id == current_user["id"])
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(ReportHistory.id.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    reports = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": r.id,
            "director_id": r.director_id,
            "title": r.title,
            "report_type": r.report_type,
            "date_range_start": str(r.date_range_start) if r.date_range_start else None,
            "date_range_end": str(r.date_range_end) if r.date_range_end else None,
            "file_path": r.file_path,
            "file_size": r.file_size,
            "created_at": str(r.created_at) if r.created_at else None,
        } for r in reports],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """보고서 파일 다운로드"""
    from app.models import ReportHistory
    from pathlib import Path
    from fastapi.responses import FileResponse

    result = await db.execute(
        select(ReportHistory).where(
            ReportHistory.id == report_id,
            ReportHistory.director_id == current_user["id"],
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")

    from app.core.config import settings
    file_path = Path(settings.UPLOADS_DIR) / "reports" / Path(report.file_path).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    import urllib.parse
    safe_title = urllib.parse.quote(report.title)
    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        filename=f"{report.title}.pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_title}.pdf"},
    )


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """보고서 삭제 (파일 + DB 기록)"""
    from app.models import ReportHistory
    from pathlib import Path

    result = await db.execute(
        select(ReportHistory).where(
            ReportHistory.id == report_id,
            ReportHistory.director_id == current_user["id"],
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")

    # Delete file if exists
    from app.core.config import settings
    file_path = Path(settings.UPLOADS_DIR) / "reports" / Path(report.file_path).name
    if file_path.exists():
        file_path.unlink()

    await db.delete(report)
    await db.commit()

    return ApiResponse(message="보고서가 삭제되었습니다.")


# ============================================================
# 원장 월간 운영 보고서 (DirectorReport)
# ============================================================

@router.get("/director-reports")
async def get_director_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    director_id: Optional[int] = Query(None),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 보고서 목록 조회 (원장=본인만, 본사/관리자=전체)"""
    from app.models import DirectorReport, User
    from app.schemas import DirectorReportResponse

    role = current_user.get("role", "")
    query = select(DirectorReport)
    
    if role == "director":
        # 원장: 본인 보고서만
        query = query.where(DirectorReport.director_id == current_user["id"])
    else:
        # 본사/관리자: 전체, optional director_id filter
        if director_id:
            query = query.where(DirectorReport.director_id == director_id)
    
    if year:
        query = query.where(DirectorReport.year == year)
    if month:
        query = query.where(DirectorReport.month == month)
    if status:
        query = query.where(DirectorReport.status == status)
    
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(DirectorReport.year.desc(), DirectorReport.month.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page)
    result = await db.execute(query)
    reports = result.scalars().all()

    # 본사용: director_name 보강
    director_ids = list(set(r.director_id for r in reports))
    if director_ids and role != "director":
        users_result = await db.execute(
            select(User.id, User.name, User.username).where(User.id.in_(director_ids))
        )
        user_map = {u.id: u.name or u.username for u in users_result.all()}
    else:
        user_map = {}

    return PaginatedResponse(
        data=[{
            "id": r.id, "director_id": r.director_id, "branch_id": r.branch_id, "status": r.status,
            "year": r.year, "month": r.month,
            "branch_name": r.branch_name, "director_name": r.director_name or user_map.get(r.director_id, ""),
            "contact": r.contact,
            "total_students": r.total_students,
            "new_registrations": r.new_registrations,
            "withdrawals": r.withdrawals,
            "retention_rate": r.retention_rate,
            "target_new_students": r.target_new_students,
            "target_monthly_revenue": r.target_monthly_revenue,
            "target_other": r.target_other or "",
            "notes": r.notes or "", "confirmed_date": r.confirmed_date or "",
            "is_agreed": r.is_agreed, "status": r.status,
            "created_at": str(r.created_at) if r.created_at else None,
            "updated_at": str(r.updated_at) if r.updated_at else None,
        } for r in reports],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 보고서 % 자동 계산 (서버측 보정)
#   프론트에서 자동 산출하지만, 값이 비어 있거나 잘못 들어와도
#   서버가 입력 숫자로 다시 계산해 저장한다.
# ============================================================
def _report_pct(numer, denom) -> int:
    try:
        numer = float(numer or 0)
        denom = float(denom or 0)
    except (TypeError, ValueError):
        return 0
    if denom <= 0:
        return 0
    return round((numer / denom) * 100)


def _normalize_report_rates(d: dict) -> dict:
    """입력 dict의 %/달성률 항목을 자동 재계산해 채운다."""
    total = d.get("total_students") or 0
    withdrawals = d.get("withdrawals") or 0
    retention = _report_pct(total - withdrawals, total)
    d["retention_rate"] = retention

    d["result_new_students_rate"] = _report_pct(
        d.get("result_new_students"), d.get("target_new_students"))
    d["result_monthly_revenue_rate"] = _report_pct(
        d.get("result_monthly_revenue"), d.get("target_monthly_revenue"))

    prev_total = d.get("prev_total_students") or total
    result_retention = _report_pct(prev_total - withdrawals, prev_total)
    d["result_retention_rate"] = result_retention
    d["result_retention_rate_achieved"] = _report_pct(result_retention, retention)
    return d


@router.post("/director-reports")
async def create_director_report(
    data: DirectorReportCreate,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 보고서 저장 (draft/submitted)"""
    from app.models import DirectorReport

    # DB에서 실제 사용자 branch_id 조회 (JWT 토큰 값보다 신뢰성 높음)
    user_result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = user_result.scalar_one_or_none()
    actual_branch_id = user.branch_id if user else current_user.get("branch_id")

    # %·달성률 서버측 자동 재계산
    _nd = data.model_dump() if hasattr(data, "model_dump") else dict(data)
    _nd = _normalize_report_rates(_nd)

    report = DirectorReport(
        director_id=current_user["id"],
        branch_id=actual_branch_id,
        status=data.status or "draft",
        year=data.year,
        month=data.month,
        branch_name=data.branch_name or "",
        director_name=data.director_name or "",
        contact=data.contact or "",
        total_students=_nd.get("total_students") or 0,
        new_registrations=_nd.get("new_registrations") or 0,
        withdrawals=_nd.get("withdrawals") or 0,
        retention_rate=_nd.get("retention_rate") or 0,
        target_new_students=_nd.get("target_new_students") or 0,
        target_monthly_revenue=_nd.get("target_monthly_revenue") or 0,
        target_other=data.target_other or "",
        issue_facility_content=data.issue_facility_content or "",
        issue_facility_request=data.issue_facility_request or "",
        issue_education_content=data.issue_education_content or "",
        issue_education_request=data.issue_education_request or "",
        issue_admin_content=data.issue_admin_content or "",
        issue_admin_request=data.issue_admin_request or "",
        issue_other_content=data.issue_other_content or "",
        issue_other_request=data.issue_other_request or "",
        result_new_students=_nd.get("result_new_students") or 0,
        result_new_students_rate=_nd.get("result_new_students_rate") or 0,
        result_monthly_revenue=_nd.get("result_monthly_revenue") or 0,
        result_monthly_revenue_rate=_nd.get("result_monthly_revenue_rate") or 0,
        result_retention_rate=_nd.get("result_retention_rate") or 0,
        result_retention_rate_achieved=_nd.get("result_retention_rate_achieved") or 0,
        notes=data.notes or "",
        confirmed_date=data.confirmed_date or "",
        is_agreed=data.is_agreed or False,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return ApiResponse(message="보고서가 저장되었습니다.", data={"id": report.id, "status": report.status})


@router.get("/director-reports/{report_id}")
async def get_director_report(
    report_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 보고서 상세 조회"""
    from app.models import DirectorReport

    role = current_user.get("role", "")
    query = select(DirectorReport).where(DirectorReport.id == report_id)
    # 원장(director)은 자신의 보고서만 조회 가능
    if role == "director":
        query = query.where(DirectorReport.director_id == current_user["id"])
    # 본사(admin/super_admin)는 모든 보고서 조회 가능

    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return ApiResponse(data={
        "id": r.id, "director_id": r.director_id, "branch_id": r.branch_id, "status": r.status,
        "year": r.year, "month": r.month,
        "branch_name": r.branch_name, "director_name": r.director_name, "contact": r.contact,
        "total_students": r.total_students,
        "new_registrations": r.new_registrations,
        "withdrawals": r.withdrawals,
        "retention_rate": r.retention_rate,
        "target_new_students": r.target_new_students,
        "target_monthly_revenue": r.target_monthly_revenue,
        "target_other": r.target_other or "",
        "issue_facility_content": r.issue_facility_content or "",
        "issue_facility_request": r.issue_facility_request or "",
        "issue_education_content": r.issue_education_content or "",
        "issue_education_request": r.issue_education_request or "",
        "issue_admin_content": r.issue_admin_content or "",
        "issue_admin_request": r.issue_admin_request or "",
        "issue_other_content": r.issue_other_content or "",
        "issue_other_request": r.issue_other_request or "",
        "result_new_students": r.result_new_students,
        "result_new_students_rate": r.result_new_students_rate,
        "result_monthly_revenue": r.result_monthly_revenue,
        "result_monthly_revenue_rate": r.result_monthly_revenue_rate,
        "result_retention_rate": r.result_retention_rate,
        "result_retention_rate_achieved": r.result_retention_rate_achieved,
        "notes": r.notes or "",
        "confirmed_date": r.confirmed_date or "",
        "is_agreed": r.is_agreed,
        "created_at": str(r.created_at) if r.created_at else None,
        "updated_at": str(r.updated_at) if r.updated_at else None,
    })


@router.put("/director-reports/{report_id}")
async def update_director_report(
    report_id: int,
    data: DirectorReportCreate,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 보고서 수정"""
    from app.models import DirectorReport

    role = current_user.get("role", "")
    query = select(DirectorReport).where(DirectorReport.id == report_id)
    if role == "director":
        query = query.where(DirectorReport.director_id == current_user["id"])
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")

    # %·달성률 서버측 자동 재계산 (프론트 값 대신 신뢰)
    _ud = data.model_dump() if hasattr(data, "model_dump") else dict(data)
    _ud = _normalize_report_rates(_ud)

    for field in [
        "status", "year", "month", "branch_name", "director_name", "contact",
        "total_students", "new_registrations", "withdrawals", "retention_rate",
        "target_new_students", "target_monthly_revenue", "target_other",
        "issue_facility_content", "issue_facility_request",
        "issue_education_content", "issue_education_request",
        "issue_admin_content", "issue_admin_request",
        "issue_other_content", "issue_other_request",
        "result_new_students", "result_new_students_rate",
        "result_monthly_revenue", "result_monthly_revenue_rate",
        "result_retention_rate", "result_retention_rate_achieved",
        "notes", "confirmed_date", "is_agreed",
    ]:
        val = _ud.get(field, getattr(data, field, None))
        if val is not None:
            setattr(r, field, val)

    await db.commit()
    await db.refresh(r)
    return ApiResponse(message="보고서가 수정되었습니다.", data={"id": r.id, "status": r.status})


@router.delete("/director-reports/{report_id}")
async def delete_director_report(
    report_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 보고서 삭제"""
    from app.models import DirectorReport

    role = current_user.get("role", "")
    query = select(DirectorReport).where(DirectorReport.id == report_id)
    if role == "director":
        query = query.where(DirectorReport.director_id == current_user["id"])
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    await db.delete(r)
    await db.commit()
    return ApiResponse(message="보고서가 삭제되었습니다.")


# ============================================================
# 프로그램 조회 (assignments 기반, 읽기 전용)
# ============================================================


@router.get("/programs")
async def get_director_programs(
    current_user: dict = Depends(require_role("director")),
    db: AsyncSession = Depends(get_db),
):
    """현 원장에게 할당된 교육 프로그램 목록"""
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="사용자 정보가 없습니다.")

    assign_result = await db.execute(
        select(ProgramAssignment).where(
            ProgramAssignment.assignee_type == "director",
            ProgramAssignment.assignee_id == user_id,
        )
    )
    assignments = assign_result.scalars().all()
    program_ids = [a.program_id for a in assignments]

    if not program_ids:
        return ApiResponse(data=[])

    prog_result = await db.execute(
        select(EducationProgram).where(EducationProgram.id.in_(program_ids))
    )
    programs = prog_result.scalars().all()

    return ApiResponse(data=[{
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "subject": p.subject,
        "grade_level": p.grade_level,
        "is_active": p.is_active,
        "created_at": str(p.created_at) if p.created_at else None,
    } for p in programs])


@router.get("/programs/{program_id}/chapters")
async def get_director_program_chapters(
    program_id: int,
    current_user: dict = Depends(require_role("director")),
    db: AsyncSession = Depends(get_db),
):
    """특정 프로그램의 챕터 목록 (원장 할당 확인)"""
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="사용자 정보가 없습니다.")

    assign_result = await db.execute(
        select(ProgramAssignment).where(
            ProgramAssignment.assignee_type == "director",
            ProgramAssignment.assignee_id == user_id,
            ProgramAssignment.program_id == program_id,
        )
    )
    if not assign_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="이 프로그램에 접근 권한이 없습니다.")

    chapters_result = await db.execute(
        select(ProgramChapter)
        .where(ProgramChapter.program_id == program_id)
        .order_by(ProgramChapter.sort_order, ProgramChapter.id)
    )
    chapters = chapters_result.scalars().all()

    return ApiResponse(data=[{
        "id": ch.id,
        "title": ch.title,
        "description": ch.description,
        "sort_order": ch.sort_order,
        "is_active": ch.is_active,
        "created_at": str(ch.created_at) if ch.created_at else None,
    } for ch in chapters])


# ============================================================
# 원장 승인 관리 (RevenueApproval 목록)
# ============================================================


@router.get("/revenue-approvals")
async def list_director_revenue_approvals(
    status: Optional[str] = Query(None, description="pending / approved / rejected / paid"),
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장: 자신의 승인 요청 목록 조회"""
    director_id = current_user["id"]

    query = select(RevenueApproval).where(
        RevenueApproval.director_id == director_id,
    )
    if status:
        query = query.where(RevenueApproval.status == status)
    query = query.order_by(RevenueApproval.created_at.desc()).limit(50)

    result = await db.execute(query)
    approvals = result.scalars().all()

    items = []
    for a in approvals:
        items.append({
            "id": a.id,
            "director_id": a.director_id,
            "branch_id": a.branch_id,
            "period_start": str(a.period_start) if a.period_start else None,
            "period_end": str(a.period_end) if a.period_end else None,
            "total_amount": float(a.total_amount or 0),
            "hq_account_number": a.hq_account_number or "",
            "status": a.status,
            "director_note": a.director_note or "",
            "approved_at": str(a.approved_at) if a.approved_at else None,
            "paid_at": str(a.paid_at) if a.paid_at else None,
            "created_at": str(a.created_at) if a.created_at else None,
        })

    return ApiResponse(data=items)


@router.get("/revenue-approvals/{approval_id}")
async def get_director_revenue_approval(
    approval_id: int,
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장: 특정 승인 요청 상세 조회"""
    director_id = current_user["id"]

    result = await db.execute(
        select(RevenueApproval).where(
            RevenueApproval.id == approval_id,
            RevenueApproval.director_id == director_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="승인 요청을 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": a.id,
        "director_id": a.director_id,
        "branch_id": a.branch_id,
        "period_start": str(a.period_start) if a.period_start else None,
        "period_end": str(a.period_end) if a.period_end else None,
        "total_amount": float(a.total_amount or 0),
        "hq_account_number": a.hq_account_number or "",
        "status": a.status,
        "director_note": a.director_note or "",
        "approved_at": str(a.approved_at) if a.approved_at else None,
        "paid_at": str(a.paid_at) if a.paid_at else None,
        "created_at": str(a.created_at) if a.created_at else None,
    })


# ============================================================
# 본사 결제 (45% 수익금 지급)
# ============================================================


@router.get("/payments")
async def get_director_payments(
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 결제 페이지: 매출 기반 45% 본사 지급액 계산"""
    from datetime import datetime, timezone

    branch_id = current_user.get("branch_id", 0)
    director_id = current_user["id"]
    now = datetime.now(timezone.utc)

    # 1. Revenue records for this director only (독립: 같은 지사 다른 원장 매출과 분리)
    rev_result = await db.execute(
        select(Revenue)
        .where(
            Revenue.branch_id == branch_id,
            Revenue.director_id == director_id,
        )
        .order_by(Revenue.created_at.desc())
        .limit(100)
    )
    revenues = rev_result.scalars().all()

    # 2. Calculate totals
    total_revenue = float(sum(r.amount or 0 for r in revenues))
    hq_amount = round(total_revenue * 0.45)  # 45% to HQ
    director_amount = total_revenue - hq_amount

    # 3. Check existing approval status
    approval_result = await db.execute(
        select(RevenueApproval)
        .where(
            RevenueApproval.director_id == director_id,
            RevenueApproval.status.in_(["pending", "approved"]),
        )
        .order_by(RevenueApproval.created_at.desc())
        .limit(1)
    )
    current_approval = approval_result.scalar_one_or_none()

    # 4. Build revenue items
    items = []
    for r in revenues:
        student_name = ""
        if r.student_id:
            s_result = await db.execute(
                select(User.name).where(User.id == r.student_id)
            )
            row = s_result.one_or_none()
            if row:
                student_name = row[0]

        items.append({
            "id": r.id,
            "student_name": student_name or "-",
            "course_name": r.course_name or "",
            "amount": float(r.amount or 0),
            "hq_portion": round(float(r.amount or 0) * 0.45),
            "method": r.method or "",
            "created_at": str(r.created_at) if r.created_at else "",
        })

    return ApiResponse(data={
        "items": items,
        "total_revenue": total_revenue,
        "hq_amount": hq_amount,
        "director_amount": director_amount,
        "hq_account": "국민은행 123456-78-901234 (누비다플랫폼)",
        "approval_status": current_approval.status if current_approval else None,
        "approval_id": current_approval.id if current_approval else None,
    })


@router.post("/payments/submit")
async def submit_director_payment(
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 → 본사 수익금 지급 승인 요청"""
    from datetime import date, timezone

    branch_id = current_user.get("branch_id", 0)
    director_id = current_user["id"]

    # Check existing pending approval
    existing = await db.execute(
        select(RevenueApproval).where(
            RevenueApproval.director_id == director_id,
            RevenueApproval.status == "pending",
        )
    )
    if existing.scalar_one_or_none():
        return ApiResponse(message="이미 승인 요청이 접수되었습니다.", data={"status": "pending"})

    # Calculate total (해당 원장의 매출만 집계 — 독립)
    rev_result = await db.execute(
        select(func.sum(Revenue.amount)).where(
            Revenue.branch_id == branch_id,
            Revenue.director_id == director_id,
        )
    )
    total = float(rev_result.scalar() or 0)
    hq_amount = round(total * 0.45)

    now_utc = datetime.now(timezone.utc)
    approval = RevenueApproval(
        director_id=director_id,
        branch_id=branch_id,
        period_start=date(now_utc.year, now_utc.month, 1),
        period_end=now_utc.date(),
        total_amount=hq_amount,
        hq_account_number="국민은행 123456-78-901234 (누비다플랫폼)",
        status="pending",
        created_at=now_utc,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    return ApiResponse(
        message="본사에 지급 승인 요청을 전송했습니다.",
        data={"id": approval.id, "status": "pending"},
    )


# ============================================================
# 결제 요약 — 원장 대시보드용
# ============================================================


@router.get("/payment-summary")
async def get_director_payment_summary(
    current_user: dict = Depends(require_role("director", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 대시보드: 소속 학생들의 결제 현황 요약"""
    branch_id = current_user.get("branch_id", 0)

    # Get all active enrollments for this branch
    enrollments_result = await db.execute(
        select(Enrollment, User, Course)
        .join(User, User.id == Enrollment.student_id)
        .join(Course, Course.id == Enrollment.course_id)
        .where(
            Enrollment.status == "active",
            Course.branch_id == branch_id,
        )
    )
    rows = enrollments_result.all()

    total_enrollments = len(rows)
    paid = sum(1 for r in rows if r.Enrollment.payment_status == "paid")
    unpaid = sum(1 for r in rows if r.Enrollment.payment_status == "unpaid")
    partial = sum(1 for r in rows if r.Enrollment.payment_status == "partial")

    # Calculate total amount from completed payments
    payment_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.branch_id == branch_id,
            Payment.status == "completed",
        )
    )
    total_paid_amount = float(payment_result.scalar() or 0)

    return ApiResponse(data={
        "total_enrollments": total_enrollments,
        "paid": paid,
        "unpaid": unpaid,
        "partial": partial,
        "total_paid_amount": total_paid_amount,
    })


# ============================================================
# 원장 매출 관리 (Revenue CRUD)
# ============================================================


@router.get("/revenue")
async def list_director_revenue(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    student_id: int = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    method: str = Query(None),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 매출 목록 조회 (필터/페이징)"""
    branch_id = current_user.get("branch_id", 0)
    if not branch_id:
        raise HTTPException(400, "원장 계정에 지사 정보가 없습니다.")

    query = select(Revenue).where(
        Revenue.branch_id == branch_id,
        Revenue.director_id == current_user["id"],
    )
    if student_id:
        query = query.where(Revenue.student_id == student_id)
    if date_from:
        query = query.where(Revenue.created_at >= date_from)
    if date_to:
        query = query.where(Revenue.created_at <= date_to + " 23:59:59")
    if method:
        query = query.where(Revenue.method == method)

    total_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    query = query.order_by(Revenue.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    revenues = result.scalars().all()

    # Build items with student names
    items = []
    for r in revenues:
        sname = ""
        if r.student_id:
            sr = await db.execute(select(User.name).where(User.id == r.student_id))
            row = sr.one_or_none()
            if row:
                sname = row[0]
        items.append({
            "id": r.id,
            "student_id": r.student_id,
            "student_name": sname or "-",
            "course_name": r.course_name or "",
            "amount": float(r.amount or 0),
            "method": r.method or "",
            "created_at": str(r.created_at) if r.created_at else "",
            "updated_at": str(r.updated_at) if r.updated_at else "",
        })

    # Calculate totals
    sum_q = select(func.coalesce(func.sum(Revenue.amount), 0))
    if branch_id:
        sum_q = sum_q.where(Revenue.branch_id == branch_id)
    if current_user.get("role") == "director":
        sum_q = sum_q.where(Revenue.director_id == current_user["id"])
    total_amount = float((await db.execute(sum_q)).scalar() or 0)

    return {
        "items": items,
        "total": total,
        "total_revenue": total_amount,
        "total_count": len(items),
        "month_revenue": total_amount,
        "page": page,
        "total_pages": max(1, (total + limit - 1) // limit),
    }


@router.post("/revenue")
async def create_director_revenue(
    data: dict,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 등록"""
    branch_id = current_user.get("branch_id", 0)
    if not branch_id:
        raise HTTPException(400, "원장 계정에 지사 정보가 없습니다.")

    # Resolve course name from course_id if provided
    course_name = data.get("course_name", "")
    course_id = data.get("course_id")
    if course_id and not course_name:
        cr = await db.execute(select(Course.name).where(Course.id == course_id))
        row = cr.one_or_none()
        if row:
            course_name = row[0]

    revenue = Revenue(
        branch_id=branch_id,
        director_id=current_user["id"],
        student_id=data.get("student_id"),
        course_name=course_name,
        amount=data.get("amount", 0),
        method=data.get("method", "transfer"),
    )
    db.add(revenue)
    await db.commit()
    await db.refresh(revenue)

    return ApiResponse(status="success", data={
        "id": revenue.id,
        "student_id": revenue.student_id,
        "course_name": revenue.course_name,
        "amount": float(revenue.amount or 0),
        "method": revenue.method,
        "created_at": str(revenue.created_at) if revenue.created_at else "",
    }, message="매출이 등록되었습니다.")


@router.get("/revenue/{revenue_id}")
async def get_director_revenue(
    revenue_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 단건 조회"""
    branch_id = current_user.get("branch_id", 0)
    result = await db.execute(
        select(Revenue).where(
            Revenue.id == revenue_id,
            Revenue.branch_id == branch_id,
        )
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(404, "매출 내역을 찾을 수 없습니다.")

    return {
        "id": r.id,
        "student_id": r.student_id,
        "course_name": r.course_name or "",
        "amount": float(r.amount or 0),
        "method": r.method or "",
        "created_at": str(r.created_at) if r.created_at else "",
        "updated_at": str(r.updated_at) if r.updated_at else "",
    }


@router.put("/revenue/{revenue_id}")
async def update_director_revenue(
    revenue_id: int,
    data: dict,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 수정"""
    branch_id = current_user.get("branch_id", 0)
    result = await db.execute(
        select(Revenue).where(
            Revenue.id == revenue_id,
            Revenue.branch_id == branch_id,
        )
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(404, "매출 내역을 찾을 수 없습니다.")

    # Resolve course name from course_id if provided
    course_name = data.get("course_name", "")
    course_id = data.get("course_id")
    if course_id and not course_name:
        cr = await db.execute(select(Course.name).where(Course.id == course_id))
        row = cr.one_or_none()
        if row:
            course_name = row[0]

    if "student_id" in data:
        r.student_id = data["student_id"]
    if course_name:
        r.course_name = course_name
    if "amount" in data:
        r.amount = data["amount"]
    if "method" in data:
        r.method = data["method"]

    await db.commit()
    await db.refresh(r)

    return ApiResponse(status="success", data={
        "id": r.id,
        "student_id": r.student_id,
        "course_name": r.course_name,
        "amount": float(r.amount or 0),
        "method": r.method,
        "updated_at": str(r.updated_at) if r.updated_at else "",
    }, message="매출이 수정되었습니다.")


@router.delete("/revenue/{revenue_id}")
async def delete_director_revenue(
    revenue_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 삭제"""
    branch_id = current_user.get("branch_id", 0)
    result = await db.execute(
        select(Revenue).where(
            Revenue.id == revenue_id,
            Revenue.branch_id == branch_id,
        )
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(404, "매출 내역을 찾을 수 없습니다.")

    await db.execute(delete(Revenue).where(Revenue.id == revenue_id))
    await db.commit()

    return ApiResponse(status="success", message="매출이 삭제되었습니다.")


@router.get("/students")
async def list_director_students(
    limit: int = Query(500, ge=1, le=2000),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 소속 학생 목록 (간단 리스트 - 매출 관리 dropdown용)"""
    branch_id = current_user.get("branch_id", 0)
    query = select(User).where(
        User.role == "student",
        User.is_active == True,
    )
    if branch_id:
        query = query.where(User.branch_id == branch_id)
    if current_user.get("role") == "director":
        query = query.where(User.director_id == current_user["id"])
    query = query.order_by(User.name.asc()).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    return {
        "items": [{"id": s.id, "name": s.name} for s in rows],
        "total": len(rows),
    }


@router.get("/courses")
async def list_director_courses(
    limit: int = Query(500, ge=1, le=2000),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 소속 강좌 목록 — academy_courses에 연결된 강좌만 반환"""
    user_id = current_user.get("id", 0)
    user = await db.get(User, user_id)
    if not user:
        return {"items": [], "total": 0}
    
    # 원장의 academy_id 찾기 (branch_id + 원장 이름으로 매칭)
    branch_id = current_user.get("branch_id", 0)
    user_name = current_user.get("name", "")
    academy_ids = []
    if branch_id and user_name:
        academy_result = await db.execute(
            select(Academy.id).where(
                Academy.branch_id == branch_id,
                Academy.name == user_name,
            )
        )
        academy_ids = [row[0] for row in academy_result.all()]
    
    if not academy_ids:
        return {"items": [], "total": 0}
    
    # academy_courses에 연결된 강좌만 조회 (모든 academy에 대해)
    results = await db.execute(
        select(Course)
        .join(AcademyCourse, Course.id == AcademyCourse.course_id)
        .where(
            AcademyCourse.academy_id.in_(academy_ids),
            AcademyCourse.is_active == True,
            Course.status == "active",
        )
        .order_by(Course.name.asc())
        .limit(limit)
    )
    rows = results.scalars().all()
    return {
        "items": [{"id": c.id, "name": c.name} for c in rows],
        "total": len(rows),
    }


# ============================================================
# 월별 매출관리 (수강료 납부) — 원장
# ============================================================
# 계산 규칙:
#   총매출   = Σ(학생별 해당월 교육비)
#   공급가액 = 총매출 ÷ 1.1        (부가세 10% 제외)
#   로열티   = 공급가액 × 0.45     (본사 45%)
#   순수익   = 공급가액 - 로열티
# ============================================================

COURSE_TYPES = {
    "ai_art": {"label": "AI아트", "amount": 98000},
    "ai_robot": {"label": "AI로봇", "amount": 198000},
}
VAT_RATE = 0.10
ROYALTY_RATE = 0.45


def _calc_financials(total: float) -> dict:
    total = float(total or 0)
    supply = round(total / (1 + VAT_RATE))
    vat = round(total - supply)
    royalty = round(supply * ROYALTY_RATE)
    net = round(supply - royalty)
    return {"total": total, "supply": supply, "vat": vat,
            "royalty": royalty, "net": net}


def _ym_to_period(period_ym: str):
    """'YYYY-MM' → (date(1일), date(말일))"""
    import calendar
    y, m = int(period_ym[:4]), int(period_ym[5:7])
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


@router.get("/tuition/students")
async def list_tuition_students(
    period_ym: str = Query(..., description="정산월 YYYY-MM"),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 매출관리 — 해당월 학생 목록 + 과정/납부 상태"""
    director_id = current_user["id"]
    branch_id = current_user.get("branch_id", 0)

    stu_q = select(User.id, User.name, User.username).where(User.role == "student")
    if branch_id:
        stu_q = stu_q.where(User.branch_id == branch_id)
    stu_q = stu_q.order_by(User.name.asc())
    stu_rows = (await db.execute(stu_q)).all()

    tp_q = select(TuitionPayment).where(
        TuitionPayment.director_id == director_id,
        TuitionPayment.period_ym == period_ym,
    )
    existing = {t.student_id: t for t in (await db.execute(tp_q)).scalars().all()}

    # 학생별 "가장 최근에 저장된 과정" — 새 달 레코드 생성 시 자동 상속
    latest_q = (
        select(TuitionPayment.student_id, TuitionPayment.course_type)
        .where(
            TuitionPayment.director_id == director_id,
            TuitionPayment.period_ym < period_ym,
        )
        .order_by(TuitionPayment.student_id.asc(), TuitionPayment.period_ym.desc())
    )
    latest_course = {}
    for sid_l, ctype_l in (await db.execute(latest_q)).all():
        # 같은 학생 중 period_ym 최신이 먼저 오므로 최초 값만 채택
        if sid_l not in latest_course:
            latest_course[sid_l] = ctype_l

    items = []
    created = 0
    for sid, name, username in stu_rows:
        tp = existing.get(sid)
        if tp is None:
            # 지난 달(최근) 과정이 있으면 그대로 상속, 없으면 기본 ai_art
            ctype = latest_course.get(sid, "ai_art")
            if ctype not in COURSE_TYPES:
                ctype = "ai_art"
            tp = TuitionPayment(
                director_id=director_id, branch_id=branch_id or None,
                student_id=sid, period_ym=period_ym,
                course_type=ctype, amount=COURSE_TYPES[ctype]["amount"],
                paid=False, memo="",
            )
            db.add(tp)
            created += 1
        items.append({
            "student_id": sid,
            "student_name": name or username or f"학생{sid}",
            "student_username": username or "",
            "course_type": tp.course_type,
            "course_label": COURSE_TYPES.get(tp.course_type, {}).get("label", tp.course_type),
            "amount": float(tp.amount or 0),
            "paid": bool(tp.paid),
            "paid_at": str(tp.paid_at) if tp.paid_at else None,
            "memo": tp.memo or "",
        })

    if created:
        await db.commit()

    total = sum(i["amount"] for i in items)
    paid_total = sum(i["amount"] for i in items if i["paid"])
    fin = _calc_financials(paid_total)

    return ApiResponse(data={
        "period_ym": period_ym,
        "items": items,
        "course_types": [{"type": k, "label": v["label"], "amount": v["amount"]}
                         for k, v in COURSE_TYPES.items()],
        "summary": {
            "student_count": len(items),
            "paid_count": sum(1 for i in items if i["paid"]),
            "unpaid_count": sum(1 for i in items if not i["paid"]),
            "total_expected": total,
            "total_paid": paid_total,
            "unpaid": total - paid_total,
            **fin,
        },
    })


@router.put("/tuition/students/{student_id}")
async def update_tuition_student(
    student_id: int,
    payload: dict,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """학생별 과정 변경 / 납부 체크 / 메모 저장 (해당월 upsert)"""
    director_id = current_user["id"]
    branch_id = current_user.get("branch_id", 0)
    period_ym = (payload.get("period_ym") or "").strip()
    if not period_ym:
        raise HTTPException(status_code=400, detail="정산월(period_ym)이 필요합니다.")

    tp = (await db.execute(
        select(TuitionPayment).where(
            TuitionPayment.director_id == director_id,
            TuitionPayment.student_id == student_id,
            TuitionPayment.period_ym == period_ym,
        )
    )).scalar_one_or_none()
    if tp is None:
        tp = TuitionPayment(
            director_id=director_id, branch_id=branch_id or None,
            student_id=student_id, period_ym=period_ym,
            course_type="ai_art", amount=COURSE_TYPES["ai_art"]["amount"], paid=False,
        )
        db.add(tp)

    if "course_type" in payload:
        ctype = (payload.get("course_type") or "ai_art").strip()
        if ctype not in COURSE_TYPES:
            raise HTTPException(status_code=400, detail="알 수 없는 과정 유형입니다.")
        new_amount = COURSE_TYPES[ctype]["amount"]
        # 현재 월 + 아직 지나지 않은(같거나 미래) 월 전체에 과정을 함께 반영.
        # → 원장이 과정을 한 번 지정해 두면 다음 달에도 계속 유지된다.
        affect = (await db.execute(
            select(TuitionPayment).where(
                TuitionPayment.director_id == director_id,
                TuitionPayment.student_id == student_id,
                TuitionPayment.period_ym >= period_ym,
            )
        )).scalars().all()
        if affect:
            for row in affect:
                row.course_type = ctype
                row.amount = new_amount
        else:
            tp.course_type = ctype
            tp.amount = new_amount

    if "paid" in payload:
        tp.paid = bool(payload.get("paid"))
        tp.paid_at = datetime.utcnow() if tp.paid else None

    if "memo" in payload:
        tp.memo = (payload.get("memo") or "")[:255]

    await db.commit()
    return ApiResponse(message="저장되었습니다.", data={
        "student_id": student_id, "course_type": tp.course_type,
        "amount": float(tp.amount or 0), "paid": bool(tp.paid),
    })


@router.get("/tuition/settle")
async def get_tuition_settlement(
    period_ym: str = Query(..., description="정산월 YYYY-MM"),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """해당월 정산 요약 — 총매출/부가세/로열티/순수익 + 승인 상태"""
    director_id = current_user["id"]

    rows = (await db.execute(
        select(TuitionPayment).where(
            TuitionPayment.director_id == director_id,
            TuitionPayment.period_ym == period_ym,
        )
    )).scalars().all()

    paid_total = sum(float(r.amount or 0) for r in rows if r.paid)
    fin = _calc_financials(paid_total)

    p_start, p_end = _ym_to_period(period_ym)
    ap = (await db.execute(
        select(RevenueApproval).where(
            RevenueApproval.director_id == director_id,
            RevenueApproval.period_start == p_start,
        ).order_by(RevenueApproval.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    hq_account = "국민은행 123456-78-901234 (누비다플랫폼)"
    acct_row = (await db.execute(
        select(AppSetting).where(AppSetting.key == "hq_account")
    )).scalar_one_or_none()
    if acct_row and isinstance(acct_row.value, dict):
        hq_account = acct_row.value.get("account") or hq_account

    return ApiResponse(data={
        "period_ym": period_ym,
        "paid_count": sum(1 for r in rows if r.paid),
        "student_count": len(rows),
        **fin,
        "royalty_rate": ROYALTY_RATE,
        "vat_rate": VAT_RATE,
        "hq_account": hq_account,
        "approval_status": ap.status if ap else None,
        "approval_id": ap.id if ap else None,
        "director_note": (ap.director_note if ap else "") or "",
    })


@router.post("/tuition/submit")
async def submit_tuition_payment(
    payload: dict,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """결제 페이지 — 입금자명/입금금액 작성 후 본사 확인 요청.

    입금자명 규칙: [지역]학원명  (예: [부산]누리드림학원)
    상태: pending(확인중) → approved(승인) / deposit_waiting(입금확인대기)
    """
    director_id = current_user["id"]
    branch_id = current_user.get("branch_id", 0)
    period_ym = (payload.get("period_ym") or "").strip()
    depositor = (payload.get("depositor_name") or "").strip()
    amount = payload.get("amount")

    if not period_ym:
        raise HTTPException(status_code=400, detail="정산월(period_ym)이 필요합니다.")
    if not depositor:
        raise HTTPException(status_code=400, detail="입금자명을 입력해 주세요.")
    if amount in (None, ""):
        raise HTTPException(status_code=400, detail="입금금액을 입력해 주세요.")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="입금금액은 숫자로 입력해 주세요.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="입금금액은 0보다 커야 합니다.")

    p_start, p_end = _ym_to_period(period_ym)

    # 같은 달 기존 요청이 있으면 갱신
    ap = (await db.execute(
        select(RevenueApproval).where(
            RevenueApproval.director_id == director_id,
            RevenueApproval.period_start == p_start,
        ).order_by(RevenueApproval.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    if ap is None:
        ap = RevenueApproval(
            director_id=director_id, branch_id=branch_id or None,
            period_start=p_start, period_end=p_end,
        )
        ap.status = "pending"
        db.add(ap)

    # 총매출(납부 기준)
    rows = (await db.execute(
        select(TuitionPayment).where(
            TuitionPayment.director_id == director_id,
            TuitionPayment.period_ym == period_ym,
        )
    )).scalars().all()
    paid_total = sum(float(r.amount or 0) for r in rows if r.paid)
    fin = _calc_financials(paid_total)

    ap.total_amount = fin["royalty"]                 # 본사에 납부할 로열티
    ap.director_note = f"{depositor} / {int(amount):,}원"
    ap.status = "pending"
    ap.approved_at = None
    ap.approved_by = None

    await db.commit()
    return ApiResponse(message="본사에 입금 확인을 요청했습니다.", data={
        "approval_id": ap.id, "status": ap.status,
        "depositor_name": depositor, "amount": amount, **fin,
    })


@router.get("/tuition/history")
async def list_tuition_history(
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 결제 페이지 — 월별 입금 요청 이력"""
    director_id = current_user["id"]
    rows = (await db.execute(
        select(RevenueApproval).where(RevenueApproval.director_id == director_id)
        .order_by(RevenueApproval.period_start.desc()).limit(36)
    )).scalars().all()

    STATUS_LABEL = {
        "pending": "입금 확인 대기",
        "approved": "승인",
        "deposit_waiting": "입금 확인 대기",
        "rejected": "반려",
        "paid": "입금 완료",
    }
    return ApiResponse(data={
        "items": [{
            "id": a.id,
            "period_ym": a.period_start.strftime("%Y-%m") if a.period_start else "",
            "royalty_amount": float(a.total_amount or 0),
            "depositor_name": a.director_note or "",
            "status": a.status,
            "status_label": STATUS_LABEL.get(a.status, a.status),
            "created_at": str(a.created_at) if a.created_at else None,
            "approved_at": str(a.approved_at) if a.approved_at else None,
        } for a in rows],
        "total": len(rows),
    })
