"""
📹 영상 관리 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import Video
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/videos", tags=["영상 관리"])


# ============================================================
# 영상 생성 (관리자 전용)
# ============================================================

@router.post("")
async def create_video(
    data: dict,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    video = Video(
        course_id=data.get("course_id"),
        title=data.get("title"),
        description=data.get("description"),
        url=data.get("url"),
        video_type=data.get("video_type", "youtube"),
        thumbnail_url=data.get("thumbnail_url"),
        duration_seconds=data.get("duration_seconds", 0),
        sort_order=data.get("sort_order", 0),
        is_active=data.get("is_active", True),
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    return ApiResponse(message="영상이 생성되었습니다.", data={
        "id": video.id,
        "course_id": video.course_id,
        "title": video.title,
        "url": video.url,
        "video_type": video.video_type,
    })


# ============================================================
# 영상 파일 업로드 (MP4 등)
# ============================================================

import os, random, string
from pathlib import Path
from fastapi import UploadFile, File as FileParam

VIDEO_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "videos"

@router.post("/upload")
async def upload_video_file(
    title: str = None,
    subject: str = None,
    file: UploadFile = FileParam(...),
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """MP4 등 영상 파일 업로드 후 Video 레코드 생성"""
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 확장자 검증
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "mp4"
    allowed = ("mp4", "webm", "mov", "avi", "mkv")
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 형식입니다. ({', '.join(allowed)})")

    # 안전한 파일명
    rand_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    safe_name = f"video_{current_user['id']}_{rand_str}.{ext}"
    content = await file.read()
    file_path = VIDEO_UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"/uploads/videos/{safe_name}"

    # Video 레코드 생성
    video = Video(
        title=title or file.filename or "업로드 영상",
        subject=subject or None,
        url=file_url,
        video_type="upload",
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    return ApiResponse(message="영상이 업로드되었습니다.", data={
        "id": video.id,
        "title": video.title,
        "url": file_url,
    })


# ============================================================
# 영상 목록 조회 (course_id 필터 지원)
# ============================================================

@router.get("")
async def get_videos(
    course_id: int = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Video)
    if course_id is not None:
        query = query.where(Video.course_id == course_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Video.sort_order, Video.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    videos = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": v.id,
            "course_id": v.course_id,
            "title": v.title,
            "subject": v.subject,
            "description": v.description,
            "url": v.url,
            "video_type": v.video_type,
            "thumbnail_url": v.thumbnail_url,
            "duration_seconds": v.duration_seconds,
            "sort_order": v.sort_order,
            "is_active": v.is_active,
            "created_at": str(v.created_at) if v.created_at else None,
            "updated_at": str(v.updated_at) if v.updated_at else None,
        } for v in videos],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 영상 단건 조회
# ============================================================

@router.get("/{video_id}")
async def get_video(
    video_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": video.id,
        "course_id": video.course_id,
        "title": video.title,
        "subject": video.subject,
        "description": video.description,
        "url": video.url,
        "video_type": video.video_type,
        "thumbnail_url": video.thumbnail_url,
        "duration_seconds": video.duration_seconds,
        "sort_order": video.sort_order,
        "is_active": video.is_active,
        "created_at": str(video.created_at) if video.created_at else None,
        "updated_at": str(video.updated_at) if video.updated_at else None,
    })


# ============================================================
# 영상 수정 (관리자 전용)
# ============================================================

@router.put("/{video_id}")
async def update_video(
    video_id: int,
    data: dict,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

    allowed_fields = {
        "course_id", "title", "description", "url", "video_type",
        "thumbnail_url", "duration_seconds", "sort_order", "is_active",
    }
    for key, val in data.items():
        if key in allowed_fields:
            setattr(video, key, val)

    await db.commit()
    await db.refresh(video)
    return ApiResponse(message="영상이 수정되었습니다.", data={
        "id": video.id,
        "title": video.title,
        "url": video.url,
        "video_type": video.video_type,
    })


# ============================================================
# 영상 삭제 (관리자 전용)
# ============================================================

@router.delete("/{video_id}")
async def delete_video(
    video_id: int,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")

    await db.delete(video)
    await db.commit()
    return ApiResponse(message="영상이 삭제되었습니다.")
