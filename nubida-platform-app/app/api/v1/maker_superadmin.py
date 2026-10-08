"""
🏢 메이커 코딩 교육 시스템 — 본사(SuperAdmin) API
"""
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from app.core.database import get_db
from app.core.security import hash_password
from app.models import (
    MakerCourse, Lesson, Studio, MakerStudent,
    MakerEnrollment, LessonProgress, MakerPortfolio,
)
from app.schemas import ApiResponse
from app.api.v1.maker_auth import get_maker_user

router = APIRouter(prefix="/maker/superadmin", tags=["메이커 코딩 - 본사"])

security = HTTPBearer()


def _require_superadmin(user: dict):
    """본사 관리자 권한 확인"""
    if user["role"] != "maker_superadmin":
        raise HTTPException(403, detail="본사 관리자(superadmin)만 접근 가능합니다.")


# ──────────────────────────────────────────────
# 1. 강좌 목록 (페이징)
# ──────────────────────────────────────────────


@router.get("/courses")
async def list_courses(
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    모든 메이커 강좌를 페이징하여 조회합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    # 전체 개수
    result = await db.execute(select(func.count(MakerCourse.id)))
    total = result.scalar() or 0

    # 페이지네이션
    offset = (page - 1) * per_page
    result = await db.execute(
        select(MakerCourse)
        .order_by(MakerCourse.month.desc(), MakerCourse.id.asc())
        .offset(offset)
        .limit(per_page)
    )
    courses = result.scalars().all()

    total_pages = (total + per_page - 1) // per_page if total > 0 else 0

    return ApiResponse(data={
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "month": c.month,
                "description": c.description,
                "thumbnail": c.thumbnail,
                "kit_name": c.kit_name,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in courses
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    })


# ──────────────────────────────────────────────
# 2. 강좌 생성
# ──────────────────────────────────────────────


@router.post("/courses")
async def create_course(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    새 메이커 강좌를 생성합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 필수: title, month
    - 선택: description, thumbnail, kit_name
    """
    _require_superadmin(current_user)

    title = data.get("title", "").strip()
    month = data.get("month", "").strip()

    if not title:
        raise HTTPException(400, detail="강좌명(title)은 필수입니다.")
    if not month:
        raise HTTPException(400, detail="월(month)은 필수입니다. (예: 2026-05)")

    course = MakerCourse(
        title=title,
        month=month,
        description=data.get("description", ""),
        thumbnail=data.get("thumbnail", ""),
        kit_name=data.get("kit_name", ""),
        status=data.get("status", "active"),
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    return ApiResponse(data={
        "id": course.id,
        "title": course.title,
        "month": course.month,
        "description": course.description,
        "thumbnail": course.thumbnail,
        "kit_name": course.kit_name,
        "status": course.status,
        "created_at": course.created_at.isoformat() if course.created_at else None,
    }, message="강좌가 생성되었습니다.")


# ──────────────────────────────────────────────
# 3. 강좌 수정
# ──────────────────────────────────────────────


@router.put("/courses/{course_id}")
async def update_course(
    course_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    메이커 강좌 정보를 수정합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(MakerCourse).where(MakerCourse.id == course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, detail="존재하지 않는 강좌입니다.")

    # 업데이트 가능한 필드
    updatable_fields = ["title", "month", "description", "thumbnail", "kit_name", "status"]
    for field in updatable_fields:
        if field in data:
            setattr(course, field, data[field])

    await db.commit()
    await db.refresh(course)

    return ApiResponse(data={
        "id": course.id,
        "title": course.title,
        "month": course.month,
        "description": course.description,
        "thumbnail": course.thumbnail,
        "kit_name": course.kit_name,
        "status": course.status,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }, message="강좌가 수정되었습니다.")


# ──────────────────────────────────────────────
# 4. 강좌 삭제 (연관 차시 함께 삭제)
# ──────────────────────────────────────────────


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    메이커 강좌를 삭제합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 해당 강좌의 모든 차시(Lesson)도 함께 삭제됩니다.
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(MakerCourse).where(MakerCourse.id == course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, detail="존재하지 않는 강좌입니다.")

    # 연관된 차시 먼저 삭제
    await db.execute(
        delete(Lesson).where(Lesson.maker_course_id == course_id)
    )

    await db.delete(course)
    await db.commit()

    return ApiResponse(data={
        "id": course_id,
    }, message="강좌가 삭제되었습니다.")


# ──────────────────────────────────────────────
# 5. 강좌별 차시 목록
# ──────────────────────────────────────────────


@router.get("/courses/{course_id}/lessons")
async def list_lessons(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 강좌의 모든 차시(수업)를 조회합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    # 강좌 존재 확인
    result = await db.execute(
        select(MakerCourse).where(MakerCourse.id == course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, detail="존재하지 않는 강좌입니다.")

    result = await db.execute(
        select(Lesson)
        .where(Lesson.maker_course_id == course_id)
        .order_by(Lesson.order_num.asc())
    )
    lessons = result.scalars().all()

    return ApiResponse(data={
        "course": {
            "id": course.id,
            "title": course.title,
            "month": course.month,
        },
        "lessons": [
            {
                "id": l.id,
                "order_num": l.order_num,
                "title": l.title,
                "content_type": l.content_type,
                "ppt_url": l.ppt_url,
                "video_url": l.video_url,
                "duration_minutes": l.duration_minutes,
                "description": l.description,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in lessons
        ],
    })


# ──────────────────────────────────────────────
# 6. 차시 추가
# ──────────────────────────────────────────────


@router.post("/courses/{course_id}/lessons")
async def create_lesson(
    course_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 강좌에 새 차시(수업)를 추가합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 필수: order_num, title
    - 선택: content_type, ppt_url, video_url, duration_minutes, description
    """
    _require_superadmin(current_user)

    # 강좌 존재 확인
    result = await db.execute(
        select(MakerCourse).where(MakerCourse.id == course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(404, detail="존재하지 않는 강좌입니다.")

    order_num = data.get("order_num")
    title = data.get("title", "").strip()

    if order_num is None:
        raise HTTPException(400, detail="차시 번호(order_num)는 필수입니다.")
    if not title:
        raise HTTPException(400, detail="차시 제목(title)은 필수입니다.")

    lesson = Lesson(
        maker_course_id=course_id,
        order_num=int(order_num),
        title=title,
        content_type=data.get("content_type", "ppt"),
        ppt_url=data.get("ppt_url", ""),
        video_url=data.get("video_url", ""),
        duration_minutes=data.get("duration_minutes", 10),
        description=data.get("description", ""),
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    return ApiResponse(data={
        "id": lesson.id,
        "maker_course_id": lesson.maker_course_id,
        "order_num": lesson.order_num,
        "title": lesson.title,
        "content_type": lesson.content_type,
        "ppt_url": lesson.ppt_url,
        "video_url": lesson.video_url,
        "duration_minutes": lesson.duration_minutes,
        "description": lesson.description,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
    }, message="차시가 추가되었습니다.")


# ──────────────────────────────────────────────
# 7. 차시 수정
# ──────────────────────────────────────────────


@router.put("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    차시(수업) 정보를 수정합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(Lesson).where(Lesson.id == lesson_id)
    )
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(404, detail="존재하지 않는 차시입니다.")

    updatable_fields = ["order_num", "title", "content_type", "ppt_url", "video_url", "duration_minutes", "description"]
    for field in updatable_fields:
        if field in data:
            setattr(lesson, field, data[field])

    await db.commit()
    await db.refresh(lesson)

    return ApiResponse(data={
        "id": lesson.id,
        "maker_course_id": lesson.maker_course_id,
        "order_num": lesson.order_num,
        "title": lesson.title,
        "content_type": lesson.content_type,
        "ppt_url": lesson.ppt_url,
        "video_url": lesson.video_url,
        "duration_minutes": lesson.duration_minutes,
        "description": lesson.description,
    }, message="차시가 수정되었습니다.")


# ──────────────────────────────────────────────
# 8. 차시 삭제
# ──────────────────────────────────────────────


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    차시(수업)를 삭제합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(Lesson).where(Lesson.id == lesson_id)
    )
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(404, detail="존재하지 않는 차시입니다.")

    await db.delete(lesson)
    await db.commit()

    return ApiResponse(data={
        "id": lesson_id,
    }, message="차시가 삭제되었습니다.")


# ──────────────────────────────────────────────
# 9. 파일 업로드 (placeholder)
# ──────────────────────────────────────────────


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    파일을 업로드합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 현재는 placeholder로, 업로드된 파일을 /uploads/ 디렉토리에 저장
    """
    _require_superadmin(current_user)

    # 파일 확장자 확인
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1] if "." in filename else ""
    safe_name = f"{uuid.uuid4().hex}{ext}"

    # 업로드 디렉토리
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "uploads",
        "maker",
    )
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    url = f"/uploads/maker/{safe_name}"

    return ApiResponse(data={
        "url": url,
        "filename": safe_name,
        "original_name": filename,
        "size": len(content),
    }, message="파일이 업로드되었습니다.")


# ──────────────────────────────────────────────
# 10. 스튜디오 목록
# ──────────────────────────────────────────────


@router.get("/studios")
async def list_studios(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    모든 스튜디오(공부방) 목록을 조회합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(Studio).order_by(Studio.created_at.desc())
    )
    studios = result.scalars().all()

    # 각 스튜디오별 학생 수 추가
    studios_data = []
    for s in studios:
        result = await db.execute(
            select(func.count(MakerStudent.id)).where(
                MakerStudent.studio_id == s.id,
                MakerStudent.is_active == True,
            )
        )
        student_count = result.scalar() or 0

        studios_data.append({
            "id": s.id,
            "name": s.name,
            "admin_name": s.admin_name,
            "admin_phone": s.admin_phone,
            "max_students": s.max_students,
            "status": s.status,
            "student_count": student_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return ApiResponse(data=studios_data)


# ──────────────────────────────────────────────
# 11. 스튜디오 생성
# ──────────────────────────────────────────────


@router.post("/studios")
async def create_studio(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    새 스튜디오(공부방)를 생성합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 필수: name
    - 선택: admin_name, admin_phone, max_students
    """
    _require_superadmin(current_user)

    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, detail="스튜디오명(name)은 필수입니다.")

    studio = Studio(
        name=name,
        admin_name=data.get("admin_name", ""),
        admin_phone=data.get("admin_phone", ""),
        max_students=data.get("max_students", 10),
        status=data.get("status", "active"),
    )
    db.add(studio)
    await db.commit()
    await db.refresh(studio)

    return ApiResponse(data={
        "id": studio.id,
        "name": studio.name,
        "admin_name": studio.admin_name,
        "admin_phone": studio.admin_phone,
        "max_students": studio.max_students,
        "status": studio.status,
        "created_at": studio.created_at.isoformat() if studio.created_at else None,
    }, message="스튜디오가 생성되었습니다.")


# ──────────────────────────────────────────────
# 12. 스튜디오 수정
# ──────────────────────────────────────────────


@router.put("/studios/{studio_id}")
async def update_studio(
    studio_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    스튜디오(공부방) 정보를 수정합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    result = await db.execute(
        select(Studio).where(Studio.id == studio_id)
    )
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(404, detail="존재하지 않는 스튜디오입니다.")

    updatable_fields = ["name", "admin_name", "admin_phone", "max_students", "status"]
    for field in updatable_fields:
        if field in data:
            setattr(studio, field, data[field])

    await db.commit()
    await db.refresh(studio)

    return ApiResponse(data={
        "id": studio.id,
        "name": studio.name,
        "admin_name": studio.admin_name,
        "admin_phone": studio.admin_phone,
        "max_students": studio.max_students,
        "status": studio.status,
    }, message="스튜디오가 수정되었습니다.")


# ──────────────────────────────────────────────
# 13. 스튜디오별 학생 목록
# ──────────────────────────────────────────────


@router.get("/studios/{studio_id}/students")
async def list_studio_students(
    studio_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 스튜디오의 모든 학생을 조회합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    """
    _require_superadmin(current_user)

    # 스튜디오 존재 확인
    result = await db.execute(
        select(Studio).where(Studio.id == studio_id)
    )
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(404, detail="존재하지 않는 스튜디오입니다.")

    result = await db.execute(
        select(MakerStudent)
        .where(MakerStudent.studio_id == studio_id)
        .order_by(MakerStudent.created_at.desc())
    )
    students = result.scalars().all()

    return ApiResponse(data={
        "studio": {
            "id": studio.id,
            "name": studio.name,
        },
        "students": [
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
        ],
    })


# ──────────────────────────────────────────────
# 14. 스튜디오에 학생 계정 생성
# ──────────────────────────────────────────────


@router.post("/studios/create-student")
async def create_studio_student(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_maker_user),
):
    """
    특정 스튜디오에 새 학생 계정을 생성합니다.
    - 본사 관리자( maker_superadmin ) 권한 필요
    - 필수: studio_id, name
    - login_id는 자동 생성 (중복 방지 UUID 기반)
    - 초기 비밀번호: "1234"
    - 선택: grade, start_date
    """
    _require_superadmin(current_user)

    studio_id = data.get("studio_id")
    name = data.get("name", "").strip()

    if not studio_id:
        raise HTTPException(400, detail="스튜디오 ID(studio_id)는 필수입니다.")
    if not name:
        raise HTTPException(400, detail="학생 이름(name)은 필수입니다.")

    # 스튜디오 존재 확인
    result = await db.execute(
        select(Studio).where(Studio.id == studio_id)
    )
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(404, detail="존재하지 않는 스튜디오입니다.")

    # login_id 자동 생성 (고유성 보장)
    import random
    suffix = str(random.randint(1000, 9999))
    login_id = f"{name}_{suffix}"

    # 중복 방지를 위한 재시도
    max_attempts = 10
    for attempt in range(max_attempts):
        result = await db.execute(
            select(MakerStudent).where(MakerStudent.login_id == login_id)
        )
        if not result.scalar_one_or_none():
            break
        suffix = str(random.randint(1000, 9999))
        login_id = f"{name}_{suffix}"
    else:
        # UUID fallback
        login_id = f"{name}_{uuid.uuid4().hex[:8]}"

    # 초기 비밀번호 "1234" 해싱
    init_password = "1234"
    password_hash = hash_password(init_password)

    student = MakerStudent(
        studio_id=studio_id,
        name=name,
        login_id=login_id,
        password_hash=password_hash,
        grade=data.get("grade", ""),
        start_date=data.get("start_date", None),
        is_active=True,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)

    return ApiResponse(data={
        "id": student.id,
        "studio_id": student.studio_id,
        "studio_name": studio.name,
        "name": student.name,
        "login_id": student.login_id,
        "initial_password": init_password,
        "grade": student.grade,
        "start_date": student.start_date.isoformat() if student.start_date else None,
        "is_active": student.is_active,
    }, message=f"학생 계정이 생성되었습니다. (로그인 ID: {login_id}, 초기 비밀번호: {init_password})")
