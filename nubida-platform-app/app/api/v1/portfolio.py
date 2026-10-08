"""
📁 포트폴리오 관리 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json, random, string
from datetime import date as _date
from pathlib import Path

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.event_bus import event_bus
from app.models import Portfolio, Notification, Enrollment, ClassSchedule, Course, User
from app.schemas import ApiResponse, PaginatedResponse

router = APIRouter(prefix="/portfolio", tags=["포트폴리오"])


# ============================================================
# 포트폴리오 생성 (학생 전용)
# ============================================================

@router.post("")
async def create_portfolio(
    data: dict,
    current_user: dict = Depends(require_role("student", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    portfolio = Portfolio(
        student_id=current_user["id"],
        title=data.get("title"),
        description=data.get("description"),
        content=data.get("content"),
        content_url=data.get("content_url"),
        file_type=data.get("file_type"),
        thumbnail_url=data.get("thumbnail_url"),
        image_urls=json.dumps(data.get("image_urls", []), ensure_ascii=False) if data.get("image_urls") else "[]",
        subject=data.get("subject"),
        tags=data.get("tags"),
        is_public=data.get("is_public", True),
        course_id=data.get("course_id"),
        template_id=data.get("template_id"),
    )
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)

    # === SSE 알림 발행: 포트폴리오 제출 ===
    try:
        # Find teacher(s) linked to student's enrolled courses
        result = await db.execute(
            select(ClassSchedule.teacher_id)
            .join(Course, Course.id == ClassSchedule.course_id)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.student_id == current_user["id"])
            .distinct()
        )
        teacher_ids = [row[0] for row in result.all()]

        for teacher_id in teacher_ids:
            notif = Notification(
                user_id=teacher_id,
                title="포트폴리오 제출 알림",
                content=f"{current_user.get('username', '학생')}님이 포트폴리오를 제출했습니다: {portfolio.title}",
                notif_type="portfolio_submitted",
            )
            db.add(notif)
            await event_bus.publish(
                teacher_id,
                "portfolio_submitted",
                {
                    "portfolio_id": portfolio.id,
                    "student_id": portfolio.student_id,
                    "title": portfolio.title,
                    "subject": portfolio.subject,
                    "message": f"포트폴리오가 제출되었습니다: {portfolio.title}",
                }
            )
        if teacher_ids:
            await db.commit()
    except Exception:
        # Don't fail the request if notification fails
        pass

    return ApiResponse(message="포트폴리오가 생성되었습니다.", data={
        "id": portfolio.id,
        "student_id": portfolio.student_id,
        "title": portfolio.title,
        "status": portfolio.status,
    })


# ============================================================
# 포트폴리오 이미지 업로드
# ============================================================

@router.post("/upload")
async def upload_portfolio_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """포트폴리오 이미지 업로드"""
    # ====== StaticFiles 마운트 경로(UPLOADS_DIR/portfolio)와 일치시킴 ======
    PORTFOLIO_UPLOAD_DIR = Path("/app/uploads/portfolio")
    PORTFOLIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # 확장자 검증
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (jpg, png, gif, webp)")
    
    # 안전한 파일명 생성
    rand_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    safe_name = f"portfolio_{current_user['id']}_{rand_str}.{ext}"
    
    # 저장
    content = await file.read()
    file_path = PORTFOLIO_UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)
    
    file_url = f"/uploads/portfolio/{safe_name}"
    return ApiResponse(data={"url": file_url, "filename": safe_name})


# ============================================================
# 포트폴리오 목록 조회 (필터 지원)
# ============================================================

@router.get("")
async def get_portfolios(
    student_id: int = None,
    course_id: int = None,
    subject: str = None,
    status: str = None,
    branch_id: int = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    포트폴리오 목록 조회
    - 학생: 자신의 포트폴리오만 조회
    - 관리자(super_admin/admin): 전체 조회
    - 학부모: 자녀의 포트폴리오 조회 (현재는 전체 학생 대상, 추후 parent_id 연동)
    - 원장(director): 자신의 branch_id에 속한 학생 포트폴리오만 조회
    """
    query = select(Portfolio)

    role = current_user["role"]

    if role == "student":
        # 학생은 자신의 것만
        query = query.where(Portfolio.student_id == current_user["id"])
    elif role == "parent":
        # 학부모: 자녀(student)의 포트폴리오만
        query = query.where(Portfolio.status == "published")
    elif role == "director":
        # 원장: 자신에게 배정된(director_id) 학생의 포트폴리오만 조회
        bid = branch_id or current_user.get("branch_id", 0)
        if bid:
            student_ids_subq = select(User.id).where(
                User.role == "student",
                User.branch_id == bid,
                User.director_id == current_user["id"],
            )
            query = query.where(Portfolio.student_id.in_(student_ids_subq))
        else:
            query = query.where(Portfolio.id < 0)
    elif role in ("branch_admin", "branch_manager", "branch_staff"):
        # 에듀케어: 같은 branch의 모든 학생 포트폴리오 조회
        bid = branch_id or current_user.get("branch_id", 0)
        if bid:
            student_ids_subq = select(User.id).where(
                User.role == "student",
                User.branch_id == bid,
            )
            query = query.where(Portfolio.student_id.in_(student_ids_subq))
        else:
            query = query.where(Portfolio.id < 0)

    # 필터
    if student_id is not None:
        # director 계열: student_id 파라미터로 소속 필터 우회 금지
        if role == "director":
            bid = branch_id or current_user.get("branch_id", 0)
            if bid:
                query = query.where(
                    Portfolio.student_id == student_id,
                    Portfolio.student_id.in_(
                        select(User.id).where(
                            User.role == "student",
                            User.branch_id == bid,
                            User.director_id == current_user["id"],
                        )
                    ),
                )
            else:
                query = query.where(Portfolio.id < 0)
        elif role in ("branch_admin", "branch_manager", "branch_staff"):
            bid = branch_id or current_user.get("branch_id", 0)
            if bid:
                query = query.where(
                    Portfolio.student_id == student_id,
                    Portfolio.student_id.in_(
                        select(User.id).where(
                            User.role == "student",
                            User.branch_id == bid,
                        )
                    ),
                )
            else:
                query = query.where(Portfolio.id < 0)
        else:
            query = query.where(Portfolio.student_id == student_id)
    if course_id is not None:
        query = query.where(Portfolio.course_id == course_id)
    if subject is not None:
        query = query.where(Portfolio.subject == subject)
    if status is not None:
        query = query.where(Portfolio.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(Portfolio.updated_at.desc(), Portfolio.id).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    portfolios = result.scalars().all()

    # student_name + 수강 과정 카테고리 조회 (enrollments → courses.category)
    student_ids = list(set(p.student_id for p in portfolios))
    student_name_map = {}
    student_cat_map = {}      # {student_id: {"category": "ai_art", "category_name": "AI 아트(AI 사이언스 아트)", "course_name": "..."}}
    for sid in student_ids:
        r = await db.execute(select(User.name).where(User.id == sid))
        name = r.scalar_one_or_none()
        if name:
            student_name_map[sid] = name

    # ── 교육과정(category) 판별 : 3단계 우선순위 ──
    #  1) portfolio.course_id → courses.category   (신규 제출)
    #  2) portfolio.subject   → courses.name 매칭 → courses.category  (기존 자유텍스트)
    #  3) 학생의 활성 enrollment → courses.category  (최후 fallback)
    from sqlalchemy import text as _sql_text

    # (a) 과정 id → category 맵
    course_cat_map = {}      # {course_id: (category, name)}
    course_name_map = {}     # {name: (category, course_id)}
    try:
        for cid, cat, cname in (await db.execute(
            select(Course.id, Course.category, Course.name).where(Course.category.isnot(None))
        )).all():
            course_cat_map[cid] = (cat, cname)
            if cname:
                course_name_map[str(cname).strip()] = (cat, cid)
    except Exception:
        course_cat_map, course_name_map = {}, {}

    # (b) 학생 → 활성 enrollment 카테고리 (fallback)
    student_cat_map = {}
    if student_ids:
        PRIORITY = {"ai_robot": 0, "ai_art": 0}
        best = {}
        for sid, cat, cname, edate, eid in (await db.execute(
            select(Enrollment.student_id, Course.category, Course.name,
                   Enrollment.enrolled_date, Enrollment.id)
            .join(Course, Course.id == Enrollment.course_id)
            .where(
                Enrollment.student_id.in_(student_ids),
                Enrollment.status != "cancelled",
                Course.category.isnot(None),
            ).order_by(Enrollment.id)
        )).all():
            if sid is None or not cat:
                continue
            cand = (PRIORITY.get(str(cat), 5), edate or _date(1970, 1, 1), eid, cat, cname)
            cb = best.get(sid)
            if cb is None or (cand[0], cand[1]) < (cb[0], cb[1]):
                best[sid] = cand
        for sid, (_p, _d, _e, cat, cname) in best.items():
            student_cat_map[sid] = {"category": cat, "course_name": cname}

    # (c) 카테고리 표시명(categories 테이블)
    cat_name_map = {}
    try:
        for k, n in (await db.execute(_sql_text("SELECT `key` AS k, name AS n FROM categories"))).all():
            cat_name_map[k] = n
    except Exception:
        cat_name_map = {}

    def _keyword_category(text):
        """자유텍스트(subject 등)를 교육과정 카테고리 key로 매핑.
        ⚠️ 'Start'(St-art) 오탐 방지 위해 로봇 키워드를 먼저 검사한다."""
        s = str(text or "")
        import re as _re
        if _re.search(r"로봇|robot|코딩|피지컬|physical|start\s*kit|아두이노|arduino|키트|\bkit\b", s, _re.I):
            return "ai_robot"
        if _re.search(r"아트|사이언스|\bscience\b|디자인|드로잉|일러스트|그래픽|회화|미술|(?<![a-z])art(?![a-z])", s, _re.I):
            return "ai_art"
        if _re.search(r"해양|ocean", s, _re.I):
            return "Ocean University"
        return None

    def _resolve_category(p):
        """포트폴리오 1건의 교육과정(category, 표시명, 근거과정명) 결정"""
        # 1순위: course_id
        if p.course_id and p.course_id in course_cat_map:
            cat, cname = course_cat_map[p.course_id]
            return cat, cat_name_map.get(cat), cname
        # 2순위: subject ↔ courses.name 매칭 (정확 일치 → 포함 일치)
        subj = (p.subject or "").strip()
        if subj:
            if subj in course_name_map:
                cat, cid = course_name_map[subj]
                return cat, cat_name_map.get(cat), subj
            for nm, (cat, cid) in course_name_map.items():
                if nm and (nm in subj or subj in nm):
                    return cat, cat_name_map.get(cat), nm
            # 3순위: subject 키워드로 카테고리 직접 매핑 (courses에 없는 주차도 커버)
            _kw = _keyword_category(subj)
            if _kw:
                return _kw, cat_name_map.get(_kw), subj
        # 4순위: 학생 활성 enrollment
        sc = student_cat_map.get(p.student_id)
        if sc:
            cat = sc["category"]
            return cat, cat_name_map.get(cat), sc.get("course_name")
        return None, None, None

    _pf_cat = {p.id: _resolve_category(p) for p in portfolios}

    return PaginatedResponse(
        data=[{
            "id": p.id,
            "student_id": p.student_id,
            "student_name": student_name_map.get(p.student_id, "알 수 없음"),
            "title": p.title,
            "description": p.description,
            "content": p.content,
            "content_url": p.content_url,
            "file_type": p.file_type,
            "thumbnail_url": p.thumbnail_url,
            "image_urls": json.loads(p.image_urls) if p.image_urls else [],
            "subject": p.subject,
            "tags": p.tags,
            "is_public": p.is_public,
            "status": p.status,
            "course_id": p.course_id,
            "category": _pf_cat.get(p.id, (None, None, None))[0],
            "category_name": _pf_cat.get(p.id, (None, None, None))[1],
            "student_course_name": _pf_cat.get(p.id, (None, None, None))[2],
            "template_id": p.template_id,
            "created_at": str(p.created_at) if p.created_at else None,
            "updated_at": str(p.updated_at) if p.updated_at else None,
        } for p in portfolios],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1) // per_page,
    )


