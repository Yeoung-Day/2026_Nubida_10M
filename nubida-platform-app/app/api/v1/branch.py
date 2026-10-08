from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role, generate_registration_code, create_unique_registration_code
from app.models import Branch, BranchSetting, Course, ClassSchedule, SchoolClass, ClassStudent, Enrollment, Payment, User, Studio, Notification, BranchReport, DirectorReport, EducationProgram, ProgramChapter, ProgramAssignment, CourseFolder, CourseFolderItem, Revenue, TuitionPayment, RevenueApproval, Category
from app.schemas import CourseCreate, CourseUpdate, ApiResponse, PaginatedResponse, BranchReportCreate

router = APIRouter(prefix="/branch", tags=["지사 운영"])


# ============================================================
# 매출 관리
# ============================================================

@router.get("/revenue")
async def get_revenue(
    period: str = "month",
    page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    from datetime import datetime, timedelta

    # branch_id 자동 설정
    branch_id = current_user.get("branch_id")
    if not branch_id and current_user.get("role") != "super_admin":
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # Base filter
    filters = [Payment.status == "completed"]
    if branch_id:
        filters.append(Payment.branch_id == branch_id)

    # Period filter
    now = datetime.utcnow()
    if period == "today":
        filters.append(func.date(Payment.paid_at) == func.current_date())
    elif period == "week":
        week_ago = now - timedelta(days=7)
        filters.append(Payment.paid_at >= week_ago)
    elif period == "month":
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        filters.append(Payment.paid_at >= month_start)

    # Stats query
    stats_query = select(
        func.count(Payment.id).label("count"),
        func.coalesce(func.sum(Payment.amount), 0).label("total")
    ).where(*filters)
    stats_result = await db.execute(stats_query)
    stats = stats_result.one()
    total_count = stats.count
    total_revenue = float(stats.total)

    # Today's stats (always computed from completed payments in branch)
    today_filters = [Payment.status == "completed", func.date(Payment.paid_at) == func.current_date()]
    if branch_id:
        today_filters.append(Payment.branch_id == branch_id)
    today_q = select(func.coalesce(func.sum(Payment.amount), 0)).where(*today_filters)
    today_revenue = float((await db.execute(today_q)).scalar() or 0)

    # Pending (미수금) stats
    pending_filters = [Payment.status.in_(["pending", "failed"])]
    if branch_id:
        pending_filters.append(Payment.branch_id == branch_id)
    pending_q = select(func.coalesce(func.sum(Payment.amount), 0)).where(*pending_filters)
    pending_revenue = float((await db.execute(pending_q)).scalar() or 0)

    # Revenue stats — 원장이 등록한 매출 (Revenue 테이블)
    revenue_filters = []
    if branch_id:
        revenue_filters.append(Revenue.branch_id == branch_id)

    # 월별 Revenue 통계 (period 무관)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_rev_filters = revenue_filters + [Revenue.created_at >= month_start]
    month_rev_q = select(
        func.coalesce(func.sum(Revenue.amount), 0),
        func.count(Revenue.id),
    ).where(*month_rev_filters)
    month_rev_result = await db.execute(month_rev_q)
    month_rev_row = month_rev_result.one()
    month_director_revenue = float(month_rev_row[0] or 0)
    month_director_revenue_count = int(month_rev_row[1] or 0)

    # 일별 Revenue 통계 (오늘)
    today_filters_rev = revenue_filters + [func.date(Revenue.created_at) == func.current_date()]
    today_rev_q = select(
        func.coalesce(func.sum(Revenue.amount), 0),
        func.count(Revenue.id),
    ).where(*today_filters_rev)
    today_rev_result = await db.execute(today_rev_q)
    today_rev_row = today_rev_result.one()
    today_director_revenue = float(today_rev_row[0] or 0)

    # period 필터 (테이블용)
    if period == "today":
        revenue_filters.append(func.date(Revenue.created_at) == func.current_date())
    elif period == "week":
        week_ago = now - timedelta(days=7)
        revenue_filters.append(Revenue.created_at >= week_ago)
    elif period == "month":
        revenue_filters.append(Revenue.created_at >= month_start)

    revenue_q = select(
        func.coalesce(func.sum(Revenue.amount), 0),
        func.count(Revenue.id),
    ).where(*revenue_filters)
    revenue_result = await db.execute(revenue_q)
    rev_row = revenue_result.one()
    director_revenue = float(rev_row[0] or 0)
    director_revenue_count = int(rev_row[1] or 0)

    # DirectorReport stats — 원장 월 보고서 매출
    dr_filters = [DirectorReport.status.in_(["submitted", "confirmed_by_branch", "confirmed_by_hq"])]
    if branch_id:
        dr_filters.append(DirectorReport.branch_id == branch_id)
    # period 매핑: year/month 필터
    if period == "month":
        dr_filters.append(DirectorReport.year == now.year)
        dr_filters.append(DirectorReport.month == now.month)
    elif period == "today":
        dr_filters.append(DirectorReport.year == now.year)
        dr_filters.append(DirectorReport.month == now.month)
    elif period == "week":
        dr_filters.append(DirectorReport.year == now.year)
        dr_filters.append(DirectorReport.month == now.month)

    dr_stats_q = select(
        func.coalesce(func.sum(DirectorReport.result_monthly_revenue), 0),
        func.count(DirectorReport.id),
    ).where(*dr_filters)
    dr_stats_result = await db.execute(dr_stats_q)
    dr_stats = dr_stats_result.one()
    dr_revenue = float(dr_stats[0] or 0)
    dr_count = int(dr_stats[1] or 0)

    # Total director revenue = Revenue 테이블 + DirectorReport 합계
    director_revenue_total = director_revenue + dr_revenue

    # Total payments query (individual records with joins)
    total_q = select(func.count(Payment.id)).where(*filters)
    total = (await db.execute(total_q)).scalar() or 0

    pay_query = (
        select(
            Payment.id,
            Payment.amount,
            Payment.method,
            Payment.status,
            Payment.paid_at,
            Payment.created_at,
            Payment.receipt_number,
            Payment.student_id,
            Payment.course_id,
            User.name.label("student_name"),
            User.phone.label("student_phone"),
            Course.name.label("course_name"),
        )
        .outerjoin(User, User.id == Payment.student_id)
        .outerjoin(Course, Course.id == Payment.course_id)
        .where(*filters)
        .order_by(Payment.paid_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(pay_query)
    rows = result.all()

    payments = []
    for r in rows:
        payments.append({
            "id": r.id,
            "amount": float(r.amount),
            "method": r.method or "cash",
            "status": r.status,
            "paid_at": str(r.paid_at) if r.paid_at else None,
            "created_at": str(r.created_at) if r.created_at else None,
            "receipt_number": r.receipt_number,
            "student_id": r.student_id,
            "student_name": r.student_name or "직접 등록",
            "student_phone": r.student_phone or "",
            "course_id": r.course_id,
            "course_name": r.course_name or "일반 매출",
            "item": (r.receipt_number if r.course_id == 0 or not r.course_name else r.course_name) or "수동 매출",
            "member": r.student_name or "직접 등록",
        })

    # Revenue 목록 조회 (period 필터 적용)
    rev_query = (
        select(
            Revenue.id,
            Revenue.amount,
            Revenue.method,
            Revenue.course_name,
            Revenue.created_at,
            Revenue.director_id,
            User.name.label("director_name"),
        )
        .outerjoin(User, User.id == Revenue.director_id)
        .where(*revenue_filters)
        .order_by(Revenue.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rev_result = await db.execute(rev_query)
    rev_rows = rev_result.all()

    revenue_list = []
    for r in rev_rows:
        revenue_list.append({
            "id": r.id,
            "amount": float(r.amount or 0),
            "method": r.method or "",
            "course_name": r.course_name or "",
            "created_at": str(r.created_at) if r.created_at else None,
            "director_id": r.director_id,
            "director_name": r.director_name or "",
        })

    # DirectorReport 목록 조회 (월 보고 매출)
    dr_list_query = select(
        DirectorReport.id,
        DirectorReport.result_monthly_revenue,
        DirectorReport.year,
        DirectorReport.month,
        DirectorReport.director_name,
        DirectorReport.created_at,
    ).where(*dr_filters).order_by(DirectorReport.year.desc(), DirectorReport.month.desc())
    dr_list_result = await db.execute(dr_list_query)
    dr_rows = dr_list_result.all()

    for r in dr_rows:
        revenue_list.append({
            "id": f"dr_{r.id}",
            "amount": float(r.result_monthly_revenue or 0),
            "method": "report",
            "course_name": f"{r.year}년 {r.month}월 원장 보고서",
            "created_at": str(r.created_at) if r.created_at else None,
            "director_id": None,
            "director_name": r.director_name or "원장",
        })

    # 총계에 DirectorReport 포함
    total_all = total + len(revenue_list)

    # 수익률 조회 (BranchSetting.payment_config)
    #   hq_royalty_rate : 본사 로열티율 % (기본 45)
    #   profit_rate     : 에듀케어 순수익율 % (기본 7) — 과세표준 기준
    #   income_tax_rate : 순수익 공제율 % (기본 3.3, 소득세3% + 지방소득세0.3%) — 순수익에서 차감
    #                     ※ 3.3%(사업소득세) 또는 10% 중 본사(지사 관리)에서 지정 가능
    # 부가세율 (매출은 부가세 포함 금액으로 저장됨 → 과세표준 = 매출 / 1.1)
    VAT_RATE = 10.0
    INCOME_TAX_RATE = 3.3
    hq_royalty_rate = 45
    profit_rate = 7
    income_tax_rate = INCOME_TAX_RATE
    try:
        bs_result = await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == branch_id)
        )
        bs = bs_result.scalar_one_or_none()
        if bs and bs.payment_config:
            hr = bs.payment_config.get("hq_royalty_rate")
            if hr is not None:
                hq_royalty_rate = float(hr)
            pr = bs.payment_config.get("profit_rate")
            if pr is not None:
                profit_rate = float(pr)
            it = bs.payment_config.get("income_tax_rate")
            if it is not None:
                income_tax_rate = float(it)
    except Exception:
        pass

    # 정산 계산 (부가세 10% 제외 = 과세표준 기준)
    #   과세표준(tax_base)     = 매출 / 1.1
    #   본사 로열티(royalty)    = 과세표준 × 45%
    #   에듀케어 순수익(profit) = 과세표준 × 7%   ← 45%와 무관, 과세표준 기준
    #   원장 수익(director)    = 과세표준 × 55%
    #   사업소득세/deduct(income_tax) = 에듀케어 순수익 × income_tax_rate%  ← 순수익 공제 (3.3% or 10%)
    #   실수령액(net_deposit)   = 에듀케어 순수익 - 사업소득세 (본사 → 에듀케어 입금액)
    vat_factor = 1 + (VAT_RATE / 100)
    tax_base = month_director_revenue / vat_factor
    vat_amount = month_director_revenue - tax_base
    royalty_amount = tax_base * hq_royalty_rate / 100
    my_profit = round(tax_base * profit_rate / 100)
    director_income = round(tax_base * (100 - hq_royalty_rate) / 100)
    income_tax = round(my_profit * income_tax_rate / 100)
    net_deposit = my_profit - income_tax

    return ApiResponse(data={
        "payments": payments,
        "revenues": revenue_list,
        "stats": {
            "today_revenue": today_revenue,
            "total_revenue": total_revenue,
            "total_count": total_count,
            "pending_revenue": pending_revenue,
            "director_revenue": director_revenue_total,
            "director_revenue_count": director_revenue_count + dr_count,
            "month_director_revenue": month_director_revenue,
            "today_director_revenue": today_director_revenue,
            "month_director_count": month_director_revenue_count,
            "period": period,
            "profit_rate": profit_rate,
            "hq_royalty_rate": hq_royalty_rate,
            "vat_rate": VAT_RATE,
            "income_tax_rate": income_tax_rate,
            "tax_base": round(tax_base),
            "vat_amount": round(vat_amount),
            "royalty_amount": round(royalty_amount),
            "director_income": director_income,
            "my_profit": my_profit,
            "income_tax": income_tax,
            "net_deposit": net_deposit,
        },
        "total": total_all,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total_all + per_page - 1) // per_page),
    })


@router.get("/revenue/monthly-summary")
async def get_monthly_summary(
    year: int = None,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """에듀케어 매출관리 — 월별 집계 + 소속 원장별 미수금/로열티 입금 현황.

    정산 기준 (부가세 10% 제외 = 과세표준):
      과세표준    = 매출 / 1.1
      본사 로열티  = 과세표준 × 45%
      에듀케어 순수익 = 과세표준 × 7%   ← 45%와 무관, 과세표준 기준
      원장 수익    = 과세표준 × 55%
      사업소득세/순수익공제 = 에듀케어 순수익 × income_tax_rate% (3.3% or 10%, 기본 3.3)
      실수령액    = 에듀케어 순수익 - 사업소득세 (본사 → 에듀케어 입금액)
    """
    VAT_RATE = 10.0
    INCOME_TAX_RATE = 3.3
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # 설정 (로열티율 / 순이익율 / 사업소득세율 / 입금 계좌)
    hq_royalty_rate, profit_rate, income_tax_rate = 45.0, 7.0, INCOME_TAX_RATE
    bank_info = {"bank_name": "", "account_number": "", "account_holder": ""}
    try:
        bs = (await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == branch_id)
        )).scalar_one_or_none()
        if bs and bs.payment_config:
            cfg = bs.payment_config
            if cfg.get("hq_royalty_rate") is not None:
                hq_royalty_rate = float(cfg["hq_royalty_rate"])
            if cfg.get("profit_rate") is not None:
                profit_rate = float(cfg["profit_rate"])
            if cfg.get("income_tax_rate") is not None:
                income_tax_rate = float(cfg["income_tax_rate"])
            for k in bank_info:
                if cfg.get(k):
                    bank_info[k] = cfg[k]
    except Exception:
        pass

    # 소속 원장 목록 (같은 branch_id 를 가진 director/원장)
    directors = (await db.execute(
        select(User.id, User.name).where(
            User.branch_id == branch_id,
            User.role.in_(["director"]),
        )
    )).all()
    dir_ids = [d[0] for d in directors]
    dir_names = {d[0]: d[1] for d in directors}

    # ── 월별 집계 ────────────────────────────────────────────
    # 소속 원장들의 월별 매출 합계 (revenues + director_reports.result_monthly_revenue)
    monthly = {}

    if dir_ids:
        rev_rows = (await db.execute(
            select(
                func.date_format(Revenue.created_at, "%Y-%m").label("ym"),
                func.coalesce(func.sum(Revenue.amount), 0).label("total"),
                func.count(Revenue.id).label("cnt"),
            )
            .where(Revenue.director_id.in_(dir_ids))
            .group_by("ym")
        )).all()
        for ym, total, cnt in rev_rows:
            if not ym:
                continue
            m = monthly.setdefault(ym, {"revenue": 0.0, "report_revenue": 0.0, "count": 0})
            m["revenue"] += float(total or 0)
            m["count"] += int(cnt or 0)

        dr_rows = (await db.execute(
            select(
                DirectorReport.year, DirectorReport.month,
                func.coalesce(func.sum(DirectorReport.result_monthly_revenue), 0),
            )
            .where(DirectorReport.director_id.in_(dir_ids))
            .group_by(DirectorReport.year, DirectorReport.month)
        )).all()
        for y, mo, tot in dr_rows:
            if not y or not mo:
                continue
            ym = f"{int(y):04d}-{int(mo):02d}"
            m = monthly.setdefault(ym, {"revenue": 0.0, "report_revenue": 0.0, "count": 0})
            m["report_revenue"] += float(tot or 0)

    # 월별 학생수 (원장별 total_students 합계 — director_reports 기준)
    students_by_ym = {}
    if dir_ids:
        st_rows = (await db.execute(
            select(
                DirectorReport.year, DirectorReport.month,
                func.coalesce(func.sum(DirectorReport.total_students), 0),
            )
            .where(DirectorReport.director_id.in_(dir_ids))
            .group_by(DirectorReport.year, DirectorReport.month)
        )).all()
        for y, mo, tot in st_rows:
            if y and mo:
                students_by_ym[f"{int(y):04d}-{int(mo):02d}"] = int(tot or 0)

    # 로열티 입금 현황 (RevenueApproval — 원장 → 본사 승인/지급)
    paids_by_ym = {}
    if dir_ids:
        ap_rows = (await db.execute(
            select(
                func.date_format(RevenueApproval.period_start, "%Y-%m").label("ym"),
                func.coalesce(func.sum(RevenueApproval.total_amount), 0),
                RevenueApproval.status,
            )
            .where(RevenueApproval.director_id.in_(dir_ids))
            .group_by("ym", RevenueApproval.status)
        )).all()
        for ym, tot, st in ap_rows:
            if not ym:
                continue
            paids_by_ym.setdefault(ym, {})[st or "pending"] = float(tot or 0)

    monthly_list = []
    for ym in sorted(monthly.keys(), reverse=True):
        d = monthly[ym]
        base = d["revenue"] + d["report_revenue"]
        # 부가세 10% 제외 → 과세표준 기준 정산
        tax_base = base / (1 + VAT_RATE / 100)
        vat_amount = base - tax_base
        royalty = tax_base * hq_royalty_rate / 100
        profit = tax_base * profit_rate / 100          # 과세표준 × 7%
        director_income = tax_base * (100 - hq_royalty_rate) / 100  # 과세표준 × 55%
        income_tax = round(profit * income_tax_rate / 100)          # 순수익 공제 (3.3% or 10%)
        net_deposit = round(profit) - income_tax                    # 본사 → 에듀케어 실수령액
        paid_map = paids_by_ym.get(ym, {})
        paid_amt = sum(v for k, v in paid_map.items() if k in ("approved", "paid"))
        monthly_list.append({
            "ym": ym,
            "total_revenue": round(base),
            "total_students": students_by_ym.get(ym, 0),
            "count": d["count"],
            "hq_royalty_rate": hq_royalty_rate,
            "profit_rate": profit_rate,
            "vat_rate": VAT_RATE,
            "income_tax_rate": income_tax_rate,
            "tax_base": round(tax_base),
            "vat_amount": round(vat_amount),
            "royalty_amount": round(royalty),
            "director_income": round(director_income),
            "my_profit": round(profit),
            "income_tax": income_tax,
            "net_deposit": net_deposit,
            "royalty_paid": round(paid_amt),
            "royalty_pending": round(max(royalty - paid_amt, 0)),
        })

    # ── 원장별 미수금 / 로열티 입금 현황 ─────────────────────
    directors_out = []
    for did in dir_ids:
        # 매출
        rev = (await db.execute(
            select(func.coalesce(func.sum(Revenue.amount), 0)).where(Revenue.director_id == did)
        )).scalar() or 0
        rep_rev = (await db.execute(
            select(func.coalesce(func.sum(DirectorReport.result_monthly_revenue), 0))
            .where(DirectorReport.director_id == did)
        )).scalar() or 0
        total_rev = float(rev) + float(rep_rev)

        # 학생수 (최신 보고서 기준)
        latest = (await db.execute(
            select(DirectorReport.total_students)
            .where(DirectorReport.director_id == did)
            .order_by(DirectorReport.year.desc(), DirectorReport.month.desc())
            .limit(1)
        )).scalar() or 0

        # 미수금 (tuition_payments 중 미납)
        unpaid = (await db.execute(
            select(func.coalesce(func.sum(TuitionPayment.amount), 0))
            .where(TuitionPayment.director_id == did, TuitionPayment.paid.is_(False))
        )).scalar() or 0
        unpaid_cnt = (await db.execute(
            select(func.count(TuitionPayment.id))
            .where(TuitionPayment.director_id == did, TuitionPayment.paid.is_(False))
        )).scalar() or 0

        # 부가세 10% 제외 → 과세표준 기준 정산
        tax_base = total_rev / (1 + VAT_RATE / 100)
        royalty = tax_base * hq_royalty_rate / 100
        profit = tax_base * profit_rate / 100
        income_tax = round(profit * income_tax_rate / 100)
        net_deposit = round(profit) - income_tax
        paid = (await db.execute(
            select(func.coalesce(func.sum(RevenueApproval.total_amount), 0))
            .where(
                RevenueApproval.director_id == did,
                RevenueApproval.status.in_(["approved", "paid"]),
            )
        )).scalar() or 0

        directors_out.append({
            "director_id": did,
            "director_name": dir_names.get(did, "원장"),
            "total_revenue": round(total_rev),
            "tax_base": round(tax_base),
            "total_students": int(latest),
            "royalty_amount": round(royalty),
            "director_income": round(tax_base * (100 - hq_royalty_rate) / 100),
            "my_profit": round(profit),
            "income_tax": income_tax,
            "net_deposit": net_deposit,
            "royalty_paid": round(float(paid)),
            "royalty_unpaid": round(max(royalty - float(paid), 0)),
            "tuition_unpaid": round(float(unpaid)),
            "tuition_unpaid_count": int(unpaid_cnt),
        })

    directors_out.sort(key=lambda x: x["royalty_unpaid"], reverse=True)

    return ApiResponse(data={
        "monthly": monthly_list,
        "directors": directors_out,
        "settings": {
            "hq_royalty_rate": hq_royalty_rate,
            "profit_rate": profit_rate,
            "income_tax_rate": income_tax_rate,
            **bank_info,
        },
    })


@router.get("/revenue/courses")
async def get_course_revenue(
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # 본사가 사용중지(is_public=0)한 카테고리 키 목록 → 해당 강좌 매출 제외
    hidden_q = await db.execute(
        select(Category.key).where(Category.is_public == False)  # noqa: E712
    )
    hidden_keys = {x for (x,) in hidden_q.all() if x}

    query = select(
        Payment.course_id,
        func.coalesce(func.sum(Payment.amount), 0).label("total")
    ).where(
        Payment.status == "completed",
        Payment.branch_id == branch_id
    ).group_by(Payment.course_id)

    result = await db.execute(query)
    rows = result.all()

    # 숨김 카테고리 강좌의 매출은 집계에서 제외
    if rows and hidden_keys:
        course_ids = [r[0] for r in rows if r[0] is not None]
        if course_ids:
            hq = await db.execute(
                select(Course.id).where(
                    Course.id.in_(course_ids),
                    Course.category.in_(list(hidden_keys)),
                )
            )
            blocked = {x for (x,) in hq.all() if x}
            rows = [r for r in rows if r[0] not in blocked]

    return ApiResponse(data=[{
        "course_id": r[0], "total_revenue": float(r[1])
    } for r in rows])


# ============================================================
# 강좌 관리
# ============================================================

@router.post("/courses")
async def create_course(
    data: CourseCreate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db)
):
    course = Course(**data.model_dump())
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return ApiResponse(message="강좌가 생성되었습니다.", data={"id": course.id})


@router.get("/courses")
async def get_courses(
    category: str = None, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")), db: AsyncSession = Depends(get_db)
):
    branch_id = current_user.get("branch_id")
    # super_admin은 branch_id 제한 없이 전체 조회
    query = select(Course)
    if branch_id:
        query = query.where(Course.branch_id == branch_id)
    query = query.where(Course.status == "active")
    if category:
        query = query.where(Course.category == category)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Course.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    courses = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": c.id, "name": c.name, "description": c.description,
            "subject": c.subject, "category": c.category,
            "price": float(c.price) if c.price else 0,
            "max_capacity": c.max_capacity, "status": c.status,
            "branch_id": c.branch_id
        } for c in courses],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page
    )


