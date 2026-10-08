"""
⚙️ 플랫폼 관리 API
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, or_

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import User, Branch, Payment, AccessLog, Notice
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/platform", tags=["플랫폼 관리"])


def _now_kst_str():
    """한국 시간(KST, UTC+9) 기준 'YYYY-MM-DDTHH:MM' 문자열.
    공지 팝업의 popup_start/popup_end 는 관리자가 브라우저(datetime-local)에서
    KST 로 입력하므로, 서버(UTC) 비교 시 9시간 시차로 팝업이 누락되는 것을 방지한다."""
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M")


# ============================================================
# 시스템 상태
# ============================================================

@router.get("/system/status")
async def get_system_status(
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar()
    total_branches = (await db.execute(select(func.count(Branch.id)))).scalar()
    total_payments = (await db.execute(
        select(func.count(Payment.id)).where(Payment.status == "completed")
    )).scalar()
    total_revenue = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.status == "completed")
    )).scalar()

    return ApiResponse(data={
        "status": "operational",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_users": total_users or 0,
            "active_users": active_users or 0,
            "total_branches": total_branches or 0,
            "total_payments": total_payments or 0,
            "total_revenue": float(total_revenue or 0),
        },
        "version": "1.0.0",
    })


# ============================================================
# 시스템 로그
# ============================================================

@router.get("/system/logs")
async def get_system_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(AccessLog).order_by(AccessLog.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    logs = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": l.id, "user_id": l.user_id, "action": l.action,
            "ip_address": l.ip_address, "details": l.details,
            "created_at": str(l.created_at),
        } for l in logs],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 사용자 분석
# ============================================================

@router.get("/analytics/users")
async def get_user_analytics(
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """역할별 사용자 분포"""
    result = await db.execute(
        select(User.role, func.count(User.id))
        .group_by(User.role)
    )
    rows = result.all()

    return ApiResponse(data={
        "role_distribution": [{"role": r[0], "count": r[1]} for r in rows],
    })


# ============================================================
# 매출 분석
# ============================================================

@router.get("/analytics/revenue")
async def get_revenue_analytics(
    period: str = Query("monthly", pattern="^(daily|monthly|yearly)$"),
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """기간별 매출 분석"""
    if period == "daily":
        date_trunc = "date(paid_at)"
    elif period == "monthly":
        date_trunc = "strftime('%Y-%m', paid_at)"
    else:
        date_trunc = "strftime('%Y', paid_at)"

    query = text(f"""
        SELECT {date_trunc} AS period, SUM(amount) AS revenue
        FROM payments
        WHERE status = 'completed'
        GROUP BY period
        ORDER BY period DESC
        LIMIT 12
    """)
    result = await db.execute(query)
    rows = result.all()

    return ApiResponse(data=[{
        "period": r[0], "revenue": float(r[1] or 0),
    } for r in rows])


# ============================================================
# 공지 팝업 (모든 역할 인증 사용자)
# ============================================================

@router.get("/notices/popup")
async def get_active_popups(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """전체 역할 — 기간 내 활성 공지 팝업 목록 (전체/특정 사용자 매칭)"""
    now_str = _now_kst_str()
    result = await db.execute(
        select(Notice)
        .where(
            Notice.is_popup == True,
            Notice.status == "published",
            or_(
                Notice.popup_start.is_(None),
                Notice.popup_start == "",
                Notice.popup_start <= now_str,
            ),
            or_(
                Notice.popup_end.is_(None),
                Notice.popup_end == "",
                Notice.popup_end >= now_str,
            ),
        )
        .order_by(Notice.created_at.desc())
    )
    popups = result.scalars().all()

    user_name = (current_user.get("name") or "").strip()
    user_id = str(current_user.get("id") or "")
    user_role = (current_user.get("role") or "").strip().lower()

    # 역할명 ↔ role 값 매핑 (대표님 요구: 역할 명칭으로 대상 지정)
    # 예: "학생,에듀케어,학부모,원장" 또는 "전체"
    # 관리자 화면은 저장값이 한글("에듀케어") 또는 영문("educare") 어느 쪽이든 올 수 있으므로
    # 두 형태 모두 키로 등록한다. (branch_admin/manager/staff = 에듀케어 계정의 실제 role)
    ROLE_ALIASES = {
        "학생": ["student"], "student": ["student"],
        "학부모": ["parent"], "parent": ["parent"],
        "원장": ["director"], "director": ["director"],
        "강사": ["teacher"], "teacher": ["teacher"],
        "관리자": ["admin", "super_admin"], "admin": ["admin", "super_admin"],
        "에듀케어": ["educare", "branch_admin", "branch_manager", "branch_staff"],
        "educare": ["educare", "branch_admin", "branch_manager", "branch_staff"],
        "branch_admin": ["branch_admin", "branch_manager", "branch_staff", "educare"],
        "branch_manager": ["branch_admin", "branch_manager", "branch_staff", "educare"],
        "branch_staff": ["branch_admin", "branch_manager", "branch_staff", "educare"],
        "에듀케어원장": ["educare_director"], "educare_director": ["educare_director"],
        "메인페이지": ["main"], "main": ["main"],
    }

    def _popup_target_match(targets_str, u_name, u_id, u_role):
        targets = (targets_str or "all").strip()
        if not targets or targets.lower() == "all" or targets.strip() == "전체":
            return True
        items = [t.strip() for t in targets.split(",") if t.strip()]
        for item in items:
            # 1) 사용자명/ID 정확 일치 (기존 방식 유지)
            if item == u_name or item == u_id:
                return True
            # 2) 역할명 매칭 (신규) — "학생"/"원장"/"에듀케어" 등
            roles = ROLE_ALIASES.get(item)
            if roles and u_role in roles:
                return True
            # 3) role 값 직접 매칭 (예: "student")
            if item.lower() == u_role:
                return True
        return False

    matched = []
    for p in popups:
        if _popup_target_match(p.popup_targets, user_name, user_id, user_role):
            matched.append(p)

    return ApiResponse(data=[{
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "author": n.author,
        "is_popup": n.is_popup,
        "popup_start": n.popup_start,
        "popup_end": n.popup_end,
        "popup_targets": n.popup_targets,
        "publish_targets": getattr(n, "publish_targets", None),
        "images": getattr(n, "images", None),
        "created_at": str(n.created_at) if n.created_at else None,
    } for n in matched])


# ============================================================
# 공지사항 — 메인페이지 / 사용자 페이지 노출 (publish_targets 기반)
# ============================================================

def _pt_matches(pt, want):
    """publish_targets 에 want(main/student/parent/director/educare) 포함 여부."""
    if not pt:
        return False
    parts = [p.strip().lower() for p in str(pt).split(",") if p.strip()]
    if "all" in parts or "전체" in parts:
        return True
    return want.lower() in parts


@router.get("/notices/public")
async def get_public_notices(
    limit: int = Query(6, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """메인페이지(비로그인 공개) — publish_targets 에 main 포함된 발행 공지.
    최신순, 상단고정 우선."""
    result = await db.execute(
        select(Notice)
        .where(Notice.status == "published")
        .order_by(Notice.is_pinned.desc(), Notice.created_at.desc())
        .limit(100)
    )
    rows = result.scalars().all()
    picked = [n for n in rows if _pt_matches(getattr(n, "publish_targets", None), "main")][:limit]

    return ApiResponse(data=[{
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "author": n.author,
        "is_pinned": bool(n.is_pinned),
        "publish_targets": getattr(n, "publish_targets", None),
        "images": getattr(n, "images", None),
        "created_at": str(n.created_at) if n.created_at else None,
    } for n in picked])


@router.get("/notices/popup-public")
async def get_public_popups(
    db: AsyncSession = Depends(get_db),
):
    """메인페이지(비로그인) — publish_targets 에 main 포함된 활성 팝업 공지.
    기간(popup_start/popup_end) 필터 적용."""
    now_str = _now_kst_str()
    result = await db.execute(
        select(Notice)
        .where(
            Notice.is_popup == True,
            Notice.status == "published",
            or_(
                Notice.popup_start.is_(None),
                Notice.popup_start == "",
                Notice.popup_start <= now_str,
            ),
            or_(
                Notice.popup_end.is_(None),
                Notice.popup_end == "",
                Notice.popup_end >= now_str,
            ),
        )
        .order_by(Notice.created_at.desc())
    )
    rows = result.scalars().all()
    picked = [n for n in rows if _pt_matches(getattr(n, "publish_targets", None), "main")]

    return ApiResponse(data=[{
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "author": n.author,
        "is_popup": n.is_popup,
        "popup_start": n.popup_start,
        "popup_end": n.popup_end,
        "popup_targets": n.popup_targets,
        "publish_targets": getattr(n, "publish_targets", None),
        "images": getattr(n, "images", None),
        "created_at": str(n.created_at) if n.created_at else None,
    } for n in picked])


@router.get("/notices/for-role")
async def get_notices_for_role(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """역할별 사용자 페이지 — publish_targets 에 내 역할 포함된 발행 공지.
    (복수 선택 지원: 예 'main,student,parent')"""
    role = (current_user.get("role") or "").strip().lower()
    role_map = {
        "student": "student",
        "parent": "parent",
        "director": "director",
        "teacher": "director",
        "branch_admin": "educare",
        "branch_manager": "educare",
        "branch_staff": "educare",
    }
    want = role_map.get(role)

    result = await db.execute(
        select(Notice)
        .where(Notice.status == "published")
        .order_by(Notice.is_pinned.desc(), Notice.created_at.desc())
        .limit(200)
    )
    rows = result.scalars().all()

    if role in ("super_admin", "admin"):
        picked = list(rows)[:limit]
    elif want:
        picked = [n for n in rows if _pt_matches(getattr(n, "publish_targets", None), want)][:limit]
    else:
        picked = []

    return ApiResponse(data=[{
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "author": n.author,
        "is_pinned": bool(n.is_pinned),
        "publish_targets": getattr(n, "publish_targets", None),
        "images": getattr(n, "images", None),
        "created_at": str(n.created_at) if n.created_at else None,
    } for n in picked])