# ============================================================
# 포트폴리오 단건 조회
# ============================================================

@router.get("/{portfolio_id}")
async def get_portfolio(
    portfolio_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # ===== 접근 권한 검사 =====
    role = current_user["role"]
    user_id = current_user["id"]

    if role == "student":
        # 학생: 본인 것만
        if portfolio.student_id != user_id:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    elif role == "parent":
        # 학부모: published 상태만
        if portfolio.status != "published":
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    elif role == "director":
        # 원장: 자신에게 배정된(director_id) 학생의 포트폴리오만
        bid = current_user.get("branch_id", 0)
        if bid:
            student_check = await db.execute(
                select(User.id).where(
                    User.id == portfolio.student_id,
                    User.role == "student",
                    User.branch_id == bid,
                    User.director_id == current_user["id"],
                )
            )
            if not student_check.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        else:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    elif role in ("branch_admin", "branch_manager", "branch_staff"):
        # 에듀케어: 같은 branch의 모든 학생 포트폴리오 조회 가능
        bid = current_user.get("branch_id", 0)
        if bid:
            student_check = await db.execute(
                select(User.id).where(
                    User.id == portfolio.student_id,
                    User.role == "student",
                    User.branch_id == bid,
                )
            )
            if not student_check.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        else:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    elif role not in ("admin", "super_admin"):
        # 그 외 role은 접근 불가
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    # admin/super_admin: 모든 포트폴리오 접근 허용

    # 학생명 조회
    student_name = None
    if portfolio.student_id:
        r = await db.execute(select(User.name).where(User.id == portfolio.student_id))
        student_name = r.scalar_one_or_none()

    return ApiResponse(data={
        "id": portfolio.id,
        "student_id": portfolio.student_id,
        "student_name": student_name or "알 수 없음",
        "title": portfolio.title,
        "description": portfolio.description,
        "content": portfolio.content,
        "content_url": portfolio.content_url,
        "file_type": portfolio.file_type,
        "thumbnail_url": portfolio.thumbnail_url,
        "image_urls": json.loads(portfolio.image_urls) if portfolio.image_urls else [],
        "subject": portfolio.subject,
        "tags": portfolio.tags,
        "is_public": portfolio.is_public,
        "status": portfolio.status,
        "created_at": str(portfolio.created_at) if portfolio.created_at else None,
        "updated_at": str(portfolio.updated_at) if portfolio.updated_at else None,
    })


# ============================================================
# 포트폴리오 수정 (소유자 또는 관리자)
# ============================================================

@router.put("/{portfolio_id}")
async def update_portfolio(
    portfolio_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # 권한 검사: 소유자(본인) 또는 관리자/admin/super_admin 또는 같은 branch의 director
    user_id = current_user["id"]
    role = current_user["role"]
    is_owner = portfolio.student_id == user_id
    is_admin = role in ("admin", "super_admin")
    is_director = role == "director"
    if is_owner or is_admin:
        pass  # 허용
    elif is_director:
        # 같은 branch의 학생인지 확인
        bid = current_user.get("branch_id", 0)
        if not bid:
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        student_check = await db.execute(
            select(User.id).where(
                User.id == portfolio.student_id,
                User.role == "student",
                User.branch_id == bid,
            )
        )
        if not student_check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    else:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    allowed_fields = {
        "title", "description", "content", "content_url", "file_type",
        "thumbnail_url", "subject", "tags", "is_public", "course_id", "template_id",
    }
    for key, val in data.items():
        if key in allowed_fields:
            setattr(portfolio, key, val)
    
    # image_urls는 JSON 직렬화 필요
    if "image_urls" in data:
        portfolio.image_urls = json.dumps(data["image_urls"], ensure_ascii=False) if isinstance(data["image_urls"], list) else data["image_urls"]

    await db.commit()
    await db.refresh(portfolio)
    return ApiResponse(message="포트폴리오가 수정되었습니다.", data={
        "id": portfolio.id,
        "title": portfolio.title,
        "status": portfolio.status,
    })


# ============================================================
# 포트폴리오 삭제 (소유자 또는 관리자)
# ============================================================

@router.delete("/{portfolio_id}")
async def delete_portfolio(
    portfolio_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # 권한 검사: 소유자(본인) 또는 관리자
    user_id = current_user["id"]
    role = current_user["role"]
    is_owner = portfolio.student_id == user_id
    is_admin = role in ("admin", "super_admin")
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")

    await db.delete(portfolio)
    await db.commit()
    return ApiResponse(message="포트폴리오가 삭제되었습니다.")


# ============================================================
# 포트폴리오 발행/발행취소 (소유자 전용)
# ============================================================

@router.post("/{portfolio_id}/publish")
async def publish_portfolio(
    portfolio_id: int,
    data: dict = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    포트폴리오 발행/발행취소
    - POST body: {"status": "published"} 또는 {"status": "draft"}
    - 기본값: published (발행)
    """
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # 권한 검사: 소유자(본인)만 발행 가능
    user_id = current_user["id"]
    role = current_user["role"]
    is_owner = portfolio.student_id == user_id
    is_admin = role in ("admin", "super_admin")
    is_director = role == "director"
    if is_owner or is_admin:
        pass  # 허용
    elif is_director:
        # 같은 branch의 학생 확인
        bid = current_user.get("branch_id", 0)
        if not bid:
            raise HTTPException(status_code=403, detail="발행 권한이 없습니다.")
        student_check = await db.execute(
            select(User.id).where(
                User.id == portfolio.student_id,
                User.role == "student",
                User.branch_id == bid,
            )
        )
        if not student_check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="발행 권한이 없습니다.")
    else:
        raise HTTPException(status_code=403, detail="발행 권한이 없습니다.")

    new_status = (data or {}).get("status", "published")
    if new_status not in ("draft", "published", "approved", "revision_requested"):
        raise HTTPException(status_code=400, detail="상태는 'draft', 'published', 'approved', 'revision_requested'만 가능합니다.")

    portfolio.status = new_status
    await db.commit()
    await db.refresh(portfolio)

    status_msg = {
        "published": "포트폴리오가 발행되었습니다.",
        "draft": "포트폴리오 발행이 취소되었습니다.",
        "approved": "포트폴리오가 승인되었습니다.",
        "revision_requested": "재작성 요청이 전송되었습니다.",
    }
    message = status_msg.get(new_status, f"상태가 '{new_status}'(으)로 변경되었습니다.")
    return ApiResponse(message=message, data={
        "id": portfolio.id,
        "status": portfolio.status,
    })


# ============================================================
# 포트폴리오 승인 (원장/관리자 전용)
# ============================================================

@router.post("/{portfolio_id}/approve")
async def approve_portfolio(
    portfolio_id: int,
    data: dict = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """포트폴리오를 승인 상태(approved)로 변경"""
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # 권한 검사: 원장(director) 또는 관리자
    role = current_user["role"]
    is_admin = role in ("admin", "super_admin")
    is_director = role == "director"
    if not is_admin and not is_director:
        raise HTTPException(status_code=403, detail="승인 권한이 없습니다.")

    portfolio.status = "approved"
    await db.commit()
    await db.refresh(portfolio)

    # 학생에게 승인 알림
    try:
        from app.api.v1.push_notifications import send_push_notification
        await send_push_notification(
            db,
            portfolio.student_id,
            title="포트폴리오 승인 완료",
            body=f"포트폴리오 '{portfolio.title}'가 승인되었습니다.",
            notif_type="portfolio_approved",
            data={"portfolio_id": portfolio.id, "kind": "portfolio_approved"},
        )
    except Exception:
        pass

    return ApiResponse(message="포트폴리오가 승인되었습니다.", data={
        "id": portfolio.id,
        "status": portfolio.status,
    })


# ============================================================
# 포트폴리오 재작성 요청 (원장/관리자 전용)
# ============================================================

@router.post("/{portfolio_id}/request-revision")
async def request_revision(
    portfolio_id: int,
    data: dict = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """포트폴리오에 코멘트를 남기고 재작성 요청 (revision_requested 상태)"""
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")

    # 권한 검사
    role = current_user["role"]
    is_admin = role in ("admin", "super_admin")
    is_director = role == "director"
    if not is_admin and not is_director:
        raise HTTPException(status_code=403, detail="재작성 요청 권한이 없습니다.")

    comment = (data or {}).get("comment", "")
    portfolio.description = comment
    portfolio.status = "revision_requested"
    await db.commit()
    await db.refresh(portfolio)

    # 학생에게 알림 전송 — 코멘트가 있으면 '반려', 없으면 '수정 요청'
    # (승인/반려/피드백/현황 모두 학생 알림 페이지 화이트리스트에 포함)
    try:
        _has_comment = bool(comment and comment.strip())
        _ntype = "portfolio_rejected" if _has_comment else "portfolio_revision"
        _title = "포트폴리오 반려" if _has_comment else "포트폴리오 수정 요청"
        notif = Notification(
            user_id=portfolio.student_id,
            title=_title,
            content=f"원장님이 포트폴리오 '{portfolio.title}'에 수정을 요청했습니다: {comment[:50]}{'...' if len(comment) > 50 else ''}",
            notif_type=_ntype,
        )
        db.add(notif)
        await db.commit()
        await event_bus.publish(
            portfolio.student_id,
            _ntype,
            {
                "portfolio_id": portfolio.id,
                "title": portfolio.title,
                "message": f"포트폴리오 수정이 요청되었습니다: {portfolio.title}",
            }
        )
    except Exception:
        pass

    return ApiResponse(message="재작성 요청이 전송되었습니다.", data={
        "id": portfolio.id,
        "status": portfolio.status,
        "comment": comment,
    })
