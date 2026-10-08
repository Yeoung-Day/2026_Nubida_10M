"""
포인트 / 기프티콘 API — 본사 전용 (설정/관리)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import CoursePoint, PointTransaction, GifticonSetting, GifticonRequest, User
from app.schemas import ApiResponse, PaginatedResponse
from pydantic import BaseModel

router = APIRouter(prefix="/headquarters", tags=["포인트/기프티콘 (본사)"])


# ========== 요청 스키마 ==========

class PointSettingCreate(BaseModel):
    target_type: str  # 'course' | 'portfolio'
    target_id: Optional[int] = None
    points: int

class PointSettingUpdate(BaseModel):
    points: Optional[int] = None
    is_active: Optional[bool] = None

class GifticonSettingCreate(BaseModel):
    name: str
    gifticon_type: str
    value: int = 0
    points_required: int = 0
    thumbnail: str = ""
    sort_order: int = 0

class GifticonSettingUpdate(BaseModel):
    name: Optional[str] = None
    gifticon_type: Optional[str] = None
    value: Optional[int] = None
    points_required: Optional[int] = None
    thumbnail: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

class PointAdjustRequest(BaseModel):
    user_id: int
    points: int
    description: str = ""

# ============================================================
# 포인트 설정 CRUD
# ============================================================

@router.get("/point-settings")
async def get_point_settings(
    target_type: Optional[str] = None,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """포인트 설정 목록 조회"""
    query = select(CoursePoint).order_by(CoursePoint.updated_at.desc())
    if target_type:
        query = query.where(CoursePoint.target_type == target_type)
    result = await db.execute(query)
    settings = result.scalars().all()
    return ApiResponse(data=[{
        "id": s.id,
        "target_type": s.target_type,
        "target_id": s.target_id,
        "points": s.points,
        "is_active": s.is_active,
        "created_at": str(s.created_at) if s.created_at else None,
    } for s in settings])


@router.post("/point-settings")
async def create_point_setting(
    req: PointSettingCreate,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """포인트 설정 추가"""
    existing = await db.execute(
        select(CoursePoint).where(
            CoursePoint.target_type == req.target_type,
            CoursePoint.target_id == req.target_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 등록된 설정입니다.")

    setting = CoursePoint(
        target_type=req.target_type,
        target_id=req.target_id,
        points=req.points,
    )
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return ApiResponse(data={"id": setting.id, "points": setting.points}, message="포인트 설정이 추가되었습니다.")


@router.put("/point-settings/{setting_id}")
async def update_point_setting(
    setting_id: int,
    req: PointSettingUpdate,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """포인트 설정 수정"""
    setting = await db.get(CoursePoint, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="설정을 찾을 수 없습니다.")
    if req.points is not None:
        setting.points = req.points
    if req.is_active is not None:
        setting.is_active = req.is_active
    await db.commit()
    return ApiResponse(message="수정되었습니다.")


@router.delete("/point-settings/{setting_id}")
async def delete_point_setting(
    setting_id: int,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """포인트 설정 삭제"""
    setting = await db.get(CoursePoint, setting_id)
    if not setting:
        raise HTTPException(status_code=404, detail="설정을 찾을 수 없습니다.")
    await db.delete(setting)
    await db.commit()
    return ApiResponse(message="삭제되었습니다.")


# ============================================================
# 기프티콘 설정 CRUD
# ============================================================

@router.get("/gifticon-settings")
async def get_gifticon_settings(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 상품 설정 목록"""
    result = await db.execute(
        select(GifticonSetting).where(GifticonSetting.is_active == True).order_by(GifticonSetting.sort_order)
    )
    items = result.scalars().all()
    return ApiResponse(data=[{
        "id": g.id,
        "name": g.name,
        "gifticon_type": g.gifticon_type,
        "value": g.value,
        "points_required": g.points_required,
        "thumbnail": g.thumbnail,
        "sort_order": g.sort_order,
    } for g in items])


