"""
📊 엑셀 다운로드 API — openpyxl + FastAPI FileResponse
"""
import io
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models import User, Payment, Branch, Course, Enrollment, DirectorReport, BranchReport
from app.schemas import ApiResponse

router = APIRouter(prefix="/excel", tags=["엑셀 다운로드"])


# ============================================================
# 스타일 헬퍼
# ============================================================

HEADER_FILL = PatternFill(start_color="0891B2", end_color="0891B2", fill_type="solid")
HEADER_FONT = Font(name="Noto Sans KR", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Noto Sans KR", size=10)
THIN_BORDER = Border(
    left=Side(style='thin', color='E0E0E0'),
    right=Side(style='thin', color='E0E0E0'),
    top=Side(style='thin', color='E0E0E0'),
    bottom=Side(style='thin', color='E0E0E0'),
)


def _style_header(ws, row=1, cols=1):
    """헤더 행 스타일 적용"""
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER


def _style_body(ws, start_row, end_row, cols):
    """본문 스타일 적용"""
    for r in range(start_row, end_row + 1):
        for c in range(1, cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = BODY_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical='center')


def _auto_width(ws, cols):
    """열 너비 자동 조정"""
    for col in range(1, cols + 1):
        max_len = 0
        for row in ws.iter_rows(min_col=col, max_col=col, values_only=False):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = min(max_len + 4, 40)


def _response(wb, filename):
    """StreamingResponse 생성 (한글 파일명 지원)"""
    from urllib.parse import quote
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    encoded_filename = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        }
    )


# ============================================================
# 1. 사용자 목록 엑셀
# ============================================================

