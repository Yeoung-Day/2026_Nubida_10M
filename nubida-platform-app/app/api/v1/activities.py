"""
📸 활동 영상 API — Activities 관리 (이미지/영상 갤러리)
"""
import os
import random
import string
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import Activity
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/activities", tags=["활동 영상"])

# Upload directory
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "common" / "assets" / "activities"
THUMBNAIL_DIR = UPLOAD_DIR / "thumbnails"

ALLOWED_IMAGE_EXT = ("jpg", "jpeg", "png", "gif", "webp")
ALLOWED_VIDEO_EXT = ("mp4", "webm", "mov", "avi", "mkv")


def _random_filename(ext: str) -> str:
    """Generate a random filename with the given extension."""
    rand_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{rand_str}.{ext}"


def _get_file_type(ext: str) -> str:
    """Determine file type based on extension."""
    if ext.lower() in ALLOWED_IMAGE_EXT:
        return "image"
    if ext.lower() in ALLOWED_VIDEO_EXT:
        return "video"
    return None


# ============================================================
# 활동 영상 목록 조회 (PUBLIC — 인증 불필요)
# ============================================================

@router.get("")
async def list_activities(
    page: int = Query(1, ge=1),
    per_page: int = Query(12, ge=1, le=50),
    file_type: str = Query(None, description="image / video"),
    db: AsyncSession = Depends(get_db),
):
    """공개된 활동 영상 목록을 조회합니다. (로그인 불필요)"""
    query = select(Activity).where(Activity.is_visible == True)

    if file_type and file_type in ("image", "video"):
        query = query.where(Activity.file_type == file_type)

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginated query
    query = query.order_by(Activity.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    activities = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "file_type": a.file_type,
            "file_path": a.file_path,
            "thumbnail_path": a.thumbnail_path,
            "created_at": str(a.created_at) if a.created_at else None,
        } for a in activities],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page if total > 0 else 1,
    )


# ============================================================
# 활동 영상 업로드 (관리자 전용)
# ============================================================

@router.post("")
async def create_activity(
    title: str = Form(...),
    description: str = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """새 활동 영상/이미지를 업로드합니다. (관리자 전용)"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    # Validate extension
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    file_type = _get_file_type(ext)
    if not file_type:
        allowed_exts = ALLOWED_IMAGE_EXT + ALLOWED_VIDEO_EXT
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식입니다. ({', '.join(allowed_exts)})",
        )

    # Save file
    safe_name = _random_filename(ext)
    content = await file.read()
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"/common/assets/activities/{safe_name}"

    # Generate thumbnail for videos (simple placeholder approach)
    thumbnail_path = None
    if file_type == "video":
        # For videos, we create a simple placeholder approach
        # In production, you'd use ffmpeg to extract a frame
        thumbnail_path = None  # Will be generated as needed

    # Create DB record
    activity = Activity(
        title=title,
        description=description or None,
        file_type=file_type,
        file_path=file_url,
        thumbnail_path=thumbnail_path,
        uploaded_by=current_user["id"],
        is_visible=True,
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    return ApiResponse(
        message="활동 영상이 업로드되었습니다.",
        data={
            "id": activity.id,
            "title": activity.title,
            "file_type": activity.file_type,
            "file_path": activity.file_path,
            "thumbnail_path": activity.thumbnail_path,
            "created_at": str(activity.created_at) if activity.created_at else None,
        },
    )


# ============================================================
# 활동 영상 단건 조회 (PUBLIC)
# ============================================================

@router.get("/{activity_id}")
async def get_activity(
    activity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """특정 활동 영상 상세 정보를 조회합니다."""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="활동 영상을 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": activity.id,
        "title": activity.title,
        "description": activity.description,
        "file_type": activity.file_type,
        "file_path": activity.file_path,
        "thumbnail_path": activity.thumbnail_path,
        "is_visible": activity.is_visible,
        "created_at": str(activity.created_at) if activity.created_at else None,
        "updated_at": str(activity.updated_at) if activity.updated_at else None,
    })


# ============================================================
# 활동 영상 수정 (관리자 전용)
# ============================================================

@router.put("/{activity_id}")
async def update_activity(
    activity_id: int,
    data: dict,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """활동 영상 정보를 수정합니다. (관리자 전용)"""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="활동 영상을 찾을 수 없습니다.")

    allowed_fields = {"title", "description", "is_visible"}
    for key, val in data.items():
        if key in allowed_fields:
            setattr(activity, key, val)

    await db.commit()
    await db.refresh(activity)

    return ApiResponse(
        message="활동 영상이 수정되었습니다.",
        data={
            "id": activity.id,
            "title": activity.title,
            "description": activity.description,
            "is_visible": activity.is_visible,
        },
    )


# ============================================================
# 활동 영상 삭제 (관리자 전용)
# ============================================================

@router.delete("/{activity_id}")
async def delete_activity(
    activity_id: int,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """활동 영상을 삭제합니다. (관리자 전용) — 파일도 함께 삭제"""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="활동 영상을 찾을 수 없습니다.")

    # Delete physical file
    if activity.file_path:
        file_path = Path(__file__).resolve().parent.parent.parent.parent / activity.file_path.lstrip("/")
        if file_path.exists():
            file_path.unlink()

    await db.delete(activity)
    await db.commit()

    return ApiResponse(message="활동 영상이 삭제되었습니다.")


# ============================================================
# 활동 영상 가시성 토글 (관리자 전용)
# ============================================================

@router.put("/{activity_id}/visibility")
async def toggle_activity_visibility(
    activity_id: int,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """활동 영상의 공개/비공개를 전환합니다. (관리자 전용)"""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="활동 영상을 찾을 수 없습니다.")

    activity.is_visible = not activity.is_visible
    await db.commit()
    await db.refresh(activity)

    status_text = "공개" if activity.is_visible else "비공개"
    return ApiResponse(
        message=f"활동 영상이 {status_text}로 변경되었습니다.",
        data={
            "id": activity.id,
            "is_visible": activity.is_visible,
        },
    )


# ============================================================
# 관리자용 전체 목록 조회 (비공개 포함)
# ============================================================

@router.get("/admin/all")
async def list_all_activities(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    file_type: str = Query(None, description="image / video / all"),
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """모든 활동 영상 목록을 조회합니다. (관리자 전용, 비공개 포함)"""
    query = select(Activity)

    if file_type and file_type in ("image", "video"):
        query = query.where(Activity.file_type == file_type)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Activity.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    activities = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "file_type": a.file_type,
            "file_path": a.file_path,
            "thumbnail_path": a.thumbnail_path,
            "is_visible": a.is_visible,
            "uploaded_by": a.uploaded_by,
            "created_at": str(a.created_at) if a.created_at else None,
            "updated_at": str(a.updated_at) if a.updated_at else None,
        } for a in activities],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page if total > 0 else 1,
    )