@router.put("/courses/{course_id}")
async def update_course(
    course_id: int, data: CourseUpdate,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(course, key, val)
    await db.commit()
    return ApiResponse(message="강좌가 수정되었습니다.", data={"id": course.id})


# ============================================================
# 직원 관리
# ============================================================

@router.get("/employees")
async def get_employees(
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
    query = select(User).where(
        User.role.in_(["branch_manager", "director", "branch_admin"]),
        User.is_active == True,
        User.branch_id == branch_id
    )
    result = await db.execute(query)
    employees = result.scalars().all()

    return ApiResponse(data=[{
        "id": e.id, "name": e.name, "email": e.email,
        "phone": e.phone, "role": e.role, "is_active": e.is_active
    } for e in employees])


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    employee = await db.get(User, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="직원/원장을 찾을 수 없습니다.")

    branch_id = current_user.get("branch_id")
    if branch_id and employee.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="해당 지사의 직원만 수정할 수 있습니다.")

    if "name" in data:
        employee.name = data["name"]
    if "email" in data:
        employee.email = data["email"]
    if "phone" in data:
        employee.phone = data["phone"]
    if "role" in data:
        employee.role = data["role"]
    if "is_active" in data:
        employee.is_active = bool(data["is_active"])

    await db.commit()
    await db.refresh(employee)
    return ApiResponse(message="수정되었습니다.")


@router.delete("/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    employee = await db.get(User, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="직원/원장을 찾을 수 없습니다.")

    branch_id = current_user.get("branch_id")
    if branch_id and employee.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="해당 지사의 직원만 삭제할 수 있습니다.")

    await db.delete(employee)
    await db.commit()
    return ApiResponse(message="삭제되었습니다.")


# ============================================================
# 결제 내역
# ============================================================

@router.get("/payments")
async def get_payments(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
    query = select(Payment).where(Payment.branch_id == branch_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Payment.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    payments = result.scalars().all()

    return PaginatedResponse(
        data=[{
            "id": p.id, "student_id": p.student_id, "course_id": p.course_id,
            "amount": float(p.amount), "method": p.method, "status": p.status,
            "paid_at": str(p.paid_at) if p.paid_at else None,
            "receipt_number": p.receipt_number, "created_at": str(p.created_at)
        } for p in payments],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page
    )


# ============================================================
# 대시보드 통계
# ============================================================

@router.get("/dashboard/stats")
async def get_branch_dashboard_stats(
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    branch_id = current_user.get("branch_id")
    if not branch_id:
        # super_admin 등 branch_id 없는 사용자: 전체 통계 반환
        total_courses = (await db.execute(
            select(func.count(Course.id))
        )).scalar() or 0

        total_students = (await db.execute(
            select(func.count(func.distinct(Enrollment.student_id)))
            .where(Enrollment.status == "active")
        )).scalar() or 0

        total_employees = (await db.execute(
            select(func.count(User.id)).where(
                User.role.in_(["director", "teacher", "branch_manager"]),
                User.is_active == True,
            )
        )).scalar() or 0

        today_attendance = 0

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = (await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                Payment.status == "completed",
                Payment.paid_at >= month_start,
            )
        )).scalar() or 0

        return ApiResponse(data={
            "total_courses": total_courses, "total_students": total_students,
            "total_employees": total_employees, "today_attendance": today_attendance,
            "monthly_revenue": float(monthly_revenue),
        })

    total_courses = (await db.execute(
        select(func.count(Course.id)).where(Course.branch_id == branch_id)
    )).scalar() or 0

    # Students: count through enrollments linked to courses in this branch
    total_students = (await db.execute(
        select(func.count(func.distinct(Enrollment.student_id)))
        .where(Enrollment.status == "active")
        .where(Enrollment.course_id.in_(
            select(Course.id).where(Course.branch_id == branch_id)
        ))
    )).scalar() or 0

    # Employees: count directors/teachers in this branch
    total_employees = (await db.execute(
        select(func.count(User.id)).where(
            User.branch_id == branch_id,
            User.role.in_(["director", "teacher", "branch_manager"]),
            User.is_active == True,
        )
    )).scalar() or 0

    today_attendance = 0  # simplified

    # Monthly revenue with month filter
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_revenue = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(
            Payment.status == "completed",
            Payment.branch_id == branch_id,
            Payment.paid_at >= month_start,
        )
    )).scalar() or 0

    return ApiResponse(data={
        "total_courses": total_courses,
        "total_students": total_students,
        "total_employees": total_employees,
        "today_attendance": today_attendance,
        "monthly_revenue": float(monthly_revenue),
    })


