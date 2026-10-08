"""
📋 감사 로그 조회 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, date

from app.core.database import get_db
from app.core.security import require_role
from app.models import AccessLog
from app.schemas.audit import AuditLogResponse, AuditLogListResponse, AuditStatsResponse

router = APIRouter(prefix="/audit", tags=["감사"])


# ============================================================
# 감사 로그 목록 조회
# ============================================================
@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: int = Query(None, description="사용자 ID 필터"),
    action: str = Query(None, description="액션 검색어 (LIKE 검색)"),
    date_from: date = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    date_to: date = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """감사 로그 목록을 필터링하여 조회합니다 (관리자 전용)."""
    # 조건 구성
    conditions = []
    if user_id is not None:
        conditions.append(AccessLog.user_id == user_id)
    if action:
        conditions.append(AccessLog.action.ilike(f"%{action}%"))
    if date_from:
        conditions.append(AccessLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append(AccessLog.created_at <= datetime.combine(date_to, datetime.max.time()))

    where_clause = and_(*conditions) if conditions else True

    # 전체 개수
    count_query = select(func.count()).select_from(AccessLog).where(where_clause)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 페이지 계산
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    # 데이터 조회 (최신순)
    query = (
        select(AccessLog)
        .where(where_clause)
        .order_by(AccessLog.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    logs = result.scalars().all()

    return AuditLogListResponse(
        data=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ============================================================
# 감사 로그 단일 조회
# ============================================================
@router.get("/logs/{log_id}", response_model=AuditLogResponse)
async def get_audit_log(
    log_id: int,
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """감사 로그 단일 항목을 조회합니다."""
    query = select(AccessLog).where(AccessLog.id == log_id)
    result = await db.execute(query)
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=404, detail="감사 로그를 찾을 수 없습니다.")

    return AuditLogResponse.model_validate(log)


# ============================================================
# 감사 로그 통계 (대시보드용)
# ============================================================
@router.get("/stats", response_model=AuditStatsResponse)
async def get_audit_stats(
    current_user: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """감사 로그 대시보드 통계: 오늘 로그 수, 액션 유형별, 상위 사용자"""
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # 오늘 로그 수
    today_count_query = (
        select(func.count())
        .select_from(AccessLog)
        .where(
            and_(
                AccessLog.created_at >= today_start,
                AccessLog.created_at <= today_end,
            )
        )
    )
    today_count_result = await db.execute(today_count_query)
    total_today = today_count_result.scalar() or 0

    # 액션 유형별 통계 (상위 20개)
    action_stats_query = (
        select(AccessLog.action, func.count().label("count"))
        .group_by(AccessLog.action)
        .order_by(func.count().desc())
        .limit(20)
    )
    action_stats_result = await db.execute(action_stats_query)
    by_action = {row.action: row.count for row in action_stats_result}

    # 상위 사용자 (상위 10명, null 제외)
    user_stats_query = (
        select(AccessLog.user_id, func.count().label("count"))
        .where(AccessLog.user_id.isnot(None))
        .group_by(AccessLog.user_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    user_stats_result = await db.execute(user_stats_query)
    top_users = {str(row.user_id): row.count for row in user_stats_result}

    return AuditStatsResponse(
        data={
            "total_today": total_today,
            "by_action": by_action,
            "top_users": top_users,
        }
    )
