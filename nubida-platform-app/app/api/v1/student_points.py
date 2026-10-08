"""
포인트 / 기프티콘 API — 학생 전용 (조회/신청)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import PointTransaction, GifticonSetting, GifticonRequest
from app.schemas import ApiResponse
from pydantic import BaseModel

router = APIRouter(prefix="/student", tags=["포인트/기프티콘 (학생)"])


class GifticonRequestCreate(BaseModel):
    gifticon_setting_id: int


# ============================================================
# 내 포인트 조회
# ============================================================

@router.get("/points")
async def get_my_points(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 포인트 잔액 + 거래내역"""
    user_id = current_user["id"]
    role = current_user.get("role")
    if role not in ("student", "super_admin", "admin"):
        raise HTTPException(status_code=403, detail="학생만 접근 가능합니다.")

    # 전체 획득 포인트 (points > 0)
    result = await db.execute(
        select(func.coalesce(func.sum(PointTransaction.points), 0))
        .where(PointTransaction.user_id == user_id, PointTransaction.points > 0)
    )
    total_earned = result.scalar() or 0

    # 전체 사용 포인트 (points < 0)
    result = await db.execute(
        select(func.coalesce(func.sum(PointTransaction.points), 0))
        .where(PointTransaction.user_id == user_id, PointTransaction.points < 0)
    )
    total_used = abs(result.scalar() or 0)

    # 잔액 = 획득 - 사용
    balance = total_earned - total_used

    # 최근 거래내역
    result = await db.execute(
        select(PointTransaction)
        .where(PointTransaction.user_id == user_id)
        .order_by(PointTransaction.created_at.desc())
        .limit(50)
    )
    txns = result.scalars().all()

    return ApiResponse(data={
        "balance": balance,
        "total_earned": total_earned,
        "total_used": total_used,
        "transactions": [{
            "id": t.id,
            "points": t.points,
            "transaction_type": t.transaction_type,
            "description": t.description,
            "reference_id": t.reference_id,
            "created_at": str(t.created_at) if t.created_at else None,
        } for t in txns],
    })


# ============================================================
# 기프티콘 상점
# ============================================================

@router.get("/gifticon-shop")
async def get_gifticon_shop(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 상점 목록"""
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
    } for g in items])


# ============================================================
# 기프티콘 신청
# ============================================================

@router.post("/gifticon-requests")
async def request_gifticon(
    req: GifticonRequestCreate,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    """기프티콘 신청"""
    user_id = current_user["id"]

    # 기프티콘 상품 확인
    gs = await db.get(GifticonSetting, req.gifticon_setting_id)
    if not gs or not gs.is_active:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")

    # 포인트 잔액 확인
    earned = await db.execute(
        select(func.coalesce(func.sum(PointTransaction.points), 0))
        .where(PointTransaction.user_id == user_id, PointTransaction.points > 0)
    )
    used = await db.execute(
        select(func.coalesce(func.sum(PointTransaction.points), 0))
        .where(PointTransaction.user_id == user_id, PointTransaction.points < 0)
    )
    balance = (earned.scalar() or 0) - abs(used.scalar() or 0)

    if balance < gs.points_required:
        raise HTTPException(status_code=400, detail=f"포인트가 부족합니다. (필요: {gs.points_required}p, 보유: {balance}p)")

    # 신청 생성
    new_req = GifticonRequest(
        user_id=user_id,
        gifticon_setting_id=req.gifticon_setting_id,
        points_used=gs.points_required,
        status="pending",
    )
    db.add(new_req)
    await db.flush()

    # 포인트 차감
    txn = PointTransaction(
        user_id=user_id,
        points=-gs.points_required,
        transaction_type="gifticon_exchange",
        reference_id=new_req.id,
        description=f"기프티콘 신청: {gs.name}",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(new_req)

    return ApiResponse(data={"id": new_req.id}, message=f"{gs.name} 신청이 완료되었습니다. 관리자 승인 후 지급됩니다.")


# ============================================================
# 내 기프티콘 신청 내역
# ============================================================

@router.get("/gifticon-requests")
async def get_my_gifticon_requests(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 기프티콘 신청 내역"""
    user_id = current_user["id"]
    result = await db.execute(
        select(GifticonRequest)
        .where(GifticonRequest.user_id == user_id)
        .order_by(GifticonRequest.requested_at.desc())
    )
    items = result.scalars().all()

    data = []
    for item in items:
        gs = await db.get(GifticonSetting, item.gifticon_setting_id)
        data.append({
            "id": item.id,
            "gifticon_name": gs.name if gs else "알 수 없음",
            "gifticon_type": gs.gifticon_type if gs else "",
            "points_used": item.points_used,
            "status": item.status,
            "admin_note": item.admin_note,
            "requested_at": str(item.requested_at) if item.requested_at else None,
            "processed_at": str(item.processed_at) if item.processed_at else None,
        })

    return ApiResponse(data=data)
