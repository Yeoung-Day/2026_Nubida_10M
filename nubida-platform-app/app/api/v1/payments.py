"""
💳 간편 결제 고도화 — Payment API
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, desc
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.event_bus import event_bus
from app.models import Payment, User, Course, Enrollment, Notification, MembershipLink, AppSetting
from app.schemas import PaymentCreate, ApiResponse, PaginatedResponse

router = APIRouter(prefix="/payments", tags=["결제"])

# 지원 결제 수단 메타 정보
PAYMENT_METHODS = [
    {
        "id": "card",
        "name": "카드 결제",
        "icon": "credit-card",
        "description": "신용/체크카드로 간편하게 결제",
    },
    {
        "id": "kakao",
        "name": "카카오페이",
        "icon": "kakao",
        "description": "카카오페이로 빠르고 안전하게 결제",
    },
    {
        "id": "toss",
        "name": "토스페이",
        "icon": "toss",
        "description": "토스 간편 결제",
    },
    {
        "id": "naver",
        "name": "네이버페이",
        "icon": "naver",
        "description": "네이버페이로 간편하게 결제",
    },
    {
        "id": "virtual_account",
        "name": "가상계좌",
        "icon": "bank",
        "description": "가상계좌로 입금 후 자동 확인",
    },
    {
        "id": "transfer",
        "name": "계좌이체",
        "icon": "exchange-alt",
        "description": "실시간 계좌이체",
    },
]


def _generate_receipt_number() -> str:
    """고유 영수증 번호 생성"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:8].upper()
    return f"RCP-{today}-{unique}"


# ============================================================
# 1. 결제 처리 (Mock)
# ============================================================


@router.post("/process")
async def process_payment(
    body: PaymentCreate,
    current_user: dict = Depends(require_role("parent", "student", "admin", "director")),
    db: AsyncSession = Depends(get_db),
):
    """Mock 결제 처리 — Payment 레코드를 생성하고 영수증 정보를 반환합니다."""
    # 유효한 결제 수단 검증
    valid_methods = {m["id"] for m in PAYMENT_METHODS}
    if body.method not in valid_methods:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 결제 수단입니다. 지원: {', '.join(sorted(valid_methods))}",
        )

    # 학생 존재 확인
    student = await db.get(User, body.student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")

    now = datetime.now(timezone.utc)
    receipt_number = _generate_receipt_number()

    # Determine parent_id: if current user is a parent and no parent_id provided, use current user
    parent_id = body.parent_id
    if current_user["role"] == "parent" and not parent_id:
        parent_id = current_user["id"]

    payment = Payment(
        student_id=body.student_id,
        course_id=body.course_id,
        branch_id=body.branch_id,
        parent_id=parent_id,
        amount=body.amount,
        method=body.method,
        status="completed",
        paid_at=now,
        receipt_number=receipt_number,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # Update enrollment payment_status to 'paid'
    enrollment_result = await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == body.student_id,
            Enrollment.course_id == body.course_id,
        )
    )
    enrollment = enrollment_result.scalar_one_or_none()
    if enrollment:
        enrollment.payment_status = "paid"
        await db.commit()

    return ApiResponse(
        status="success",
        message="결제가 완료되었습니다.",
        data={
            "payment_id": payment.id,
            "student_id": payment.student_id,
            "course_id": payment.course_id,
            "branch_id": payment.branch_id,
            "parent_id": payment.parent_id,
            "amount": float(payment.amount),
            "method": payment.method,
            "status": payment.status,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            "receipt_number": payment.receipt_number,
            "receipt_url": f"/api/v1/payments/receipt/{payment.id}",
        },
    )


# ============================================================
# 2. 가상계좌 발급 (Mock)
# ============================================================


