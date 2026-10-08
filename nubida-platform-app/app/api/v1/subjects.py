"""
📚 과목(교육명) 마스터 API
- 본사(super_admin/admin): 과목 CRUD · 순서 · 활성화 관리
- 원장(director) 포함 전체: 활성 과목 목록 조회 (화면 상단 과목 탭용)
- director_edu_materials.category / courses.subject 값을 과목명으로 연결하므로
  과목명 변경 시 해당 자료·강좌의 분류값도 함께 갱신한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models import Subject, DirectorEduMaterial, Course
from app.schemas import ApiResponse, SubjectCreate, SubjectUpdate

router = APIRouter(prefix="/subjects", tags=["과목(교육명) 마스터"])


def _serialize(s: Subject) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "sort_order": s.sort_order or 0,
        "is_active": bool(s.is_active),
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ============================================================
# 과목 목록 (전체 활성 과목 — 원장/본사 공통, 과목 탭 구성용)
# ============================================================

@router.get("")
async def list_subjects(
    include_inactive: bool = Query(False, description="비활성 과목 포함 여부"),
    current_user: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    q = select(Subject)
    if not include_inactive:
        q = q.where(Subject.is_active == True)
    result = await db.execute(q.order_by(Subject.sort_order.asc(), Subject.id.asc()))
    items = [_serialize(s) for s in result.scalars().all()]
    return ApiResponse(data={"items": items, "total": len(items)})


# ============================================================
# [본사] 과목 생성
# ============================================================

@router.post("")
async def create_subject(
    payload: SubjectCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="과목명을 입력해주세요.")

    dup = await db.execute(select(Subject).where(Subject.name == name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"이미 등록된 과목입니다: {name}")

    sort_order = payload.sort_order if payload.sort_order is not None else 0
    if sort_order == 0:
        max_row = await db.execute(select(func.max(Subject.sort_order)))
        sort_order = (max_row.scalar() or 0) + 1

    subject = Subject(name=name, sort_order=sort_order)
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return ApiResponse(message="과목이 추가되었습니다.", data=_serialize(subject))


# ============================================================
# [본사] 과목 수정 (이름/순서/활성)
# - 이름 변경 시 동일 과목명을 쓰는 교육자료(category)·강좌(subject)도 함께 변경
# ============================================================

@router.put("/{subject_id}")
async def update_subject(
    subject_id: int,
    payload: SubjectUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다.")

    old_name = subject.name
    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="과목명을 입력해주세요.")
        if new_name != old_name:
            dup = await db.execute(select(Subject).where(Subject.name == new_name, Subject.id != subject_id))
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"이미 등록된 과목입니다: {new_name}")
            # 연결 유지: 교육자료·강좌의 과목명도 함께 갱신
            await db.execute(
                update(DirectorEduMaterial)
                .where(DirectorEduMaterial.category == old_name)
                .values(category=new_name)
            )
            await db.execute(
                update(Course)
                .where(Course.subject == old_name)
                .values(subject=new_name)
            )
            data["name"] = new_name

    for key, value in data.items():
        setattr(subject, key, value)
    await db.commit()
    await db.refresh(subject)
    return ApiResponse(message="과목이 수정되었습니다.", data=_serialize(subject))


# ============================================================
# [본사] 과목 삭제
# - 과목 마스터 행만 제거. 자료·강좌의 과목명 텍스트는 유지(전체 탭에서 확인 가능,
#   탭 노출 대상에서만 제외 = 미분류 처리)
# ============================================================

@router.delete("/{subject_id}")
async def delete_subject(
    subject_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subject).where(Subject.id == subject_id))
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다.")

    await db.delete(subject)
    await db.commit()
    return ApiResponse(message=f"과목이 삭제되었습니다. ({subject.name})")
