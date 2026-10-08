"""
🔔 SSE 실시간 알림 스트림
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse

from app.core.security import get_current_user, decode_token
from app.core.event_bus import event_bus
from app.models import Notification
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

router = APIRouter(prefix="/sse", tags=["알림"])

# ── 학생 알림 화이트리스트 ──────────────────────────────────────────
# 학생 알림 페이지에는 '의미 있는' 알림만 노출한다.
#   notice              : 공지사항
#   learning_added      : 학습내용(강좌 자료) 추가
#   portfolio_*         : 포트폴리오 승인/반려/피드백/제출/현황
# 과거에 대량 생성된 course_updated(강좌 자료 변경 스팸) 등은 제외한다.
STUDENT_ALLOWED_TYPES = {
    "notice",
    "learning_added",
    "portfolio_submitted",
    "portfolio_approved",
    "portfolio_rejected",
    "portfolio_revision",
    "portfolio_feedback",
    "portfolio_status",
}


async def get_user_from_query(token: Optional[str] = Query(None)):
    """SSE EventSource용 — query param으로 인증"""
    if token:
        payload = decode_token(token)
        user_id = payload.get("sub")
        role = payload.get("role")
        name = payload.get("name") or payload.get("username", "")
        username = payload.get("username", "")
        if user_id and role:
            return {"id": user_id, "role": role, "name": name, "username": username}
    # fallback: Authorization header
    raise HTTPException(status_code=401, detail="인증 필요")


@router.get("/stream")
async def sse_stream(current_user: dict = Depends(get_user_from_query)):
    """SSE 실시간 알림 스트림 — 클라이언트가 연결을 유지"""
    user_id = current_user["id"]
    queue = event_bus.subscribe(user_id)

    async def event_generator():
        try:
            yield f"data: {{\"type\": \"connected\", \"data\": {{\"user_id\": {user_id}}}}}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/notifications")
async def get_notifications(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 30,
):
    """알림 목록 조회 (최신순)

    학생(role='student')에게는 화이트리스트에 포함된 알림만 노출한다.
    (공지 / 학습내용 추가 / 포트폴리오 승인·반려·피드백·현황)
    """
    from app.schemas import ApiResponse
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user["id"])
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if current_user.get("role") == "student":
        stmt = stmt.where(Notification.notif_type.in_(STUDENT_ALLOWED_TYPES))
    result = await db.execute(stmt)
    notifications = result.scalars().all()
    return ApiResponse(data={
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "type": n.notif_type,
                "is_read": n.is_read,
                "created_at": str(n.created_at) if n.created_at else "",
            } for n in notifications
        ],
        "total": len(notifications)
    })


@router.get("/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """읽지 않은 알림 개수 (학생은 화이트리스트 기준)"""
    from app.schemas import ApiResponse
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user["id"], Notification.is_read == False)
    )
    if current_user.get("role") == "student":
        stmt = stmt.where(Notification.notif_type.in_(STUDENT_ALLOWED_TYPES))
    result = await db.execute(stmt)
    count = result.scalar() or 0
    return ApiResponse(data={"unread_count": count})


@router.post("/notifications/{notif_id}/read")
async def mark_read(
    notif_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """알림 읽음 처리"""
    from app.schemas import ApiResponse
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id, Notification.user_id == current_user["id"])
        .values(is_read=True)
    )
    await db.commit()
    return ApiResponse(data={"id": notif_id})


@router.post("/notifications/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """모든 알림 읽음 처리 (학생은 노출 중인 알림만)"""
    from app.schemas import ApiResponse
    stmt = (
        update(Notification)
        .where(Notification.user_id == current_user["id"], Notification.is_read == False)
    )
    if current_user.get("role") == "student":
        stmt = stmt.where(Notification.notif_type.in_(STUDENT_ALLOWED_TYPES))
    stmt = stmt.values(is_read=True)
    await db.execute(stmt)
    await db.commit()
    return ApiResponse(message="모든 알림을 읽음 처리했습니다.")