@router.post("/virtual-account")
async def issue_virtual_account(
    current_user: dict = Depends(require_role("parent", "student")),
):
    """Mock 가상계좌 발급 — 실제 DB 변경 없이 계좌 정보만 반환합니다."""
    return ApiResponse(
        status="success",
        message="가상계좌가 발급되었습니다.",
        data={
            "bank_name": "하나은행",
            "account_number": "123-456789-01-123",
            "depositor": "(주)누비다교육",
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "notice": "입금 후 자동으로 결제 확인됩니다.",
        },
    )


# ============================================================
# 3. 영수증 조회
# ============================================================


@router.get("/receipt/{payment_id}")
async def get_receipt(
    payment_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """완료된 결제의 상세 영수증 정보를 반환합니다."""
    payment = await db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="결제 내역을 찾을 수 없습니다.")

    # 학생 정보
    student = await db.get(User, payment.student_id)
    # 학부모 정보
    parent = await db.get(User, payment.parent_id) if payment.parent_id else None

    return ApiResponse(
        status="success",
        data={
            "receipt_number": payment.receipt_number,
            "payment_id": payment.id,
            "student": {
                "id": student.id if student else None,
                "name": student.name if student else "알 수 없음",
            },
            "parent": {
                "id": parent.id if parent else None,
                "name": parent.name if parent else None,
            } if parent else None,
            "course_id": payment.course_id,
            "branch_id": payment.branch_id,
            "amount": float(payment.amount),
            "method": payment.method,
            "status": payment.status,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# ============================================================
# 4. 결제 목록 조회 (관리자/HQ/학부모)
# ============================================================


@router.get("")
async def list_payments(
    status: str = None,
    method: str = None,
    search: str = None,
    student_id: int = None,
    parent_id: int = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """결제 목록을 조회합니다. 관리자/HQ/학부모 전용."""
    query = select(Payment)

    # Role-based filtering
    if current_user["role"] == "parent":
        # Parents see payments linked to their children or their own parent_id
        child_ids_result = await db.execute(
            select(MembershipLink.child_id).where(
                MembershipLink.parent_id == current_user["id"],
                MembershipLink.relationship == "parent_child",
                MembershipLink.status == "active",
            )
        )
        child_ids = [row[0] for row in child_ids_result.all()]
        query = query.where(
            or_(
                Payment.parent_id == current_user["id"],
                Payment.student_id.in_(child_ids) if child_ids else False,
            )
        )

    if status:
        query = query.where(Payment.status == status)
    if method:
        query = query.where(Payment.method == method)
    if student_id:
        query = query.where(Payment.student_id == student_id)
    if parent_id:
        query = query.where(Payment.parent_id == parent_id)
    if search:
        query = query.where(
            or_(
                Payment.receipt_number.ilike(f"%{search}%"),
                Payment.student_id.cast(str).ilike(f"%{search}%"),
            )
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(Payment.created_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    payments = result.scalars().all()

    # Fetch related user/course names
    items = []
    for p in payments:
        student = await db.get(User, p.student_id) if p.student_id else None
        parent = await db.get(User, p.parent_id) if p.parent_id else None
        items.append({
            "id": p.id,
            "student_id": p.student_id,
            "student_name": student.name if student else None,
            "parent_id": p.parent_id,
            "parent_name": parent.name if parent else None,
            "course_id": p.course_id,
            "branch_id": p.branch_id,
            "amount": float(p.amount),
            "method": p.method,
            "status": p.status,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "receipt_number": p.receipt_number,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return PaginatedResponse(data=items, total=total, page=page, per_page=per_page)


# ============================================================
# 5. 결제 수단 목록
# ============================================================


@router.get("/methods")
async def get_payment_methods():
    """사용 가능한 결제 수단 목록을 반환합니다."""
    return ApiResponse(
        status="success",
        data=PAYMENT_METHODS,
    )


# ============================================================
# 6. 학부모 전용: 자녀의 수강 강좌 + 결제 상태 조회
# ============================================================


@router.get("/parent-summary")
async def get_parent_payment_summary(
    current_user: dict = Depends(require_role("parent")),
    db: AsyncSession = Depends(get_db),
):
    """학부모가 자녀들의 수강 강좌와 결제 상태를 조회합니다."""
    parent_id = current_user["id"]

    # Get children linked to this parent via MembershipLink
    child_result = await db.execute(
        select(MembershipLink.child_id).where(
            MembershipLink.parent_id == parent_id,
            MembershipLink.relationship == "parent_child",
            MembershipLink.status == "active",
        )
    )
    child_ids = [row[0] for row in child_result.all()]

    # Fallback: if no membership links, try student_profiles or just all students
    if not child_ids:
        # Try finding students created by this parent or with matching info
        students_result = await db.execute(
            select(User).where(
                User.role == "student",
                User.is_active == True,
            ).limit(100)
        )
        child_ids = [s.id for s in students_result.scalars().all()]

    children_data = []
    for child_id in child_ids:
        child = await db.get(User, child_id)
        if not child:
            continue

        # Get child's enrollments with courses
        enrollments_result = await db.execute(
            select(Enrollment, Course)
            .join(Course, Course.id == Enrollment.course_id)
            .where(
                Enrollment.student_id == child_id,
                Enrollment.status == "active",
            )
        )
        enrollments = enrollments_result.all()

        courses = []
        for enrollment, course in enrollments:
            # Check if there's a completed payment for this enrollment
            payment_result = await db.execute(
                select(Payment).where(
                    Payment.student_id == child_id,
                    Payment.course_id == course.id,
                    Payment.status == "completed",
                ).order_by(Payment.paid_at.desc()).limit(1)
            )
            latest_payment = payment_result.scalar_one_or_none()

            courses.append({
                "enrollment_id": enrollment.id,
                "course_id": course.id,
                "course_name": course.name,
                "course_price": float(course.price) if course.price else 0,
                "branch_id": course.branch_id,
                "payment_status": enrollment.payment_status,
                "paid_at": latest_payment.paid_at.isoformat() if latest_payment and latest_payment.paid_at else None,
                "latest_payment_id": latest_payment.id if latest_payment else None,
            })

        children_data.append({
            "child_id": child_id,
            "child_name": child.name,
            "courses": courses,
        })

    return ApiResponse(data=children_data)


# ============================================================
# 본사 입금 계좌 — 대표자(super_admin) 전용 수정, 모든 사용자 조회
# ============================================================
HQ_ACCOUNT_DEFAULT = {"bank": "국민은행", "account": "123456-78-901234", "holder": "누비다플랫폼"}


@router.get("/hq-account")
async def get_hq_account(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """본사 입금 계좌 조회 — 로그인한 모든 사용자 (원장/지사/학생 포함)"""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "hq_account"))
    row = result.scalar_one_or_none()
    if row and row.value:
        data = row.value
    else:
        data = HQ_ACCOUNT_DEFAULT
    return ApiResponse(data=data)


@router.put("/hq-account")
async def update_hq_account(
    data: dict,
    current_user: dict = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """본사 입금 계좌 수정 — 대표자(super_admin) 전용"""
    bank = (data.get("bank") or "").strip()
    account = (data.get("account") or "").strip()
    holder = (data.get("holder") or "").strip()
    if not bank or not account or not holder:
        raise HTTPException(status_code=400, detail="은행/계좌번호/예금주를 모두 입력해주세요.")
    result = await db.execute(select(AppSetting).where(AppSetting.key == "hq_account"))
    row = result.scalar_one_or_none()
    if row:
        row.value = {"bank": bank, "account": account, "holder": holder}
    else:
        db.add(AppSetting(key="hq_account", value={"bank": bank, "account": account, "holder": holder}))
    await db.commit()
    return ApiResponse(
        data={"bank": bank, "account": account, "holder": holder},
        message="본사 입금 계좌가 수정되었습니다.",
    )
