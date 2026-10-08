"""
누비다플랫폼 — 강좌 폴더 CRUD API
폴더 관리 (최대 2단계 depth) + 강좌-폴더 연결
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models import CourseFolder, CourseFolderItem, Course
from app.schemas import ApiResponse, FolderCreate, FolderUpdate, FolderCourseAction

router = APIRouter(prefix="/headquarters", tags=["강좌 폴더"])


# ============================================================
# Helper: 전체 폴더 조회 후 트리 구축
# ============================================================
async def get_folder_tree(db: AsyncSession, category: str = None) -> list:
    """모든 폴더를 조회하여 트리 구조 + 강좌 개수 포함 반환
    - category가 지정되면 해당 카테고리 폴더 + category=NULL 폴더 반환
    - category가 없으면 전체 폴더 반환
    """
    query = select(CourseFolder).order_by(CourseFolder.sort_order, CourseFolder.id)
    if category:
        query = query.where(
            (CourseFolder.category == category) | (CourseFolder.category.is_(None))
        )
    result = await db.execute(query)
    all_folders = result.scalars().all()

    # 강좌 개수 + 활성 강좌 개수 집계 (각 폴더별 course_folder_items 수)
    from sqlalchemy import func, case
    from app.models import CourseFolderItem
    count_result = await db.execute(
        select(
            CourseFolderItem.folder_id,
            func.count(CourseFolderItem.course_id).label("cnt"),
            func.sum(case((Course.status == "active", 1), else_=0)).label("active_cnt")
        )
        .outerjoin(Course, CourseFolderItem.course_id == Course.id)
        .group_by(CourseFolderItem.folder_id)
    )
    folder_counts = {}
    folder_active_counts = {}
    for row in count_result.all():
        folder_counts[row.folder_id] = row.cnt
        folder_active_counts[row.folder_id] = row.active_cnt or 0

    # dict로 변환
    folder_dict = {}
    for f in all_folders:
        folder_dict[f.id] = {
            "id": f.id,
            "name": f.name,
            "parent_id": f.parent_id,
            "branch_id": f.branch_id,
            "category": f.category,
            "sort_order": f.sort_order,
            "course_count": folder_counts.get(f.id, 0),
            "active_course_count": folder_active_counts.get(f.id, 0),
            "created_at": str(f.created_at) if f.created_at else None,
            "children": [],
        }

    # 트리 구축 (최상위 노드만 반환)
    roots = []
    for f_id, f_data in folder_dict.items():
        if f_data["parent_id"] is None:
            roots.append(f_data)
        else:
            parent = folder_dict.get(f_data["parent_id"])
            if parent:
                parent["children"].append(f_data)

    # 자식 폴더의 강좌 개수를 부모 폴더에 합산 (2단계 depth)
    def aggregate_child_counts(folder):
        total_courses = folder["course_count"]
        total_active = folder["active_course_count"]
        for child in folder["children"]:
            child_courses, child_active = aggregate_child_counts(child)
            total_courses += child_courses
            total_active += child_active
        folder["course_count"] = total_courses
        folder["active_course_count"] = total_active
        return total_courses, total_active

    for root in roots:
        aggregate_child_counts(root)

    return roots


# ============================================================
# GET /folders — 전체 폴더 목록 (최상위 + 트리 구조)
# ============================================================
@router.get("/folders")
async def list_folders(
    category: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin", "director", "branch_admin", "branch_manager")),
):
    """전체 폴더 목록을 트리 구조로 반환 (최상위 폴더 + 자식 폴더)
    - ?category=maker_coding: 해당 카테고리 + 공용 폴더만 반환
    """
    try:
        tree = await get_folder_tree(db, category)
        return ApiResponse(data=tree)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 목록 조회 실패: {str(e)}")


# ============================================================
# POST /folders — 새 폴더 생성
# ============================================================
@router.post("/folders")
async def create_folder(
    data: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """새 폴더 생성 (parent_id 생략 시 최상위)"""
    try:
        # 부모 폴더 존재 확인
        if data.parent_id:
            parent = await db.get(CourseFolder, data.parent_id)
            if not parent:
                raise HTTPException(status_code=404, detail="부모 폴더를 찾을 수 없습니다.")
            # 최대 2단계 depth 검증
            if parent.parent_id is not None:
                raise HTTPException(status_code=400, detail="최대 2단계 depth까지만 허용됩니다.")

        folder = CourseFolder(name=data.name, parent_id=data.parent_id, category=data.category)
        db.add(folder)
        await db.commit()
        await db.refresh(folder)
        return ApiResponse(message="폴더가 생성되었습니다.", data={"id": folder.id, "name": folder.name})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 생성 실패: {str(e)}")


# ============================================================
# PUT /folders/{folder_id} — 폴더 정보 수정
# ============================================================
@router.put("/folders/{folder_id}")
async def update_folder(
    folder_id: int,
    data: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """폴더명/정렬순서/부모 변경"""
    try:
        folder = await db.get(CourseFolder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        update_data = data.model_dump(exclude_unset=True)
        if 'parent_id' in update_data:
            if data.parent_id == folder_id:
                raise HTTPException(status_code=400, detail="자기 자신을 부모로 설정할 수 없습니다.")
            if data.parent_id is not None:
                new_parent = await db.get(CourseFolder, data.parent_id)
                if not new_parent:
                    raise HTTPException(status_code=404, detail="부모 폴더를 찾을 수 없습니다.")
                # 부모 폴더가 이미 자식인 경우 방지 (순환 참조)
                if new_parent.parent_id == folder_id:
                    raise HTTPException(status_code=400, detail="순환 참조가 발생합니다.")
                # 최대 2단계 depth: 부모가 이미 자식이면 해당 폴더는 자식을 가질 수 없음
                if new_parent.parent_id is not None:
                    raise HTTPException(status_code=400, detail="최대 2단계 depth까지만 허용됩니다. 2단계 폴더는 하위 폴더를 가질 수 없습니다.")
            folder.parent_id = data.parent_id

        if data.name is not None:
            folder.name = data.name
        if data.sort_order is not None:
            folder.sort_order = data.sort_order
        if data.category is not None:
            folder.category = data.category

        await db.commit()
        await db.refresh(folder)
        return ApiResponse(message="폴더가 수정되었습니다.", data={"id": folder.id, "name": folder.name})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 수정 실패: {str(e)}")


# ============================================================
# DELETE /folders/{folder_id} — 폴더 삭제 (자식 폴더 + 연결 모두 정리)
# ============================================================
@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """폴더 삭제 — 자식 폴더 함께 삭제, 강좌는 유지 (CASCADE)"""
    try:
        folder = await db.get(CourseFolder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        # 자식 폴더도 함께 삭제 (CASCADE가 course_folder_items에는 적용되지만,
        # 자식 폴더 자체는 수동으로 삭제)
        children = await db.execute(
            select(CourseFolder).where(CourseFolder.parent_id == folder_id)
        )
        for child in children.scalars().all():
            # 자식 폴더의 course_folder_items는 FK CASCADE로 자동 삭제
            await db.delete(child)

        await db.delete(folder)
        await db.commit()
        return ApiResponse(message="폴더가 삭제되었습니다.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 삭제 실패: {str(e)}")


# ============================================================
# POST /folders/{folder_id}/courses — 강좌를 폴더에 추가
# ============================================================
@router.post("/folders/{folder_id}/courses")
async def add_course_to_folder(
    folder_id: int,
    data: FolderCourseAction,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin", "director", "branch_admin", "branch_manager")),
):
    """강좌를 폴더에 연결"""
    try:
        # 폴더 존재 확인
        folder = await db.get(CourseFolder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        # 강좌 존재 확인
        course = await db.get(Course, data.course_id)
        if not course:
            raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

        # 중복 확인
        existing = await db.execute(
            select(CourseFolderItem)
            .where(CourseFolderItem.folder_id == folder_id)
            .where(CourseFolderItem.course_id == data.course_id)
        )
        if existing.scalar_one_or_none():
            return ApiResponse(message="이미 폴더에 포함된 강좌입니다.")

        # 연결 생성
        link = CourseFolderItem(folder_id=folder_id, course_id=data.course_id)
        db.add(link)
        await db.commit()
        return ApiResponse(message="강좌가 폴더에 추가되었습니다.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"강좌 추가 실패: {str(e)}")


# ============================================================
# DELETE /folders/{folder_id}/courses/{course_id} — 강좌를 폴더에서 제거
# ============================================================
@router.delete("/folders/{folder_id}/courses/{course_id}")
async def remove_course_from_folder(
    folder_id: int,
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin", "director", "branch_admin", "branch_manager")),
):
    """강좌를 폴더에서 연결 해제"""
    try:
        result = await db.execute(
            select(CourseFolderItem)
            .where(CourseFolderItem.folder_id == folder_id)
            .where(CourseFolderItem.course_id == course_id)
        )
        link = result.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="해당 강좌가 폴더에 없습니다.")

        await db.delete(link)
        await db.commit()
        return ApiResponse(message="강좌가 폴더에서 제거되었습니다.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"강좌 제거 실패: {str(e)}")


# ============================================================
# GET /folders/{folder_id}/courses — 폴더 내 강좌 목록
# ============================================================
@router.get("/folders/{folder_id}/courses")
async def list_folder_courses(
    folder_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin", "director", "branch_admin", "branch_manager")),
):
    """특정 폴더에 속한 강좌 목록"""
    try:
        folder = await db.get(CourseFolder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        from sqlalchemy import func
        from app.schemas import PaginatedResponse

        # Join: course_folder_items → courses
        query = (
            select(Course)
            .join(CourseFolderItem, CourseFolderItem.course_id == Course.id)
            .where(CourseFolderItem.folder_id == folder_id)
            .order_by(CourseFolderItem.sort_order, Course.id)
        )

        # Pagination
        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0
        result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
        courses = result.scalars().all()

        return PaginatedResponse(
            data=[{
                "id": c.id,
                "title": c.name,
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "status": c.status,
                "created_at": str(c.created_at),
            } for c in courses],
            total=total or 0,
            page=page,
            per_page=per_page,
            total_pages=max(1, -(-(total or 0) // per_page)),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"강좌 목록 조회 실패: {str(e)}")


# ============================================================
# PUT /folders/{folder_id}/toggle — 폴더 내 모든 강좌 활성화/비활성화
# ============================================================
@router.put("/folders/{folder_id}/toggle")
async def toggle_folder_courses(
    folder_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """폴더 내 모든 강좌를 일괄 활성화(active)/비활성화(inactive)"""
    try:
        folder = await db.get(CourseFolder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")

        new_status = data.get("status", "active")
        if new_status not in ("active", "inactive"):
            raise HTTPException(status_code=400, detail="status는 'active' 또는 'inactive'만 가능합니다.")

        # 1) 이 폴더에 연결된 모든 강좌 ID 조회
        items = await db.execute(
            select(CourseFolderItem.course_id)
            .where(CourseFolderItem.folder_id == folder_id)
        )
        course_ids = [row[0] for row in items.all()]

        # 2) 자식 폴더 처리 (최대 2단계)
        children = await db.execute(
            select(CourseFolder).where(CourseFolder.parent_id == folder_id)
        )
        child_ids = [c.id for c in children.scalars().all()]
        for cid in child_ids:
            child_items = await db.execute(
                select(CourseFolderItem.course_id)
                .where(CourseFolderItem.folder_id == cid)
            )
            course_ids.extend(row[0] for row in child_items.all())

        if not course_ids:
            return ApiResponse(message="이 폴더에 강좌가 없습니다.", data={"updated": 0})

        # 3) 일괄 업데이트
        from sqlalchemy import update
        stmt = (
            update(Course)
            .where(Course.id.in_(course_ids))
            .values(status=new_status)
        )
        await db.execute(stmt)
        await db.commit()

        return ApiResponse(
            message=f"폴더 내 {len(course_ids)}개 강좌가 {'활성화' if new_status == 'active' else '비활성화'}되었습니다.",
            data={"updated": len(course_ids), "status": new_status}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"폴더 토글 실패: {str(e)}")