# ============================================================
# 수강생 관리 (branch-level)
# ============================================================

@router.get("/students")
async def get_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy.orm import aliased
    branch_id = current_user.get("branch_id")
    query = select(User).where(
        User.role == "student",
        User.is_active == True,
    )
    if branch_id:
        query = query.where(User.branch_id == branch_id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(User.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    students = result.scalars().all()

    # Fetch enrolled courses for each student
    student_ids = [s.id for s in students]
    enrollment_data = {}
    if student_ids:
        # enrollments → courses → course_folder_items → course_folders (traverse to root)
        enroll_result = await db.execute(
            select(
                Enrollment.student_id,
                Course.name,
                Enrollment.payment_status,
                Enrollment.course_id,
                CourseFolderItem.folder_id,
            )
            .join(Course, Course.id == Enrollment.course_id)
            .outerjoin(CourseFolderItem, CourseFolderItem.course_id == Course.id)
            .where(
                Enrollment.student_id.in_(student_ids),
                Enrollment.status == "active",
            )
        )
        # Load all folders for root lookup
        folder_rows = await db.execute(select(CourseFolder))
        all_folders = {f.id: f for f in folder_rows.scalars().all()}

        def get_root_folder_name(folder_id):
            """Walk up parent chain to find top-level folder name."""
            visited = set()
            fid = folder_id
            while fid and fid not in visited:
                visited.add(fid)
                folder = all_folders.get(fid)
                if not folder:
                    break
                if not folder.parent_id:
                    return folder.name
                fid = folder.parent_id
            return None

        for row in enroll_result.all():
            sid, cname, pstatus, cid, folder_id = row
            if sid not in enrollment_data:
                enrollment_data[sid] = []
            display_name = cname
            if folder_id:
                root_name = get_root_folder_name(folder_id)
                if root_name:
                    display_name = root_name
            enrollment_data[sid].append({
                "course_name": display_name,
                "course_id": cid,
                "payment_status": pstatus or "pending",
            })

    # Fetch director (원장) info per student via class_students → school_classes → director
    director_map = {}
    if student_ids:
        dir_result = await db.execute(
            select(ClassStudent.student_id, User.name.label("director_name"))
            .join(SchoolClass, SchoolClass.id == ClassStudent.class_id)
            .join(User, User.id == SchoolClass.director_id)
            .where(
                ClassStudent.student_id.in_(student_ids),
                ClassStudent.status == "active",
                SchoolClass.director_id.isnot(None),
            )
        )
        for sid, dname in dir_result.all():
            if sid not in director_map:
                director_map[sid] = []
            if dname and dname not in director_map[sid]:
                director_map[sid].append(dname)

    return PaginatedResponse(
        data=[{
            "id": s.id, "name": s.name, "email": s.email,
            "phone": s.phone, "grade": getattr(s, "grade", None),
            "status": "active" if s.is_active else "inactive",
            "created_at": str(s.created_at),
            "courses": enrollment_data.get(s.id, []),
            "director_name": ", ".join(director_map.get(s.id, [])) or "-",
        } for s in students],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/students/course-category-stats")
async def get_students_course_category_stats(
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """에듀케어 소속(지사 및 소속 원장 반) 학생들의 수강강좌 카테고리별 인원 집계.

    - 기준: enrollments(status=active) -> courses.category
    - 대상: 해당 에듀케어(branch_id) 소속 학생 + 소속 원장(반)에 배정된 학생
    - 카테고리 코드를 사람이 읽기 좋은 라벨로 변환해 반환
    """
    branch_id = current_user.get("branch_id")

    # 1) 대상 학생 ID 수집: (a) branch_id 소속, (b) 소속 원장의 반에 배정된 학생
    student_ids = set()

    if branch_id:
        r1 = await db.execute(
            select(User.id).where(
                User.role == "student",
                User.is_active == True,
                User.branch_id == branch_id,
            )
        )
        student_ids.update(x for (x,) in r1.all() if x)

        dir_rows = await db.execute(
            select(User.id).where(
                User.role == "director",
                User.branch_id == branch_id,
            )
        )
        director_ids = [x for (x,) in dir_rows.all() if x]
        if director_ids:
            cls_rows = await db.execute(
                select(SchoolClass.id).where(SchoolClass.director_id.in_(director_ids))
            )
            class_ids = [x for (x,) in cls_rows.all() if x]
            if class_ids:
                cs_rows = await db.execute(
                    select(ClassStudent.student_id).where(
                        ClassStudent.class_id.in_(class_ids),
                        ClassStudent.status == "active",
                    )
                )
                student_ids.update(x for (x,) in cs_rows.all() if x)

    student_ids = {sid for sid in student_ids if sid}
    if not student_ids:
        return ApiResponse(data={"categories": [], "total_students": 0, "total_enrollments": 0})

    # 2) 카테고리별 "서로 다른 학생 수" 집계
    rows = await db.execute(
        select(
            Course.category.label("category"),
            Enrollment.student_id.label("student_id"),
        )
        .join(Course, Course.id == Enrollment.course_id)
        .where(
            Enrollment.student_id.in_(list(student_ids)),
            Enrollment.status == "active",
        )
    )

    cat_students = {}
    for cat, sid in rows.all():
        code = (cat or "").strip() or "uncategorized"
        cat_students.setdefault(code, set()).add(sid)

    # 2-1) 본사가 사용중지(is_public=0)한 카테고리는 제외
    if cat_students:
        pub_q = await db.execute(
            select(Category.key).where(
                Category.key.in_(list(cat_students.keys())),
                Category.is_public == False,  # noqa: E712
            )
        )
        hidden = {x for (x,) in pub_q.all() if x}
        for code in hidden:
            cat_students.pop(code, None)

    # 3) 라벨 매핑
    LABELS = {
        "ai_robot": {"label": "AI로봇", "emoji": "🤖"},
        "ai_art": {"label": "AI아트", "emoji": "🎨"},
        "physical_ai_instructor_level_2": {"label": "피지컬 AI 지도사", "emoji": "🧑‍🏫"},
        "physical_ai": {"label": "피지컬 AI", "emoji": "🦾"},
    }

    def prettify(code: str) -> dict:
        if code in LABELS:
            return LABELS[code]
        pretty = code.replace("_", " ").strip()
        if pretty and pretty.isascii():
            pretty = " ".join(w.capitalize() for w in pretty.split())
        return {"label": pretty or "기타", "emoji": "📦"}

    categories = []
    for code, sids in cat_students.items():
        meta = prettify(code)
        categories.append({
            "category": code,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "count": len(sids),
        })

    categories.sort(key=lambda c: (-c["count"], c["label"]))

    return ApiResponse(data={
        "categories": categories,
        "total_students": len(student_ids),
        "total_enrollments": sum(c["count"] for c in categories),
    })


@router.post("/students")
async def create_student(
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.core.security import get_password_hash
    import random, string
    username = data.get("username") or (data.get("name", "student").lower().replace(" ", "_") + "_" + "".join(random.choices(string.digits, k=4)))
    password = data.get("password", "password123")
    student = User(
        username=username,
        email=data.get("email", f"{username}@example.com"),
        password_hash=get_password_hash(password),
        name=data.get("name", "학생"),
        phone=data.get("phone"),
        role="student",
        branch_id=current_user.get("branch_id"),
        registration_code=await create_unique_registration_code(db),
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return ApiResponse(message="수강생이 등록되었습니다.", data={"id": student.id, "username": username})


@router.put("/students/{student_id}")
async def update_student(
    student_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="수강생을 찾을 수 없습니다.")
    for field in ["name", "email", "phone", "grade", "is_active"]:
        if field in data:
            setattr(student, field, data[field])
    await db.commit()
    return ApiResponse(message="수강생 정보가 수정되었습니다.")


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="수강생을 찾을 수 없습니다.")
    student.is_active = False
    await db.commit()
    return ApiResponse(message="수강생이 삭제되었습니다.")


# ============================================================
# 공부방(스튜디오) 관리
# ============================================================

@router.get("/studios")
async def get_studios(
    branch_id: int = None,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Studio).order_by(Studio.id)
    result = await db.execute(query)
    studios = result.scalars().all()
    return ApiResponse(data=[{
        "id": s.id, "name": s.name,
        "director_name": s.admin_name or "",
        "director_id": None,
        "phone": s.admin_phone or "",
        "address": "",
        "student_count": 0,
        "course_count": 0,
        "status": s.status,
    } for s in studios])


@router.post("/studios")
async def create_studio(
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    studio = Studio(
        name=data.get("name", "공부방"),
        admin_name=data.get("director_name") or data.get("admin_name"),
        admin_phone=data.get("phone"),
        status=data.get("status", "active"),
    )
    db.add(studio)
    await db.commit()
    await db.refresh(studio)
    return ApiResponse(message="공부방이 등록되었습니다.", data={"id": studio.id})


@router.put("/studios/{studio_id}")
async def update_studio(
    studio_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Studio).where(Studio.id == studio_id))
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(status_code=404, detail="공부방을 찾을 수 없습니다.")
    field_map = {"name": "name", "director_name": "admin_name", "admin_name": "admin_name", "phone": "admin_phone", "status": "status"}
    for js_field, model_field in field_map.items():
        if js_field in data:
            setattr(studio, model_field, data[js_field])
    await db.commit()
    return ApiResponse(message="공부방 정보가 수정되었습니다.")


@router.delete("/studios/{studio_id}")
async def delete_studio(
    studio_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Studio).where(Studio.id == studio_id))
    studio = result.scalar_one_or_none()
    if not studio:
        raise HTTPException(status_code=404, detail="공부방을 찾을 수 없습니다.")
    await db.delete(studio)
    await db.commit()
    return ApiResponse(message="공부방이 삭제되었습니다.")


# ============================================================
# 매출 등록
# ============================================================

@router.post("/revenue")
async def create_revenue(
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    payment = Payment(
        student_id=0,  # 0 = 직접등록 (수동 매출)
        course_id=0,   # 0 = 일반 매출 (강좌 미연결)
        branch_id=data.get("branch_id") or current_user.get("branch_id") or 0,
        amount=data.get("amount", 0),
        method=data.get("method", "cash"),
        status="completed",
        paid_at=datetime.utcnow(),
        receipt_number=data.get("item") or data.get("receipt_number") or f"수동-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return ApiResponse(message="매출이 등록되었습니다.", data={"id": payment.id})


@router.put("/revenue/{payment_id}")
async def update_revenue(
    payment_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 내역 수정"""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="매출 내역을 찾을 수 없습니다.")

    update_fields = ["amount", "method", "status"]
    for field in update_fields:
        if field in data:
            setattr(payment, field, data[field])

    if "item" in data:
        payment.receipt_number = data["item"]
    if "paid_at" in data and data["paid_at"]:
        from datetime import datetime
        try:
            payment.paid_at = datetime.fromisoformat(str(data["paid_at"]))
        except (ValueError, TypeError):
            pass

    await db.commit()
    return ApiResponse(message="매출이 수정되었습니다.", data={"id": payment.id})


@router.delete("/revenue/{payment_id}")
async def delete_revenue(
    payment_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """매출 내역 삭제"""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="매출 내역을 찾을 수 없습니다.")

    await db.delete(payment)
    await db.commit()
    return ApiResponse(message="매출이 삭제되었습니다.")


# ============================================================
# 강좌 삭제
# ============================================================

@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")
    course.status = "inactive"
    await db.commit()
    return ApiResponse(message="강좌가 삭제되었습니다.")


# ============================================================
# 일정 관리
# ============================================================

@router.get("/schedule")
async def get_schedules(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    branch_id = current_user.get("branch_id")
    query = select(ClassSchedule).order_by(ClassSchedule.day_of_week, ClassSchedule.start_time)
    if branch_id:
        query = query.where(ClassSchedule.branch_id == branch_id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    schedules = result.scalars().all()
    return PaginatedResponse(
        data=[{
            "id": s.id,
            "course_id": s.course_id,
            "teacher_id": s.teacher_id,
            "title": s.title or "",
            "description": s.description or "",
            "day_of_week": s.day_of_week,
            "start_time": str(s.start_time)[:5] if s.start_time else "09:00",
            "end_time": str(s.end_time)[:5] if s.end_time else "10:00",
            "room": s.room or "",
            "date": str(s.date) if s.date else None,
            "created_at": str(s.created_at) if s.created_at else None,
        } for s in schedules],
        total=total, page=page, per_page=per_page,
        total_pages=max(1, (total + per_page - 1) // per_page),
    )


@router.post("/schedule")
async def create_schedule(
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, time as time_type
    
    # Parse title/description
    title = data.get("title") or data.get("course_name") or "일정"
    description = data.get("description") or data.get("notes", "")
    
    # Parse date → day_of_week (0=Sun, 6=Sat)
    day_of_week = None
    date_str = data.get("date") or data.get("scheduled_at", "")
    if date_str:
        try:
            parsed_date = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
            day_of_week = parsed_date.weekday()  # 0=Mon → convert to 1=Sun
            day_of_week = (day_of_week + 1) % 7  # SQL: 0=Sun
        except (ValueError, TypeError):
            pass
    
    # Parse time
    start_time = None
    end_time = None
    time_str = data.get("time") or data.get("start_time", "")
    if time_str:
        try:
            start_time = datetime.strptime(str(time_str)[:5], "%H:%M").time()
            # end = start + 1 hour
            end_hour = start_time.hour + 1
            end_minute = start_time.minute
            if end_hour >= 24:
                end_hour = 23
                end_minute = 59
            end_time = time_type(end_hour, end_minute)
        except (ValueError, TypeError):
            pass
    
    # Default time when not provided
    if not start_time:
        start_time = time_type(9, 0)  # 09:00 기본값
    if not end_time:
        end_time = time_type(10, 0)  # 10:00 기본값
    
    schedule = ClassSchedule(
        course_id=data.get("course_id") or 0,
        teacher_id=data.get("teacher_id") or current_user.get("id") or 0,
        branch_id=current_user.get("branch_id") or 0,
        title=title,
        description=description,
        day_of_week=day_of_week or data.get("day_of_week"),
        start_time=start_time,
        end_time=end_time or start_time,
        room=data.get("room") or data.get("location", ""),
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return ApiResponse(message="일정이 등록되었습니다.", data={"id": schedule.id})


@router.put("/schedule/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, time as time_type

    schedule = await db.get(ClassSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")

    # Update fields if provided
    if "title" in data:
        schedule.title = data["title"]
    if "description" in data:
        schedule.description = data.get("description", "")
    if "room" in data:
        schedule.room = data.get("room", "")
    if "day_of_week" in data:
        schedule.day_of_week = data["day_of_week"]

    # Parse date
    date_str = data.get("date") or data.get("scheduled_at", "")
    if date_str:
        try:
            parsed_date = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
            schedule.day_of_week = (parsed_date.weekday() + 1) % 7
        except (ValueError, TypeError):
            pass

    # Parse time
    time_str = data.get("time") or data.get("start_time", "")
    if time_str:
        try:
            schedule.start_time = datetime.strptime(str(time_str)[:5], "%H:%M").time()
            end_hour = schedule.start_time.hour + 1
            end_minute = schedule.start_time.minute
            if end_hour >= 24:
                end_hour = 23; end_minute = 59
            schedule.end_time = time_type(end_hour, end_minute)
        except (ValueError, TypeError):
            pass

    await db.commit()
    await db.refresh(schedule)
    return ApiResponse(message="일정이 수정되었습니다.")


@router.delete("/schedule/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    schedule = await db.get(ClassSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")
    await db.delete(schedule)
    await db.commit()
    return ApiResponse(message="일정이 삭제되었습니다.")


# ============================================================
# 알림 관리
# ============================================================

@router.get("/notifications")
async def get_notifications(
    branch_id: int = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.get("id")
    query = select(Notification).order_by(Notification.created_at.desc())
    if user_id:
        query = query.where(Notification.user_id == user_id)
    result = await db.execute(query)
    notifications = result.scalars().all()
    return ApiResponse(data=[{
        "id": n.id, "title": n.title, "content": n.content,
        "notif_type": n.notif_type, "is_read": n.is_read,
        "created_at": str(n.created_at),
    } for n in notifications])


@router.post("/notifications")
async def create_notification(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notif = Notification(
        user_id=data.get("user_id") or current_user.get("id"),
        title=data.get("title", "알림"),
        content=data.get("content", ""),
        notif_type=data.get("notif_type", "system"),
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return ApiResponse(message="알림이 생성되었습니다.", data={"id": notif.id})


# ============================================================
# 알림 설정 (notification_config) 조회/저장
# ============================================================

@router.get("/notification-settings")
async def get_notification_settings(
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사의 알림 설정(notification_config) 조회"""
    try:
        branch_id = current_user.get("branch_id")
        if not branch_id and current_user.get("role") != "super_admin":
            raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
        if not branch_id:
            return ApiResponse(data={"payment": True, "attendance": True, "schedule": False})

        result = await db.execute(select(BranchSetting).where(BranchSetting.branch_id == branch_id))
        setting = result.scalar_one_or_none()

        # 첫 접근 시 BranchSetting 자동 생성
        if not setting:
            setting = BranchSetting(branch_id=branch_id, notification_config={})
            db.add(setting)
            await db.commit()
            await db.refresh(setting)

        config = setting.notification_config or {}
        return ApiResponse(data={
            "payment": config.get("payment", True),
            "attendance": config.get("attendance", True),
            "schedule": config.get("schedule", False),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"알림 설정 조회 중 오류: {str(e)}")


@router.post("/notification-settings")
async def save_notification_settings(
    data: dict,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사의 알림 설정(notification_config) 저장"""
    try:
        branch_id = current_user.get("branch_id")
        if not branch_id and current_user.get("role") != "super_admin":
            raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
        if not branch_id:
            return ApiResponse(message="알림 설정이 저장되었습니다.", data=data)

        result = await db.execute(select(BranchSetting).where(BranchSetting.branch_id == branch_id))
        setting = result.scalar_one_or_none()
        if not setting:
            setting = BranchSetting(branch_id=branch_id)
            db.add(setting)
        config = setting.notification_config or {}
        if "payment" in data:
            config["payment"] = bool(data["payment"])
        if "attendance" in data:
            config["attendance"] = bool(data["attendance"])
        if "schedule" in data:
            config["schedule"] = bool(data["schedule"])
        setting.notification_config = config
        await db.commit()
        return ApiResponse(message="알림 설정이 저장되었습니다.", data=config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"알림 설정 저장 중 오류: {str(e)}")


# ============================================================
# 원장 검색 (코드 #000000)
# ============================================================

@router.get("/directors/search")
async def search_director_by_code(
    code: str = Query(..., description="원장 코드 (#XXXXXX)"),
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 코드(#XXXXXX)로 원장 정보 검색"""
    query = select(User).where(
        User.registration_code == code.strip(),
        User.role == "director",
        User.is_active == True,
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="해당 코드의 원장을 찾을 수 없습니다.")

    # 공부방(Studio) 정보도 함께 조회
    studio_query = select(Studio).where(
        Studio.admin_name == user.name,
        Studio.status == "active",
    )
    studio_result = await db.execute(studio_query)
    studio = studio_result.scalar_one_or_none()

    # 지사(Branch) 정보 조회
    branch = None
    if user.branch_id:
        branch_result = await db.execute(select(Branch).where(Branch.id == user.branch_id))
        branch = branch_result.scalar_one_or_none()

    return ApiResponse(data={
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone or "",
        "registration_code": user.registration_code,
        "branch_id": user.branch_id,
        "branch_name": branch.name if branch else "",
        "studio_name": studio.name if studio else "",
        "studio_id": studio.id if studio else None,
    })


@router.post("/directors/register-by-code")
async def register_director_by_code(
    data: dict,
    current_user: dict = Depends(require_role("branch_manager", "branch_admin", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """원장 코드로 조회 → 현재 지사에 등록 (branch_id 설정)"""
    code = (data.get("code") or data.get("registration_code") or "").strip()
    user_id = data.get("user_id") or data.get("director_id")

    query = select(User).where(User.role == "director", User.is_active == True)
    if user_id:
        query = query.where(User.id == user_id)
    elif code:
        query = query.where(User.registration_code == code)
    else:
        raise HTTPException(status_code=400, detail="코드 또는 사용자 ID가 필요합니다.")

    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="해당 원장을 찾을 수 없습니다.")

    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    user.branch_id = branch_id
    await db.commit()

    return ApiResponse(message=f"{user.name} 원장이 등록되었습니다.", data={
        "id": user.id, "name": user.name, "branch_id": user.branch_id
    })


# ============================================================
# 원장 보고서 조회 (해당 지사 소속 원장들의 보고서)
# ============================================================
@router.get("/director-reports")
async def get_branch_director_reports(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사에서 소속 원장들의 보고서 조회"""
    # branch_admin은 자신의 지사 보고서만, super_admin은 전체
    if current_user["role"] in ("super_admin", "admin"):
        query = select(DirectorReport)
    else:
        query = select(DirectorReport).where(DirectorReport.branch_id == current_user["branch_id"])
    
    if year:
        query = query.where(DirectorReport.year == year)
    if month:
        query = query.where(DirectorReport.month == month)
    
    # 전체 카운트
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    
    query = query.order_by(DirectorReport.created_at.desc()).offset((page-1)*per_page).limit(per_page)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    # 원장 이름 매핑
    director_ids = list(set(r.director_id for r in reports if r.director_id))
    if director_ids:
        users_result = await db.execute(select(User.id, User.name).where(User.id.in_(director_ids)))
        user_map = {u.id: u.name for u in users_result.all()}
    else:
        user_map = {}
    
    return PaginatedResponse(
        data=[{
            "id": r.id, "director_id": r.director_id, "branch_id": r.branch_id,
            "status": r.status, "year": r.year, "month": r.month,
            "branch_name": r.branch_name,
            "director_name": r.director_name or user_map.get(r.director_id, ""),
            "contact": r.contact,
            "total_students": r.total_students,
            "new_registrations": r.new_registrations,
            "withdrawals": r.withdrawals,
            "retention_rate": r.retention_rate,
            "target_new_students": r.target_new_students,
            "target_monthly_revenue": r.target_monthly_revenue,
            "notes": r.notes or "",
            "confirmed_date": r.confirmed_date or "",
            "is_agreed": r.is_agreed,
            "created_at": str(r.created_at) if r.created_at else None,
        } for r in reports],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/director-reports/{report_id}")
async def get_branch_director_report_detail(
    report_id: int,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사에서 원장 보고서 상세 조회"""
    query = select(DirectorReport).where(DirectorReport.id == report_id)
    if current_user["role"] not in ("super_admin", "admin"):
        query = query.where(DirectorReport.branch_id == current_user["branch_id"])
    
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    
    return ApiResponse(data={
        "id": r.id, "director_id": r.director_id, "branch_id": r.branch_id,
        "status": r.status, "year": r.year, "month": r.month,
        "branch_name": r.branch_name, "director_name": r.director_name,
        "contact": r.contact,
        "total_students": r.total_students,
        "new_registrations": r.new_registrations,
        "withdrawals": r.withdrawals,
        "retention_rate": r.retention_rate,
        "target_new_students": r.target_new_students,
        "target_monthly_revenue": r.target_monthly_revenue,
        "target_other": r.target_other or "",
        "issue_facility_content": r.issue_facility_content or "",
        "issue_facility_request": r.issue_facility_request or "",
        "issue_education_content": r.issue_education_content or "",
        "issue_education_request": r.issue_education_request or "",
        "issue_admin_content": r.issue_admin_content or "",
        "issue_admin_request": r.issue_admin_request or "",
        "issue_other_content": r.issue_other_content or "",
        "issue_other_request": r.issue_other_request or "",
        "result_new_students": r.result_new_students,
        "result_new_students_rate": r.result_new_students_rate,
        "result_monthly_revenue": r.result_monthly_revenue,
        "result_monthly_revenue_rate": r.result_monthly_revenue_rate,
        "result_retention_rate": r.result_retention_rate,
        "result_retention_rate_achieved": r.result_retention_rate_achieved,
        "notes": r.notes or "",
        "confirmed_date": r.confirmed_date or "",
        "is_agreed": r.is_agreed,
        "created_at": str(r.created_at) if r.created_at else None,
        "updated_at": str(r.updated_at) if r.updated_at else None,
    })


@router.put("/director-reports/{report_id}/confirm")
async def confirm_director_report(
    report_id: int,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사에서 원장 보고서 확인 (상태를 confirmed_by_branch로 변경)"""
    query = select(DirectorReport).where(DirectorReport.id == report_id)
    if current_user["role"] not in ("super_admin", "admin"):
        query = query.where(DirectorReport.branch_id == current_user["branch_id"])
    
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    
    if r.status != "submitted":
        raise HTTPException(status_code=400, detail="제출된(submitted) 보고서만 확인할 수 있습니다.")
    
    r.status = "confirmed_by_branch"
    await db.commit()
    await db.refresh(r)
    return ApiResponse(message="보고서가 확인되었습니다.", data={"id": r.id, "status": r.status})


# ============================================================
# 지사 보고서 관리 (지사 → 본사 제출)
# ============================================================
@router.get("/reports")
async def get_branch_reports(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사 보고서 목록 조회"""
    if current_user["role"] in ("super_admin", "admin"):
        query = select(BranchReport)
    else:
        query = select(BranchReport).where(BranchReport.branch_id == current_user["branch_id"])
    
    if year:
        query = query.where(BranchReport.year == year)
    if month:
        query = query.where(BranchReport.month == month)
    if status:
        query = query.where(BranchReport.status == status)
    
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0
    
    query = query.order_by(BranchReport.created_at.desc()).offset((page-1)*per_page).limit(per_page)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return PaginatedResponse(
        data=[{
            "id": r.id, "branch_id": r.branch_id, "status": r.status,
            "year": r.year, "month": r.month,
            "branch_name": r.branch_name,
            "manager_name": r.manager_name or "",
            "contact": r.contact,
            "total_students": r.total_students,
            "new_registrations": r.new_registrations,
            "withdrawals": r.withdrawals,
            "retention_rate": r.retention_rate,
            "notes": r.notes or "",
            "is_agreed": r.is_agreed,
            "created_at": str(r.created_at) if r.created_at else None,
        } for r in reports],
        total=total, page=page, per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


@router.get("/reports/{report_id}")
async def get_branch_report_detail(
    report_id: int,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사 보고서 상세 조회"""
    query = select(BranchReport).where(BranchReport.id == report_id)
    if current_user["role"] not in ("super_admin", "admin"):
        query = query.where(BranchReport.branch_id == current_user["branch_id"])
    
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    
    return ApiResponse(data={
        "id": r.id, "branch_id": r.branch_id, "status": r.status,
        "year": r.year, "month": r.month,
        "branch_name": r.branch_name, "manager_name": r.manager_name or "",
        "contact": r.contact,
        "total_students": r.total_students,
        "new_registrations": r.new_registrations,
        "withdrawals": r.withdrawals,
        "retention_rate": r.retention_rate,
        "target_new_students": r.target_new_students,
        "target_monthly_revenue": r.target_monthly_revenue,
        "target_other": r.target_other or "",
        "issue_facility_content": r.issue_facility_content or "",
        "issue_facility_request": r.issue_facility_request or "",
        "issue_education_content": r.issue_education_content or "",
        "issue_education_request": r.issue_education_request or "",
        "issue_admin_content": r.issue_admin_content or "",
        "issue_admin_request": r.issue_admin_request or "",
        "issue_other_content": r.issue_other_content or "",
        "issue_other_request": r.issue_other_request or "",
        "result_new_students": r.result_new_students,
        "result_new_students_rate": r.result_new_students_rate,
        "result_monthly_revenue": r.result_monthly_revenue,
        "result_monthly_revenue_rate": r.result_monthly_revenue_rate,
        "result_retention_rate": r.result_retention_rate,
        "result_retention_rate_achieved": r.result_retention_rate_achieved,
        "notes": r.notes or "",
        "confirmed_date": r.confirmed_date or "",
        "is_agreed": r.is_agreed,
        "director_report_received": r.director_report_received,
        "created_at": str(r.created_at) if r.created_at else None,
        "updated_at": str(r.updated_at) if r.updated_at else None,
    })


# ============================================================
# 보고서 % 자동 계산 (서버측 보정) — 에듀케어 보고서
# ============================================================
def _breport_pct(numer, denom) -> int:
    try:
        numer = float(numer or 0)
        denom = float(denom or 0)
    except (TypeError, ValueError):
        return 0
    if denom <= 0:
        return 0
    return round((numer / denom) * 100)


def _normalize_breport_rates(d: dict) -> dict:
    total = d.get("total_students") or 0
    withdrawals = d.get("withdrawals") or 0
    retention = _breport_pct(total - withdrawals, total)
    d["retention_rate"] = retention

    d["result_new_students_rate"] = _breport_pct(
        d.get("result_new_students"), d.get("target_new_students"))
    d["result_monthly_revenue_rate"] = _breport_pct(
        d.get("result_monthly_revenue"), d.get("target_monthly_revenue"))

    prev_total = d.get("prev_total_students") or total
    result_retention = _breport_pct(prev_total - withdrawals, prev_total)
    d["result_retention_rate"] = result_retention
    d["result_retention_rate_achieved"] = _breport_pct(result_retention, retention)
    return d


@router.post("/reports")
async def create_branch_report(
    data: BranchReportCreate,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사 보고서 작성"""
    # branch_id 자동 설정
    branch_id = current_user.get("branch_id")
    if not branch_id:
        if current_user["role"] in ("super_admin", "admin"):
            if not data.branch_id:
                raise HTTPException(status_code=400, detail="지사 ID(branch_id)가 필요합니다.")
            branch_id = data.branch_id
        else:
            raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # %·달성률 서버측 자동 재계산
    _nd = data.model_dump() if hasattr(data, "model_dump") else dict(data)
    _nd = _normalize_breport_rates(_nd)

    report = BranchReport(
        branch_id=branch_id,
        director_report_id=data.director_report_id,
        status=data.status or "draft",
        year=data.year,
        month=data.month,
        branch_name=data.branch_name or "",
        manager_name=data.manager_name or "",
        contact=data.contact or "",
        total_students=_nd.get("total_students") or 0,
        new_registrations=_nd.get("new_registrations") or 0,
        withdrawals=_nd.get("withdrawals") or 0,
        retention_rate=_nd.get("retention_rate") or 0,
        target_new_students=data.target_new_students or 0,
        target_monthly_revenue=data.target_monthly_revenue or 0,
        target_other=data.target_other or "",
        issue_facility_content=data.issue_facility_content or "",
        issue_facility_request=data.issue_facility_request or "",
        issue_education_content=data.issue_education_content or "",
        issue_education_request=data.issue_education_request or "",
        issue_admin_content=data.issue_admin_content or "",
        issue_admin_request=data.issue_admin_request or "",
        issue_other_content=data.issue_other_content or "",
        issue_other_request=data.issue_other_request or "",
        result_new_students=_nd.get("result_new_students") or 0,
        result_new_students_rate=_nd.get("result_new_students_rate") or 0,
        result_monthly_revenue=_nd.get("result_monthly_revenue") or 0,
        result_monthly_revenue_rate=_nd.get("result_monthly_revenue_rate") or 0,
        result_retention_rate=_nd.get("result_retention_rate") or 0,
        result_retention_rate_achieved=_nd.get("result_retention_rate_achieved") or 0,
        notes=data.notes or "",
        confirmed_date=data.confirmed_date or "",
        is_agreed=data.is_agreed or False,
        director_report_received=data.director_report_received or False,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return ApiResponse(message="보고서가 저장되었습니다.", data={"id": report.id, "status": report.status})


@router.put("/reports/{report_id}")
async def update_branch_report(
    report_id: int,
    data: BranchReportCreate,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """지사 보고서 수정"""
    query = select(BranchReport).where(BranchReport.id == report_id)
    if current_user["role"] not in ("super_admin", "admin"):
        query = query.where(BranchReport.branch_id == current_user["branch_id"])
    
    result = await db.execute(query)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    
    # %·달성률 서버측 자동 재계산
    _ud = data.model_dump() if hasattr(data, "model_dump") else dict(data)
    _ud = _normalize_breport_rates(_ud)

    for field in [
        "status", "year", "month", "branch_name", "manager_name", "contact",
        "total_students", "new_registrations", "withdrawals", "retention_rate",
        "target_new_students", "target_monthly_revenue", "target_other",
        "issue_facility_content", "issue_facility_request",
        "issue_education_content", "issue_education_request",
        "issue_admin_content", "issue_admin_request",
        "issue_other_content", "issue_other_request",
        "result_new_students", "result_new_students_rate",
        "result_monthly_revenue", "result_monthly_revenue_rate",
        "result_retention_rate", "result_retention_rate_achieved",
        "notes", "confirmed_date", "is_agreed",
        "director_report_received",
    ]:
        val = _ud.get(field, getattr(data, field, None))
        if val is not None:
            setattr(r, field, val)
    
    await db.commit()
    await db.refresh(r)
    return ApiResponse(message="보고서가 수정되었습니다.", data={"id": r.id, "status": r.status})


# ============================================================
# 프로그램 조회 (assignments 기반, 읽기 전용)
# ============================================================


@router.get("/programs")
async def get_branch_programs(
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "director")),
    db: AsyncSession = Depends(get_db),
):
    """현 지사에 할당된 교육 프로그램 목록"""
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # Get program IDs via ProgramAssignment
    assign_result = await db.execute(
        select(ProgramAssignment).where(
            ProgramAssignment.assignee_type == "branch",
            ProgramAssignment.assignee_id == branch_id,
        )
    )
    assignments = assign_result.scalars().all()
    program_ids = [a.program_id for a in assignments]

    if not program_ids:
        return ApiResponse(data=[])

    prog_result = await db.execute(
        select(EducationProgram).where(EducationProgram.id.in_(program_ids))
    )
    programs = prog_result.scalars().all()

    return ApiResponse(data=[{
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "subject": p.subject,
        "instructor": p.instructor or "",
        "created_at": str(p.created_at) if p.created_at else None,
    } for p in programs])


@router.get("/programs/{program_id}/chapters")
async def get_branch_program_chapters(
    program_id: int,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "director")),
    db: AsyncSession = Depends(get_db),
):
    """특정 프로그램의 챕터 목록 (지사 할당 확인)"""
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")

    # Verify assignment
    assign_result = await db.execute(
        select(ProgramAssignment).where(
            ProgramAssignment.assignee_type == "branch",
            ProgramAssignment.assignee_id == branch_id,
            ProgramAssignment.program_id == program_id,
        )
    )
    if not assign_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="이 프로그램에 접근 권한이 없습니다.")

    chapters_result = await db.execute(
        select(ProgramChapter)
        .where(ProgramChapter.program_id == program_id)
        .order_by(ProgramChapter.sort_order, ProgramChapter.id)
    )
    chapters = chapters_result.scalars().all()

    return ApiResponse(data=[{
        "id": ch.id,
        "title": ch.title,
        "description": ch.description,
        "sort_order": ch.sort_order,
        "is_active": ch.is_active,
        "created_at": str(ch.created_at) if ch.created_at else None,
    } for ch in chapters])


# ============================================================
# 에듀케어 설정 — 자신의 branch 정보 조회/수정
# ============================================================

@router.get("/settings")
async def get_branch_settings(
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "director", "student", "parent", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """에듀케어 계정이 자신의 branch 정보를 조회"""
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    # 수익률 + 입금 계좌 조회 (BranchSetting.payment_config)
    #   ★ 정산 설정(로열티율/순수익률/순수익 공제율)은 본사(지사 관리)가 주관한다.
    #     여기서는 읽기 전용으로 노출 (에듀케어 매출관리 화면 표시용).
    #   bank_name / account_number / account_holder : 로열티 입금 계좌 (에듀케어가 직접 입력)
    hq_royalty_rate = 45.0
    profit_rate = 7.0
    income_tax_rate = 3.3
    bank_name = ""
    account_number = ""
    account_holder = ""
    try:
        bs_result = await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == branch_id)
        )
        bs = bs_result.scalar_one_or_none()
        if bs and bs.payment_config:
            cfg = bs.payment_config
            if cfg.get("hq_royalty_rate") is not None:
                hq_royalty_rate = float(cfg["hq_royalty_rate"])
            if cfg.get("profit_rate") is not None:
                profit_rate = float(cfg["profit_rate"])
            if cfg.get("income_tax_rate") is not None:
                income_tax_rate = float(cfg["income_tax_rate"])
            bank_name = cfg.get("bank_name", "") or ""
            account_number = cfg.get("account_number", "") or ""
            account_holder = cfg.get("account_holder", "") or ""
    except Exception:
        pass

    return ApiResponse(data={
        "id": branch.id,
        "name": branch.name,
        "phone": branch.phone,
        "address": branch.address,
        "status": branch.status,
        "is_approved": branch.is_approved,
        "code": branch.code,
        "email": branch.email,
        "created_at": str(branch.created_at) if branch.created_at else None,
        "profit_rate": profit_rate,
        "hq_royalty_rate": hq_royalty_rate,
        "income_tax_rate": income_tax_rate,
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
        # 정산 설정은 본사가 주관 — 에듀케어는 수정 불가 (프론트에서도 잠금 표시)
        "settlement_locked": True,
    })


@router.put("/settings")
async def update_branch_settings(
    data: dict,
    current_user: dict = Depends(require_role("branch_admin", "branch_manager", "director", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """에듀케어 계정이 자신의 branch 정보 수정"""
    branch_id = current_user.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="지사 정보가 없습니다.")
    branch = await db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="지사를 찾을 수 없습니다.")

    updatable_fields = ("name", "phone", "address")
    for key in updatable_fields:
        if key in data:
            setattr(branch, key, data[key])

    # 입금 계좌만 에듀케어가 직접 저장 가능 — BranchSetting.payment_config
    #   ★ 정산 설정(profit_rate / hq_royalty_rate / income_tax_rate)은 본사(지사 관리)가 주관하므로
    #     에듀케어 PUT에서는 저장을 차단한다 (요청에 포함돼도 무시).
    config_keys = ("bank_name", "account_number", "account_holder")
    blocked_settlement_keys = ("profit_rate", "hq_royalty_rate", "income_tax_rate")
    if any(k in data for k in blocked_settlement_keys):
        # 저장은 하지 않되 조용히 무시하지 않고 명시적으로 알린다
        raise HTTPException(
            status_code=403,
            detail="정산 설정(로열티율/순수익률/순수익 공제율)은 본사에서 관리합니다.",
        )
    if any(k in data for k in config_keys):
        bs_result = await db.execute(
            select(BranchSetting).where(BranchSetting.branch_id == branch_id)
        )
        bs = bs_result.scalar_one_or_none()
        if not bs:
            bs = BranchSetting(branch_id=branch_id, payment_config={})
            db.add(bs)
        config = dict(bs.payment_config or {})

        for str_key in ("bank_name", "account_number", "account_holder"):
            if str_key in data:
                config[str_key] = str(data[str_key] or "").strip()

        bs.payment_config = config

    await db.commit()
    await db.refresh(branch)
    return ApiResponse(message="에듀케어 설정이 저장되었습니다.", data={
        "id": branch.id,
        "name": branch.name,
    })
