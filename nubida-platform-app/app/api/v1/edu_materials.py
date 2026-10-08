"""
📚 원장 교육 자료 API
- 본사(super_admin/admin): 업로드 · 목록 · 수정 · 삭제 · 발행 관리
- 원장(director) 및 본사 미리보기: 발행 자료 목록/상세/다운로드/뷰어
- 학생 강좌 학습 자료(CourseMaterial)와 완전 분리된 전용 배포 채널
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from urllib.parse import quote
import os
import uuid
import shutil

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import DirectorEduMaterial, User
from app.schemas import ApiResponse, DirectorEduMaterialCreate, DirectorEduMaterialUpdate

# 프로젝트 루트 /uploads/edu (main.py의 makedirs와 동일 경로)
EDU_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "uploads", "edu",
)
os.makedirs(EDU_UPLOAD_DIR, exist_ok=True)

# viewer.start_conversion(file_url)이 /uploads/edu/* 하위 경로를 자동 허용
# (viewer._safe_upload_path: '/uploads/' 접두 제거 → UPLOADS_DIR 기준 상대 경로)

router = APIRouter(prefix="/headquarters/edu-materials", tags=["원장 교육 자료(본사)"])
director_router = APIRouter(prefix="/director/edu-materials", tags=["원장 교육 자료(원장)"])

# 변환 가능한 문서 확장자
_CONVERTIBLE_EXTS = (".pdf", ".ppt", ".pptx")


def _serialize(m: DirectorEduMaterial) -> dict:
    return {
        "id": m.id,
        "title": m.title,
        "description": m.description or "",
        "material_type": m.material_type,
        "file_url": m.file_url or "",
        "file_size": m.file_size or 0,
        "category": m.category or "",
        "content_html": m.content_html or "",
        "is_published": bool(m.is_published),
        "view_count": m.view_count or 0,
        "created_by": m.created_by,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _detect_material_type(ext: str) -> str:
    ext_lower = ext.lower()
    if ext_lower in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
        return "video"
    if ext_lower in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        return "image"
    if ext_lower in (".pdf", ".ppt", ".pptx", ".hwp", ".doc", ".docx", ".txt", ".xlsx", ".zip"):
        return "document"
    return "document"


# ============================================================
# [본사] 자료 목록 조회 (검색/카테고리/유형/발행 필터)
# ============================================================

@router.get("")
async def list_edu_materials(
    search: str = Query("", description="제목/설명 검색"),
    category: str = Query("", description="카테고리 필터"),
    material_type: str = Query("", description="유형 필터 (document/video/image/link)"),
    published_only: bool = Query(False, description="발행된 자료만 조회 (미리보기용)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 전용: 전체 자료 관리 목록"""
    conds = []
    if search:
        like = f"%{search}%"
        conds.append(or_(DirectorEduMaterial.title.like(like), DirectorEduMaterial.description.like(like)))
    if category:
        conds.append(DirectorEduMaterial.category == category)
    if material_type:
        conds.append(DirectorEduMaterial.material_type == material_type)
    if published_only:
        conds.append(DirectorEduMaterial.is_published == True)

    base = select(DirectorEduMaterial)
    if conds:
        base = base.where(*conds)

    total = await db.execute(select(func.count()).select_from(base.subquery()))
    total_cnt = total.scalar() or 0

    result = await db.execute(
        base.order_by(DirectorEduMaterial.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = [_serialize(m) for m in result.scalars().all()]

    return ApiResponse(data={
        "items": items,
        "total": total_cnt,
        "page": page,
        "page_size": page_size,
    })


# ============================================================
# [본사] 상세 조회
# ============================================================

@router.get("/{material_id}")
async def get_edu_material(
    material_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DirectorEduMaterial).where(DirectorEduMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    return ApiResponse(data=_serialize(material))


# ============================================================
# [본사] 파일 업로드 (multipart — pdf/ppt/영상/이미지 등)
# ============================================================

@router.post("/upload")
async def upload_edu_material(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    is_published: bool = Form(False),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """파일 업로드 후 DirectorEduMaterial 자동 생성. PDF/PPT는 뷰어 변환 자동 시작."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(EDU_UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    file_url = f"/uploads/edu/{unique_name}"
    mtype = _detect_material_type(ext)

    material = DirectorEduMaterial(
        title=title or file.filename,
        description=description or None,
        material_type=mtype,
        file_url=file_url,
        file_size=file_size,
        category=category or None,
        is_published=bool(is_published),
        created_by=current_user["id"],
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)

    # PDF/PPT → 슬라이드 뷰어용 백그라운드 변환 시작
    if ext.lower() in _CONVERTIBLE_EXTS:
        try:
            from app.api.v1.viewer import start_conversion
            start_conversion(file_url)
        except Exception:
            pass  # 변환 실패는 목록/다운로드에 영향 없음 (뷰어에서 재시도)

    return ApiResponse(message="파일이 업로드되었습니다.", data=_serialize(material))


# ============================================================
# [본사] 일반 생성 (link 타입 등 파일 없는 자료)
# ============================================================

@router.post("")
async def create_edu_material(
    payload: DirectorEduMaterialCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    material = DirectorEduMaterial(
        title=payload.title,
        description=payload.description,
        material_type=payload.material_type,
        file_url=payload.file_url,
        file_size=payload.file_size or 0,
        category=payload.category,
        content_html=payload.content_html,
        is_published=payload.is_published,
        created_by=current_user["id"],
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    return ApiResponse(message="자료가 등록되었습니다.", data=_serialize(material))


# ============================================================
# [본사] 수정
# ============================================================

@router.put("/{material_id}")
async def update_edu_material(
    material_id: int,
    payload: DirectorEduMaterialUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DirectorEduMaterial).where(DirectorEduMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(material, key, value)
    await db.commit()
    await db.refresh(material)
    return ApiResponse(message="자료가 수정되었습니다.", data=_serialize(material))


# ============================================================
# [본사] 삭제 (DB 레코드 + 업로드 파일)
# ============================================================

@router.delete("/{material_id}")
async def delete_edu_material(
    material_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DirectorEduMaterial).where(DirectorEduMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    # 물리 파일 삭제 (uploads/edu 내부 uuid 파일만)
    if material.file_url and material.file_url.startswith("/uploads/edu/"):
        rel = material.file_url[len("/uploads/edu/"):]
        # 경로 탈출 방지
        if "/" not in rel and "\\" not in rel and ".." not in rel:
            try:
                os.remove(os.path.join(EDU_UPLOAD_DIR, rel))
            except OSError:
                pass

    await db.delete(material)
    await db.commit()
    return ApiResponse(message="자료가 삭제되었습니다.")


# ============================================================
# [원장] 발행 자료 목록 (본사 admin/super_admin은 전체 조회)
# ============================================================

@director_router.get("")
async def director_list_materials(
    search: str = Query("", description="제목/설명 검색"),
    category: str = Query("", description="카테고리 필터"),
    material_type: str = Query("", description="유형 필터"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 화면: 발행된 자료만 노출"""
    conds = []
    if current_user.get("role") == "director":
        conds.append(DirectorEduMaterial.is_published == True)
    if search:
        like = f"%{search}%"
        conds.append(or_(DirectorEduMaterial.title.like(like), DirectorEduMaterial.description.like(like)))
    if category:
        conds.append(DirectorEduMaterial.category == category)
    if material_type:
        conds.append(DirectorEduMaterial.material_type == material_type)

    base = select(DirectorEduMaterial)
    if conds:
        base = base.where(*conds)

    total = await db.execute(select(func.count()).select_from(base.subquery()))
    total_cnt = total.scalar() or 0

    result = await db.execute(
        base.order_by(DirectorEduMaterial.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = [_serialize(m) for m in result.scalars().all()]

    return ApiResponse(data={
        "items": items,
        "total": total_cnt,
        "page": page,
        "page_size": page_size,
    })


# ============================================================
# [원장] 상세 조회 (조회수 증가)
# ============================================================

@director_router.get("/{material_id}")
async def director_get_material(
    material_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DirectorEduMaterial).where(DirectorEduMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    if current_user.get("role") == "director" and not material.is_published:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    # 조회수 증가 (발행 상태/실제 열람 시)
    if current_user.get("role") == "director":
        material.view_count = (material.view_count or 0) + 1
        await db.commit()
        await db.refresh(material)

    return ApiResponse(data=_serialize(material))


# ============================================================
# [원장] 파일 다운로드 (한글 파일명 RFC 5987 지원)
# ============================================================

@director_router.get("/{material_id}/download")
async def director_download_material(
    material_id: int,
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DirectorEduMaterial).where(DirectorEduMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    if current_user.get("role") == "director" and not material.is_published:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")
    if not material.file_url or not material.file_url.startswith("/uploads/edu/"):
        raise HTTPException(status_code=400, detail="다운로드 가능한 파일이 없습니다.")

    fs_path = os.path.join(EDU_UPLOAD_DIR, os.path.basename(material.file_url))
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    ext = os.path.splitext(fs_path)[1]
    download_name = f"{material.title}{ext}"
    encoded = quote(download_name)

    return FileResponse(
        str(fs_path),
        media_type="application/octet-stream",
        filename=download_name,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"
        },
    )