@router.get("/users")
async def export_users(
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """사용자 목록 엑셀 다운로드"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "사용자 목록"

    headers = ["ID", "이름", "아이디", "이메일", "역할", "휴대폰", "활성", "가입일"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    role_labels = {
        "super_admin": "최고관리자", "admin": "관리자",
        "branch_admin": "지사관리자", "branch_manager": "지사관리자",
        "director": "원장", "teacher": "강사",
        "student": "학생", "parent": "학부모",
    }

    for u in users:
        ws.append([
            u.id, u.name, u.username, u.email or "",
            role_labels.get(u.role, u.role),
            u.phone or "",
            "✅" if u.is_active else "❌",
            str(u.created_at)[:10] if u.created_at else "",
        ])

    _style_body(ws, 2, len(users) + 1, len(headers))
    _auto_width(ws, len(headers))

    return _response(wb, f"사용자목록_{datetime.now().strftime('%Y%m%d')}.xlsx")


# ============================================================
# 2. 결제 내역 엑셀
# ============================================================

@router.get("/payments")
async def export_payments(
    current_user: dict = Depends(require_role("super_admin", "admin", "branch_admin", "branch_manager")),
    db: AsyncSession = Depends(get_db),
    branch_id: int = Query(None),
):
    """결제 내역 엑셀 다운로드"""
    query = select(Payment).order_by(Payment.created_at.desc())
    if branch_id:
        query = query.where(Payment.branch_id == branch_id)
    result = await db.execute(query)
    payments = result.scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "결제 내역"

    headers = ["ID", "학생ID", "강좌ID", "지사ID", "금액", "결제방식", "상태", "결제일", "등록일"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    status_labels = {"completed": "완료", "pending": "대기", "failed": "실패", "refunded": "환불"}
    method_labels = {"card": "카드", "transfer": "계좌이체", "cash": "현금", "kakao": "카카오페이"}

    for p in payments:
        ws.append([
            p.id, p.student_id, p.course_id or "", p.branch_id or "",
            float(p.amount) if p.amount else 0,
            method_labels.get(p.method, p.method or ""),
            status_labels.get(p.status, p.status or ""),
            str(p.paid_at)[:10] if p.paid_at else "",
            str(p.created_at)[:10] if p.created_at else "",
        ])

    _style_body(ws, 2, len(payments) + 1, len(headers))
    _auto_width(ws, len(headers))

    return _response(wb, f"결제내역_{datetime.now().strftime('%Y%m%d')}.xlsx")


# ============================================================
# 3. 통계 데이터 엑셀
# ============================================================

@router.get("/statistics")
async def export_statistics(
    current_user: dict = Depends(require_role("super_admin", "admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
):
    """통계 데이터 엑셀 다운로드"""
    wb = openpyxl.Workbook()

    # --- Sheet 1: 사용자 통계 ---
    ws1 = wb.active
    ws1.title = "사용자 통계"

    result = await db.execute(
        select(User.role, func.count(User.id)).where(User.is_active == True).group_by(User.role)
    )
    role_stats = result.all()

    headers1 = ["역할", "활성 사용자 수"]
    ws1.append(headers1)
    _style_header(ws1, 1, len(headers1))

    total = 0
    for role, count in role_stats:
        role_label = {
            "super_admin": "최고관리자", "admin": "관리자",
            "branch_admin": "지사관리자", "branch_manager": "지사관리자",
            "director": "원장", "teacher": "강사",
            "student": "학생", "parent": "학부모",
        }.get(role, role)
        ws1.append([role_label, count])
        total += count
    ws1.append(["합계", total])

    _style_body(ws1, 2, len(role_stats) + 1, len(headers1))
    _auto_width(ws1, len(headers1))

    # --- Sheet 2: 강좌 통계 ---
    ws2 = wb.create_sheet("강좌 통계")

    result2 = await db.execute(
        select(Course.status, func.count(Course.id)).group_by(Course.status)
    )
    course_stats = result2.all()

    headers2 = ["상태", "강좌 수"]
    ws2.append(headers2)
    _style_header(ws2, 1, len(headers2))

    total2 = 0
    status_labels = {"active": "공개", "draft": "비공개", "inactive": "중지"}
    for status, count in course_stats:
        ws2.append([status_labels.get(status, status), count])
        total2 += count
    ws2.append(["합계", total2])

    _style_body(ws2, 2, len(course_stats) + 1, len(headers2))
    _auto_width(ws2, len(headers2))

    # --- Sheet 3: 결제 통계 ---
    ws3 = wb.create_sheet("결제 통계")

    result3 = await db.execute(
        select(Payment.status, func.count(Payment.id), func.sum(Payment.amount))
        .group_by(Payment.status)
    )
    payment_stats = result3.all()

    headers3 = ["상태", "건수", "금액 합계"]
    ws3.append(headers3)
    _style_header(ws3, 1, len(headers3))

    total_count = 0
    total_amount = 0
    pstatus_labels = {"completed": "완료", "pending": "대기", "failed": "실패", "refunded": "환불"}
    for status, count, amount in payment_stats:
        amt = float(amount) if amount else 0
        ws3.append([pstatus_labels.get(status, status), count, amt])
        total_count += count
        total_amount += amt
    ws3.append(["합계", total_count, total_amount])

    _style_body(ws3, 2, len(payment_stats) + 1, len(headers3))
    _auto_width(ws3, len(headers3))

    return _response(wb, f"통계데이터_{datetime.now().strftime('%Y%m%d')}.xlsx")


# ============================================================
# 4. 보고서 엑셀 (원장/지사)
# ============================================================

@router.get("/reports")
async def export_reports(
    current_user: dict = Depends(require_role("super_admin", "admin", "branch_admin")),
    db: AsyncSession = Depends(get_db),
    year: int = Query(None),
    month: int = Query(None),
):
    """원장/지사 보고서 엑셀 다운로드"""
    wb = openpyxl.Workbook()

    # --- Sheet 1: 원장 보고서 ---
    ws1 = wb.active
    ws1.title = "원장 보고서"

    query = select(DirectorReport).order_by(DirectorReport.year.desc(), DirectorReport.month.desc())
    if year:
        query = query.where(DirectorReport.year == year)
    if month:
        query = query.where(DirectorReport.month == month)
    result = await db.execute(query)
    reports = result.scalars().all()

    headers1 = ["ID", "원장명", "지사명", "년", "월", "총수강생", "신규", "탈퇴", "유지율%", "매출목표", "매출실적", "상태"]
    ws1.append(headers1)
    _style_header(ws1, 1, len(headers1))

    for r in reports:
        ws1.append([
            r.id, r.director_name, r.branch_name,
            r.year, r.month,
            r.total_students or 0, r.new_registrations or 0, r.withdrawals or 0,
            r.retention_rate or 0,
            r.target_monthly_revenue or 0,
            r.result_monthly_revenue or 0,
            "제출" if r.status == "submitted" else "임시",
        ])

    _style_body(ws1, 2, len(reports) + 1, len(headers1))
    _auto_width(ws1, len(headers1))

    return _response(wb, f"보고서_{datetime.now().strftime('%Y%m%d')}.xlsx")
