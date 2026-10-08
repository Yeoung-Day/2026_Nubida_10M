"""
📁 포트폴리오 템플릿 API — 강좌별 포트폴리오 양식 관리
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.portfolio_template import PortfolioTemplate
from app.models import Course
from app.schemas import ApiResponse

router = APIRouter(prefix="/portfolio-templates", tags=["포트폴리오 템플릿"])


# ============================================================
# 템플릿 목록 조회
# ============================================================
@router.get("")
async def get_templates(
    course_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(PortfolioTemplate)
    if course_id is not None:
        query = query.where(PortfolioTemplate.course_id == course_id)
    if is_active is not None:
        query = query.where(PortfolioTemplate.is_active == is_active)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(PortfolioTemplate.sort_order.asc(), PortfolioTemplate.id.asc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    templates = result.scalars().all()

    # 강좌명 조회
    course_ids = [t.course_id for t in templates if t.course_id]
    courses = {}
    if course_ids:
        course_result = await db.execute(select(Course).where(Course.id.in_(course_ids)))
        for c in course_result.scalars().all():
            courses[c.id] = c.name

    return ApiResponse(data={
        "templates": [{
            "id": t.id,
            "course_id": t.course_id,
            "course_name": courses.get(t.course_id, ""),
            "title": t.title,
            "description": t.description,
            "guide_text": t.guide_text,
            "form_fields": t.form_fields if t.form_fields else [],
            "target_role": t.target_role,
            "is_active": t.is_active,
            "weeks": t.weeks if t.weeks else [],
            "days": t.days if t.days else [],
            "sort_order": t.sort_order or 0,
            "created_at": str(t.created_at) if t.created_at else None,
            "updated_at": str(t.updated_at) if t.updated_at else None,
        } for t in templates],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    })


# ============================================================
# 템플릿 단건 조회
# ============================================================
@router.get("/{template_id}")
async def get_template(
    template_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PortfolioTemplate).where(PortfolioTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")

    # 강좌명
    course_name = ""
    if template.course_id:
        course_result = await db.execute(select(Course).where(Course.id == template.course_id))
        course = course_result.scalar_one_or_none()
        course_name = course.name if course else ""

    return ApiResponse(data={
        "id": template.id,
        "course_id": template.course_id,
        "course_name": course_name,
        "title": template.title,
        "description": template.description,
        "guide_text": template.guide_text,
        "form_fields": template.form_fields if template.form_fields else [],
        "target_role": template.target_role,
        "is_active": template.is_active,
        "weeks": template.weeks if template.weeks else [],
        "days": template.days if template.days else [],
        "sort_order": template.sort_order or 0,
        "created_at": str(template.created_at) if template.created_at else None,
        "updated_at": str(template.updated_at) if template.updated_at else None,
    })


# ============================================================
# 템플릿 생성
# ============================================================
@router.post("")
async def create_template(
    data: dict,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    course_id = data.get("course_id")
    if not course_id:
        raise HTTPException(status_code=400, detail="course_id는 필수입니다.")

    # 강좌 존재 확인
    course_result = await db.execute(select(Course).where(Course.id == course_id))
    if not course_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="해당 강좌를 찾을 수 없습니다.")

    # 중복 체크 — 같은 강좌에 여러 템플릿 가능 (버전용)
    template = PortfolioTemplate(
        course_id=course_id,
        title=data.get("title", "포트폴리오"),
        description=data.get("description", ""),
        guide_text=data.get("guide_text", ""),
        form_fields=data.get("form_fields", []),
        target_role=data.get("target_role", "student"),
        is_active=data.get("is_active", True),
        weeks=data.get("weeks", []),
        days=data.get("days", []),
        sort_order=data.get("sort_order", 0),
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    return ApiResponse(message="포트폴리오 템플릿이 생성되었습니다.", data={"id": template.id})


# ============================================================
# 템플릿 수정
# ============================================================
@router.put("/{template_id}")
async def update_template(
    template_id: int,
    data: dict,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PortfolioTemplate).where(PortfolioTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")

    allowed = {"title", "description", "guide_text", "form_fields", "target_role", "is_active", "weeks", "days", "sort_order"}
    for k, v in data.items():
        if k in allowed:
            setattr(template, k, v)

    await db.commit()
    await db.refresh(template)
    return ApiResponse(message="포트폴리오 템플릿이 수정되었습니다.", data={"id": template.id})


# ============================================================
# 템플릿 삭제
# ============================================================
@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PortfolioTemplate).where(PortfolioTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")

    await db.delete(template)
    await db.commit()
    return ApiResponse(message="포트폴리오 템플릿이 삭제되었습니다.")
