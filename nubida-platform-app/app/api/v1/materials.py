"""
📚 강좌 학습 자료 API
- 본사/원장/교사: 자료 CRUD
- 학생/학부모: 자료 조회 + 학습 진행률
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone
import os, uuid, shutil

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import CourseMaterial, LearningProgress, Course, User, Enrollment, PointTransaction
from app.schemas import (
    ApiResponse, PaginatedResponse,
    CourseMaterialCreate, CourseMaterialUpdate, LearningProgressUpdate,
)
from app.services.point_service import award_points_for_course_completion

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/courses", tags=["강좌 학습 자료"])


# ============================================================
# 자료 목록 조회 (모든 역할)
# ============================================================

# ============================================================
# 자료 통계 (본사/원장/교사)
# ============================================================

@router.get("/{course_id}/materials/stats")
async def get_materials_stats(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌의 자료 유형별 개수 통계"""
    total = await db.execute(
        select(func.count(CourseMaterial.id))
        .where(CourseMaterial.course_id == course_id, CourseMaterial.is_active == True)
    )
    total_cnt = total.scalar() or 0

    type_counts = {}
    type_result = await db.execute(
        select(CourseMaterial.material_type, func.count(CourseMaterial.id))
        .where(CourseMaterial.course_id == course_id, CourseMaterial.is_active == True)
        .group_by(CourseMaterial.material_type)
    )
    for t, cnt in type_result.all():
        type_counts[t] = cnt

    return ApiResponse(data={
        "total": total_cnt,
        "documents": type_counts.get("document", 0),
        "videos": type_counts.get("video", 0),
        "images": type_counts.get("image", 0),
        "links": type_counts.get("link", 0),
        "embed": type_counts.get("embed", 0),
    })


@router.get("/{course_id}/materials")
async def get_materials(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """강좌의 학습 자료 목록을 정렬 순으로 반환"""
    result = await db.execute(
        select(CourseMaterial)
        .where(
            CourseMaterial.course_id == course_id,
            CourseMaterial.is_active == True,
        )
        .order_by(CourseMaterial.sort_order, CourseMaterial.id)
    )
    materials = result.scalars().all()

    # 학생이면 진행률도 함께 반환
    progress_map = {}
    if current_user.get("role") == "student":
        prog_result = await db.execute(
            select(LearningProgress)
            .where(
                LearningProgress.student_id == current_user["id"],
                LearningProgress.course_id == course_id,
            )
        )
        for p in prog_result.scalars().all():
            progress_map[p.material_id] = {
                "is_completed": p.is_completed,
                "progress_percent": p.progress_percent,
                "last_viewed_at": str(p.last_viewed_at) if p.last_viewed_at else None,
            }

    return ApiResponse(data=[{
        "id": m.id,
        "course_id": m.course_id,
        "title": m.title,
        "description": m.description,
        "material_type": m.material_type,
        "file_url": m.file_url,
        "embed_url": m.embed_url,
        "file_size": m.file_size,
        "duration_minutes": m.duration_minutes,
        "content_html": m.content_html,
        "content_blocks": m.content_blocks,
        "chapter": getattr(m, 'chapter', '') or '',
        "sort_order": m.sort_order,
        "created_at": str(m.created_at),
        "progress": progress_map.get(m.id),
    } for m in materials])



# ============================================================
# 자료 상세 조회
# ============================================================

@router.get("/{course_id}/materials/{material_id}")
async def get_material_detail(
    course_id: int,
    material_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course_id,
        )
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    # 학생이면 진행률 기록 (조회 시 자동 기록)
    if current_user.get("role") == "student":
        student_id = current_user["id"]
        prog_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.student_id == student_id,
                LearningProgress.material_id == material_id,
            )
        )
        progress = prog_result.scalar_one_or_none()
        if not progress:
            progress = LearningProgress(
                student_id=student_id,
                material_id=material_id,
                course_id=course_id,
                progress_percent=10,
                last_viewed_at=datetime.now(timezone.utc),
            )
            db.add(progress)
        else:
            progress.last_viewed_at = datetime.now(timezone.utc)
            if progress.progress_percent < 10:
                progress.progress_percent = 10
        await db.commit()

    progress_map = {}
    if current_user.get("role") == "student":
        prog_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.student_id == current_user["id"],
                LearningProgress.material_id == material_id,
            )
        )
        p = prog_result.scalar_one_or_none()
        if p:
            progress_map = {
                "is_completed": p.is_completed,
                "progress_percent": p.progress_percent,
                "last_viewed_at": str(p.last_viewed_at),
            }

    return ApiResponse(data={
        "id": material.id,
        "course_id": material.course_id,
        "title": material.title,
        "description": material.description,
        "material_type": material.material_type,
        "file_url": material.file_url,
        "embed_url": material.embed_url,
        "file_size": material.file_size,
        "duration_minutes": material.duration_minutes,
        "content_html": material.content_html,
        "content_blocks": material.content_blocks,
        "chapter": getattr(material, 'chapter', '') or '',
        "sort_order": material.sort_order,
        "created_at": str(material.created_at),
        "progress": progress_map,
    })