@router.post("/gifticon-settings")
async def create_gifticon_setting(
    req: GifticonSettingCreate,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 상품 추가"""
    item = GifticonSetting(**req.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ApiResponse(data={"id": item.id}, message="상품이 추가되었습니다.")


@router.put("/gifticon-settings/{item_id}")
async def update_gifticon_setting(
    item_id: int,
    req: GifticonSettingUpdate,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 상품 수정"""
    item = await db.get(GifticonSetting, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    return ApiResponse(message="수정되었습니다.")


@router.delete("/gifticon-settings/{item_id}")
async def delete_gifticon_setting(
    item_id: int,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 상품 삭제"""
    item = await db.get(GifticonSetting, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    await db.delete(item)
    await db.commit()
    return ApiResponse(message="삭제되었습니다.")


# ============================================================
# 기프티콘 신청 관리
# ============================================================

@router.get("/gifticon-requests")
async def get_gifticon_requests(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 신청 목록"""
    query = select(GifticonRequest)
    count_query = select(func.count(GifticonRequest.id))

    if status:
        query = query.where(GifticonRequest.status == status)
        count_query = count_query.where(GifticonRequest.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(GifticonRequest.requested_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    data = []
    for req_item in items:
        user = await db.get(User, req_item.user_id)
        gs = await db.get(GifticonSetting, req_item.gifticon_setting_id)
        data.append({
            "id": req_item.id,
            "user_name": user.name if user else "알 수 없음",
            "user_id": req_item.user_id,
            "gifticon_name": gs.name if gs else "알 수 없음",
            "gifticon_type": gs.gifticon_type if gs else "",
            "points_used": req_item.points_used,
            "status": req_item.status,
            "admin_note": req_item.admin_note,
            "requested_at": str(req_item.requested_at) if req_item.requested_at else None,
            "processed_at": str(req_item.processed_at) if req_item.processed_at else None,
        })

    return PaginatedResponse(data=data, total=total, page=page, per_page=per_page)


@router.post("/gifticon-requests/{request_id}/approve")
async def approve_gifticon_request(
    request_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 신청 승인"""
    req_item = await db.get(GifticonRequest, request_id)
    if not req_item:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if req_item.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")

    req_item.status = "approved"
    req_item.admin_id = current_user["id"]
    req_item.processed_at = func.now()
    await db.commit()
    return ApiResponse(message="승인되었습니다.")


@router.post("/gifticon-requests/{request_id}/reject")
async def reject_gifticon_request(
    request_id: int,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 신청 거절 (포인트 환불)"""
    req_item = await db.get(GifticonRequest, request_id)
    if not req_item:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if req_item.status != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 신청입니다.")

    req_item.status = "rejected"
    req_item.admin_id = current_user["id"]
    req_item.processed_at = func.now()

    # 포인트 환불
    refund = PointTransaction(
        user_id=req_item.user_id,
        points=req_item.points_used,  # + (환불)
        transaction_type="gifticon_exchange",
        reference_id=request_id,
        description=f"기프티콘 신청 거절로 인한 포인트 환불",
    )
    db.add(refund)
    await db.commit()
    return ApiResponse(message="거절되었습니다. 포인트가 환불되었습니다.")


# ============================================================
# 포인트 거래내역 전체 조회
# ============================================================

@router.get("/point-transactions")
async def get_all_point_transactions(
    user_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """전체 포인트 거래내역"""
    query = select(PointTransaction)
    count_query = select(func.count(PointTransaction.id))
    if user_id:
        query = query.where(PointTransaction.user_id == user_id)
        count_query = count_query.where(PointTransaction.user_id == user_id)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(PointTransaction.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    data = []
    for txn in items:
        user = await db.get(User, txn.user_id)
        data.append({
            "id": txn.id,
            "user_name": user.name if user else "",
            "user_id": txn.user_id,
            "points": txn.points,
            "transaction_type": txn.transaction_type,
            "reference_id": txn.reference_id,
            "description": txn.description,
            "created_at": str(txn.created_at) if txn.created_at else None,
        })

    return PaginatedResponse(data=data, total=total, page=page, per_page=per_page)


@router.post("/point-transactions/adjust")
async def adjust_points(
    req: PointAdjustRequest,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """포인트 수동 조정"""
    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    txn = PointTransaction(
        user_id=req.user_id,
        points=req.points,
        transaction_type="admin_adjust",
        description=req.description or f"관리자 조정: {req.points:+d}",
    )
    db.add(txn)
    await db.commit()
    return ApiResponse(message=f"{req.points:+d} 포인트가 조정되었습니다.")