# ============================================================
# 자료 생성 (본사/원장/교사)
# ============================================================

@router.post("/{course_id}/materials")
async def create_material(
    course_id: int,
    data: CourseMaterialCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    # 강좌 존재 확인
    result = await db.execute(select(Course).where(Course.id == course_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    material = CourseMaterial(
        course_id=course_id,
        title=data.title,
        description=data.description,
        material_type=data.material_type,
        file_url=data.file_url,
        embed_url=data.embed_url,
        file_size=data.file_size,
        duration_minutes=data.duration_minutes,
        content_html=data.content_html,
        sort_order=data.sort_order,
        created_by=current_user["id"],
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)

    return ApiResponse(message="자료가 등록되었습니다.", data={"id": material.id})


# ============================================================
# 강의 콘텐츠 저장 (본사 전용, content_html 전송)
# ============================================================

@router.put("/{course_id}/materials/{material_id}/content")
async def update_material_content(
    course_id: int,
    material_id: int,
    data: dict,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """강의 콘텐츠(HTML) 저장 — PPT 슬라이드 + 코드 블록 포함"""
    result = await db.execute(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course_id,
        )
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    content_html = data.get("content_html", "")
    material.content_html = content_html
    if data.get("material_type"):
        material.material_type = data["material_type"]
    await db.commit()

    return ApiResponse(message="강의 콘텐츠가 저장되었습니다.")


@router.put("/{course_id}/materials/{material_id}/blocks")
async def update_material_blocks(
    course_id: int,
    material_id: int,
    data: dict,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """강의 블록 콘텐츠 저장 — content_blocks (JSON 블록 배열) + content_html 동시 생성"""
    result = await db.execute(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course_id,
        )
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    blocks = data.get("content_blocks", [])
    material.content_blocks = blocks
    if data.get("material_type"):
        material.material_type = data["material_type"]

    # content_blocks로부터 content_html 자동 생성 (하위호환)
    material.content_html = _blocks_to_html(blocks)

    await db.commit()
    return ApiResponse(message="강의 블록 콘텐츠가 저장되었습니다.")


def _blocks_to_html(blocks: list) -> str:
    """content_blocks 배열을 HTML로 변환 (하위호환용)"""
    if not blocks:
        return ""
    html_parts = []
    for block in blocks:
        btype = block.get("type", "text")
        bdata = block.get("data", {})
        if btype == "text":
            html_parts.append(f"<p>{bdata.get('content', '')}</p>")
        elif btype == "heading":
            html_parts.append(f"<h2>{bdata.get('content', '')}</h2>")
        elif btype == "code":
            lang = bdata.get("language", "text")
            code = bdata.get("code", "")
            html_parts.append(f'<pre class="code-block {lang}"><code>{code}</code></pre>')
        elif btype == "slide":
            file_url = bdata.get("file_url", "")
            file_ext = bdata.get("file_ext", "pptx")
            html_parts.append(f'<pre class="code-block slide" data-src="{file_url}" data-type="{file_ext}"><code>[슬라이드]</code></pre>')
        elif btype == "image":
            src = bdata.get("src", "")
            alt = bdata.get("alt", "")
            html_parts.append(f'<p><img src="{src}" alt="{alt}" style="max-width:100%"></p>')
        elif btype == "video":
            url = bdata.get("url", "")
            html_parts.append(f'<p><a href="{url}" target="_blank">🎬 영상 보기</a></p>')
    return "\n".join(html_parts)


# ============================================================
# 파일 업로드 (본사 전용, multipart)
# ============================================================

@router.post("/{course_id}/upload")
async def upload_course_file(
    course_id: int,
    file: UploadFile = File(...),
    title: str = "",
    material_type: str = "document",
    sort_order: int = 0,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """파일 업로드 후 CourseMaterial 자동 생성"""
    # 강좌 존재 확인
    result = await db.execute(select(Course).where(Course.id == course_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    # 고유 파일명 생성
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    # 파일 저장
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    file_url = f"/uploads/{unique_name}"

    # material_type 자동 감지
    mtype = material_type
    if not mtype or mtype == "document":
        ext_lower = ext.lower()
        if ext_lower in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
            mtype = "video"
        elif ext_lower in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
            mtype = "image"
        elif ext_lower in (".ppt", ".pptx"):
            mtype = "document"

    material = CourseMaterial(
        course_id=course_id,
        title=title or file.filename,
        material_type=mtype,
        file_url=file_url,
        file_size=file_size,
        sort_order=sort_order,
        created_by=current_user["id"],
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)

    # 변환 가능한 파일이면 자동으로 백그라운드 변환 시작
    if mtype == "document" and ext.lower() in (".pdf", ".ppt", ".pptx"):
        try:
            from app.api.v1.viewer import start_conversion
            # 백그라운드 스레드에서 실행되므로 블로킹되지 않음
            start_conversion(file_url)
        except Exception:
            pass  # 변환 실패는 사용자 경험에 영향을 주지 않음

    return ApiResponse(message="파일이 업로드되었습니다.", data={
        "id": material.id,
        "title": material.title,
        "material_type": material.material_type,
        "file_url": file_url,
        "file_size": file_size,
    })


# ============================================================
# 자료 수정 (본사/원장/교사)
# ============================================================

@router.put("/materials/{material_id}")
async def update_material(
    material_id: int,
    data: CourseMaterialUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CourseMaterial).where(CourseMaterial.id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(material, key, val)
    await db.commit()
    return ApiResponse(message="자료가 수정되었습니다.")


# ============================================================
# 자료 삭제 (본사/원장/교사)
# ============================================================

@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CourseMaterial).where(CourseMaterial.id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="자료를 찾을 수 없습니다.")

    # 연관 진행률도 삭제
    await db.execute(
        LearningProgress.__table__.delete().where(
            LearningProgress.material_id == material_id
        )
    )
    await db.delete(material)
    await db.commit()
    return ApiResponse(message="자료가 삭제되었습니다.")


# ============================================================
# 학습 진행률 업데이트 (학생)
# ============================================================

@router.post("/{course_id}/progress")
async def update_progress(
    course_id: int,
    data: LearningProgressUpdate,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]

    # material_id 또는 block_index 중 하나는 반드시 필요
    if data.material_id is None and data.block_index is None:
        raise HTTPException(status_code=422, detail="material_id 또는 block_index가 필요합니다.")

    # 블록 진행 (material_id 없이 block_index로)
    if data.block_index is not None:
        # 해당 강좌의 콘텐츠 블록 범위 검증
        course = (await db.execute(
            select(Course).where(Course.id == course_id)
        )).scalar()
        blocks = (course.content_blocks or []) if course else []
        if data.block_index < 0 or data.block_index >= len(blocks):
            raise HTTPException(status_code=404, detail="콘텐츠 블록을 찾을 수 없습니다.")
        # divider(구분선)는 비학습 블록 — 진행 기록 거부 (통계 오염 방지)
        if isinstance(blocks[data.block_index], dict) and blocks[data.block_index].get("type") == "divider":
            raise HTTPException(status_code=422, detail="구분선은 학습 진행 대상이 아닙니다.")

        result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.student_id == student_id,
                LearningProgress.course_id == course_id,
                LearningProgress.material_id.is_(None),
                LearningProgress.block_index == data.block_index,
            )
        )
    else:
        result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.student_id == student_id,
                LearningProgress.material_id == data.material_id,
            )
        )
    progress = result.scalar_one_or_none()

    if not progress:
        progress = LearningProgress(
            student_id=student_id,
            material_id=data.material_id if data.block_index is None else None,
            block_index=data.block_index,
            course_id=course_id,
            is_completed=data.is_completed,
            progress_percent=data.progress_percent,
            last_viewed_at=datetime.now(timezone.utc),
        )
        db.add(progress)
    else:
        progress.is_completed = data.is_completed
        progress.progress_percent = data.progress_percent
        progress.last_viewed_at = datetime.now(timezone.utc)
        if data.is_completed:
            progress.completed_at = datetime.now(timezone.utc)

    await db.commit()

    # 모든 자료(파일+블록)를 완료했는지 확인 → 포인트 지급
    if data.is_completed:
        total = (await db.execute(
            select(func.count(CourseMaterial.id))
            .where(CourseMaterial.course_id == course_id, CourseMaterial.is_active == True)
        )).scalar() or 0
        # 콘텐츠 블록도 총 자료 수에 포함
        course = (await db.execute(
            select(Course).where(Course.id == course_id)
        )).scalar()
        if course and course.content_blocks:
            total += len(course.content_blocks)
        done = (await db.execute(
            select(func.count(LearningProgress.id))
            .where(
                LearningProgress.student_id == student_id,
                LearningProgress.course_id == course_id,
                LearningProgress.is_completed == True,
            )
        )).scalar() or 0
        if total > 0 and done >= total:
            # 이미 포인트를 지급했는지 확인 (중복 방지)
            existing = await db.execute(
                select(func.count(PointTransaction.id))
                .where(
                    PointTransaction.user_id == student_id,
                    PointTransaction.transaction_type == "course_complete",
                    PointTransaction.reference_id == course_id,
                )
            )
            if (existing.scalar() or 0) == 0:
                enrollment = await db.execute(
                    select(Enrollment).where(
                        Enrollment.student_id == student_id,
                        Enrollment.course_id == course_id,
                    )
                )
                enrollment_row = enrollment.scalar_one_or_none()
                await award_points_for_course_completion(
                    db, student_id, course_id,
                    enrollment_row.id if enrollment_row else course_id,
                )

    return ApiResponse(message="진행률이 저장되었습니다.")


# ============================================================
# 학습 통계 (학생)
# ============================================================

@router.get("/{course_id}/progress/stats")
async def get_progress_stats(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]

    # 전체 자료 수
    total_materials = (await db.execute(
        select(func.count(CourseMaterial.id))
        .where(
            CourseMaterial.course_id == course_id,
            CourseMaterial.is_active == True,
        )
    )).scalar() or 0

    # 강좌명
    course = (await db.execute(
        select(Course.name).where(Course.id == course_id)
    )).scalar() or ""

    # 완료한 자료 수
    completed = (await db.execute(
        select(func.count(LearningProgress.id))
        .where(
            LearningProgress.student_id == student_id,
            LearningProgress.course_id == course_id,
            LearningProgress.is_completed == True,
        )
    )).scalar() or 0

    # 진행 중인 자료 수
    in_progress = (await db.execute(
        select(func.count(LearningProgress.id))
        .where(
            LearningProgress.student_id == student_id,
            LearningProgress.course_id == course_id,
            LearningProgress.is_completed == False,
            LearningProgress.progress_percent > 0,
        )
    )).scalar() or 0

    completion_rate = round((completed / total_materials * 100)) if total_materials > 0 else 0

    return ApiResponse(data={
        "total_materials": total_materials,
        "completed": completed,
        "in_progress": in_progress,
        "completion_rate": completion_rate,
        "course_name": course,
    })
