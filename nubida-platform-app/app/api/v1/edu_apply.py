"""
교육 신청(Education Application) API — 2026-09-21
(개편: 게시판형 공고 + 강사 팝업 + 지역 분류)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔒 개인정보 보호 설계 (핵심)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [공개]  인증 불필요
      GET  /edu-apply/programs                 공고 목록 (게시판)
      GET  /edu-apply/programs/{id}            공고 상세
      POST /edu-apply/submit                   공고에 신청 접수
      POST /edu-apply/instructor/upload        강사카드 PDF 업로드
      POST /edu-apply/instructor/submit        소속 강사 신청 접수

  [본사 전용] 인증 + HQ_ONLY_ROLES
      — 공고 관리 —
      POST   /edu-apply/programs               공고 등록
      PUT    /edu-apply/programs/{id}          공고 수정
      DELETE /edu-apply/programs/{id}          공고 삭제
      — 신청자 관리 —
      GET  /edu-apply/programs/{id}/applicants 공고별 신청자 (펼쳐보기)
      GET  /edu-apply/list                     전체 신청 목록
      GET  /edu-apply/instructor/list          강사 목록 (지역별 분류)
      GET  /edu-apply/instructor/regions       지역 목록 + 건수
      POST /edu-apply/status/{kind}/{id}       승인/반려
      POST /edu-apply/note/{kind}/{id}         본사 메모
      DELETE /edu-apply/{kind}/{id}            삭제
      GET  /edu-apply/file/{id}                강사카드 PDF
      GET  /edu-apply/csv/{kind}               CSV
      POST /edu-apply/notify/{kind}/{id}       안내 이력 기록
      GET  /edu-apply/notify/list              안내 이력
      GET  /edu-apply/stats                    요약 통계

⚠️ HQ_ONLY_ROLES 에 없는 역할은 모든 관리 엔드포인트에서 403.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from sqlalchemy import text
from datetime import datetime
import os
import re
import csv
import io
import uuid
import aiofiles

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas import ApiResponse

router = APIRouter(prefix="/edu-apply", tags=["EduApply"])

# ── 개인정보 접근 가능 역할 (본사 전용) ──
HQ_ONLY_ROLES = ("super_admin", "admin")

# ── 업로드 저장 경로 ──
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "uploads", "edu_apply",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

PDF_MAX_BYTES = 10 * 1024 * 1024  # 10MB

VALID_STATUSES = ("pending", "reviewing", "approved", "rejected")
VALID_PROGRAM_STATUSES = ("open", "closed")

STATUS_LABEL_KR = {
    "pending": "접수",
    "reviewing": "확인중",
    "approved": "승인",
    "rejected": "반려",
}
PROGRAM_STATUS_KR = {"open": "모집중", "closed": "마감"}


# ============================================================
# 내부 헬퍼
# ============================================================

def _require_hq(user: dict) -> None:
    """본사(admin/super_admin)가 아니면 403. 개인정보 보호의 유일한 관문."""
    role = (user or {}).get("role", "")
    if role not in HQ_ONLY_ROLES:
        raise HTTPException(403, "본사 관리자만 접근할 수 있습니다.")


def _clean(v, maxlen=200):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:maxlen]


def _check_phone(phone: str) -> str:
    p = _clean(phone, 30)
    if not p:
        raise HTTPException(400, "연락처를 입력해주세요.")
    digits = re.sub(r"[^0-9]", "", p)
    if not (9 <= len(digits) <= 11):
        raise HTTPException(400, "연락처 형식이 올바르지 않습니다.")
    return p


def _client_meta(request: Request):
    ip = None
    try:
        fwd = request.headers.get("x-forwarded-for")
        ip = (fwd.split(",")[0].strip() if fwd
              else (request.client.host if request.client else None))
    except Exception:
        ip = None
    return ip, _clean(request.headers.get("user-agent"), 300)


def _table_of(kind: str) -> str:
    """kind 별 테이블명 매핑 — SQL 인젝션 방지 화이트리스트."""
    if kind in ("application", "app", "edu", "applicant"):
        return "edu_applications"
    if kind in ("instructor", "teacher", "inst"):
        return "edu_instructor_applications"
    raise HTTPException(400, "잘못된 구분입니다.")


def _program_to_dict(r) -> dict:
    """edu_programs row → dict (컬럼 순서 명시 매핑)."""
    return {
        "id": r[0],
        "title": r[1],
        "category": r[2],
        "content": r[3],
        "summary": r[4],
        "status": r[5],
        "status_label": PROGRAM_STATUS_KR.get(r[5], r[5]),
        "recruit_start": r[6],
        "recruit_end": r[7],
        "capacity": r[8],
        "location": r[9],
        "fee": r[10],
        "contact": r[11],
        "is_pinned": bool(r[12]),
        "sort_order": r[13],
        "is_visible": bool(r[14]) if r[14] is not None else True,
        "created_by_name": r[16] if len(r) > 16 else None,
        "created_at": str(r[17]) if len(r) > 17 and r[17] else None,
        "updated_at": str(r[18]) if len(r) > 18 and r[18] else None,
    }


def _row_to_dict(kind: str, r) -> dict:
    """신청 row → dict."""
    if kind == "instructor":
        return {
            "id": r[0], "title": r[1], "name": r[2], "phone": r[3], "email": r[4],
            "region": r[5], "organization": r[6], "memo": r[7],
            "birth_date": r[8], "career": r[9],
            "has_certificate": r[10], "certificate_detail": r[11],
            "has_pdf": bool(r[12]), "pdf_name": r[13],
            "status": r[14], "status_label": STATUS_LABEL_KR.get(r[14], r[14]),
            "admin_note": r[15],
            "created_at": str(r[18]) if len(r) > 18 and r[18] else None,
            "updated_at": str(r[19]) if len(r) > 19 and r[19] else None,
        }
    # application — program_id(1) title(2) name(3) phone(4) email(5) region(6) org(7)
    #               memo(8) status(9) admin_note(10) ip(11) ua(12) created(13) updated(14)
    return {
        "id": r[0],
        "program_id": r[1] if len(r) > 1 else None,
        "title": r[2], "name": r[3], "phone": r[4], "email": r[5],
        "region": r[6], "organization": r[7], "memo": r[8],
        "status": r[9], "status_label": STATUS_LABEL_KR.get(r[9], r[9]),
        "admin_note": r[10],
        "created_at": str(r[13]) if len(r) > 13 and r[13] else None,
        "updated_at": str(r[14]) if len(r) > 14 and r[14] else None,
    }


# ============================================================
# [공개] 공고 게시판 — 인증 불필요
# ============================================================

@router.get("/programs")
async def list_programs_public(
    category: str = Query(None),
    include_closed: int = Query(1),
    db=Depends(get_db),
):
    """공고 목록 (게시판) — 공개.

    모집중 우선 + 상단고정 우선 정렬. 본사가 올린 공고를 방문자가 본다.
    """
    where = ["is_visible = 1"]
    params = {}
    if not include_closed:
        where.append("status = 'open'")
    if category:
        where.append("category = :cat")
        params["cat"] = _clean(category, 80)

    clause = "WHERE " + " AND ".join(where)

    async with db as conn:
        rows = await conn.execute(text(
            f"""SELECT * FROM edu_programs {clause}
                ORDER BY is_pinned DESC,
                         CASE WHEN status='open' THEN 0 ELSE 1 END,
                         sort_order ASC, created_at DESC
                LIMIT 200"""
        ), params)
        programs = [_program_to_dict(r) for r in rows.fetchall()]

        # 각 공고의 신청자 수
        counts = {}
        if programs:
            crows = await conn.execute(text(
                """SELECT program_id, COUNT(*) FROM edu_applications
                   WHERE program_id IS NOT NULL GROUP BY program_id"""
            ))
            for pid, cnt in crows.fetchall():
                counts[pid] = cnt

    for p in programs:
        p["applicant_count"] = counts.get(p["id"], 0)
        # 정원 마감 여부
        cap = p.get("capacity") or 0
        p["is_full"] = bool(cap and p["applicant_count"] >= cap)

    return ApiResponse(status="success", data=programs)


@router.get("/programs/{program_id}")
async def get_program_public(program_id: int, db=Depends(get_db)):
    """공고 상세 — 공개"""
    async with db as conn:
        rows = await conn.execute(
            text("SELECT * FROM edu_programs WHERE id=:pid AND is_visible=1"), {"pid": program_id}
        )
        r = rows.fetchone()
        if not r:
            raise HTTPException(404, "공고를 찾을 수 없습니다.")
        p = _program_to_dict(r)

        c = await conn.execute(
            text("SELECT COUNT(*) FROM edu_applications WHERE program_id=:pid"), {"pid": program_id}
        )
        p["applicant_count"] = c.scalar() or 0
        cap = p.get("capacity") or 0
        p["is_full"] = bool(cap and p["applicant_count"] >= cap)

    return ApiResponse(status="success", data=p)


# ============================================================
# [공개] 신청 접수
# ============================================================

@router.post("/submit")
async def submit_application(
    request: Request,
    program_id: int = Query(...),
    name: str = Query(...),
    phone: str = Query(...),
    email: str = Query(None),
    region: str = Query(None),
    organization: str = Query(None),
    memo: str = Query(None),
    db=Depends(get_db),
):
    """공고에 교육 신청 접수 (공개). 타이틀은 공고에서 자동으로 가져온다."""
    n = _clean(name, 50)
    if not n:
        raise HTTPException(400, "이름을 입력해주세요.")
    ph = _check_phone(phone)

    async with db as conn:
        # 공고 확인 (모집중인지)
        rows = await conn.execute(
            text("SELECT title, status, capacity FROM edu_programs WHERE id=:pid AND is_visible=1"),
            {"pid": program_id},
        )
        prog = rows.fetchone()
        if not prog:
            raise HTTPException(404, "공고를 찾을 수 없습니다.")
        if prog[1] != "open":
            raise HTTPException(400, "마감된 공고입니다.")

        # 정원 확인
        cap = prog[2] or 0
        if cap:
            c = await conn.execute(
                text("SELECT COUNT(*) FROM edu_applications WHERE program_id=:pid"),
                {"pid": program_id},
            )
            if (c.scalar() or 0) >= cap:
                raise HTTPException(400, "정원이 마감되었습니다.")

        ip, ua = _client_meta(request)

        await conn.execute(
            text("""INSERT INTO edu_applications
                    (program_id, title, name, phone, email, region, organization, memo,
                     status, ip_address, user_agent)
                    VALUES (:pid, :title, :name, :phone, :email, :region, :org, :memo,
                            'pending', :ip, :ua)"""),
            {
                "pid": program_id,
                "title": prog[0],
                "name": n, "phone": ph,
                "email": _clean(email, 120),
                "region": _clean(region, 80),
                "org": _clean(organization, 120),
                "memo": _clean(memo, 4000),
                "ip": ip, "ua": ua,
            },
        )
        await conn.commit()

    return ApiResponse(status="success", message="교육 신청이 접수되었습니다. 확인 후 연락드리겠습니다.")


@router.post("/instructor/upload")
async def upload_instructor_pdf(file: UploadFile = File(...)):
    """소속 강사 신청 — 강사카드 PDF 업로드 (공개)"""
    ctype = (file.content_type or "").lower()
    fname = file.filename or "card.pdf"
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

    if ("pdf" not in ctype) and (ext != "pdf"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다.")

    content = await file.read()
    if len(content) > PDF_MAX_BYTES:
        raise HTTPException(400, "파일 크기는 10MB 이하여야 합니다.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "올바른 PDF 파일이 아닙니다.")

    safe_name = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(UPLOAD_DIR, safe_name)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return ApiResponse(
        status="success",
        data={"path": f"/uploads/edu_apply/{safe_name}", "name": _clean(fname, 300)},
    )


@router.post("/instructor/submit")
async def submit_instructor_application(
    request: Request,
    name: str = Query(...),
    phone: str = Query(...),
    email: str = Query(None),
    region: str = Query(None),
    organization: str = Query(None),
    memo: str = Query(None),
    birth_date: str = Query(None),
    career: str = Query(None),
    has_certificate: str = Query(None),
    certificate_detail: str = Query(None),
    pdf_path: str = Query(None),
    pdf_name: str = Query(None),
    db=Depends(get_db),
):
    """소속 강사 신청 접수 (공개) — 팝업에서 호출. 타이틀 고정."""
    n = _clean(name, 50)
    if not n:
        raise HTTPException(400, "이름을 입력해주세요.")
    ph = _check_phone(phone)

    safe_pdf = None
    if pdf_path:
        p = _clean(pdf_path, 300)
        if p and p.startswith("/uploads/edu_apply/") and p.endswith(".pdf"):
            safe_pdf = p

    ip, ua = _client_meta(request)
    title = "소속 강사 신청"

    async with db as conn:
        await conn.execute(
            text("""INSERT INTO edu_instructor_applications
                    (title, name, phone, email, region, organization, memo,
                     birth_date, career, has_certificate, certificate_detail,
                     pdf_path, pdf_name, status, ip_address, user_agent)
                    VALUES (:title, :name, :phone, :email, :region, :org, :memo,
                            :birth, :career, :hascert, :certdetail,
                            :pdf, :pdfname, 'pending', :ip, :ua)"""),
            {
                "title": title, "name": n, "phone": ph,
                "email": _clean(email, 120),
                "region": _clean(region, 80),
                "org": _clean(organization, 120),
                "memo": _clean(memo, 4000),
                "birth": _clean(birth_date, 20),
                "career": _clean(career, 4000),
                "hascert": _clean(has_certificate, 10),
                "certdetail": _clean(certificate_detail, 2000),
                "pdf": safe_pdf, "pdfname": _clean(pdf_name, 300),
                "ip": ip, "ua": ua,
            },
        )
        await conn.commit()

    return ApiResponse(status="success", message="소속 강사 신청이 접수되었습니다. 확인 후 연락드리겠습니다.")


# ============================================================
# [본사 전용] 공고 관리 (게시판)
# ============================================================

@router.get("/admin/programs")
async def list_programs_admin(
    status: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """공고 목록 (관리용 — 숨김 포함) — 🔒 본사 전용"""
    _require_hq(user)

    where, params = [], {}
    if status and status in VALID_PROGRAM_STATUSES:
        where.append("status = :st")
        params["st"] = status
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db as conn:
        rows = await conn.execute(text(
            f"""SELECT * FROM edu_programs {clause}
                ORDER BY is_pinned DESC, sort_order ASC, created_at DESC LIMIT 500"""
        ), params)
        programs = [_program_to_dict(r) for r in rows.fetchall()]

        counts = {}
        crows = await conn.execute(text(
            """SELECT program_id, COUNT(*) FROM edu_applications
               WHERE program_id IS NOT NULL GROUP BY program_id"""
        ))
        for pid, cnt in crows.fetchall():
            counts[pid] = cnt

        # 상태별 건수 (펼침용)
        stat = {}
        srows = await conn.execute(text(
            """SELECT program_id, status, COUNT(*) FROM edu_applications
               WHERE program_id IS NOT NULL GROUP BY program_id, status"""
        ))
        for pid, st, cnt in srows.fetchall():
            stat.setdefault(pid, {})[st] = cnt

    for p in programs:
        p["applicant_count"] = counts.get(p["id"], 0)
        p["status_counts"] = stat.get(p["id"], {})

    return ApiResponse(status="success", data=programs)


@router.post("/programs")
async def create_program(
    title: str = Query(...),
    content: str = Query(None),
    summary: str = Query(None),
    category: str = Query(None),
    status: str = Query("open"),
    recruit_start: str = Query(None),
    recruit_end: str = Query(None),
    capacity: int = Query(0),
    location: str = Query(None),
    fee: str = Query(None),
    contact: str = Query(None),
    is_pinned: int = Query(0),
    is_visible: int = Query(1),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """공고 등록 — 🔒 본사 전용"""
    _require_hq(user)

    t = _clean(title, 200)
    if not t:
        raise HTTPException(400, "공고 제목을 입력해주세요.")
    st = status if status in VALID_PROGRAM_STATUSES else "open"

    async with db as conn:
        await conn.execute(
            text("""INSERT INTO edu_programs
                    (title, category, content, summary, status, recruit_start, recruit_end,
                     capacity, location, fee, contact, is_pinned, sort_order, is_visible,
                     created_by, created_by_name)
                    VALUES (:title, :cat, :content, :summary, :st, :rs, :re,
                            :cap, :loc, :fee, :contact, :pin, 0, :vis,
                            :uid, :uname)"""),
            {
                "title": t,
                "cat": _clean(category, 80),
                "content": _clean(content, 20000),
                "summary": _clean(summary, 300),
                "st": st,
                "rs": _clean(recruit_start, 20),
                "re": _clean(recruit_end, 20),
                "cap": capacity or 0,
                "loc": _clean(location, 120),
                "fee": _clean(fee, 80),
                "contact": _clean(contact, 120),
                "pin": 1 if is_pinned else 0,
                "vis": 1 if is_visible else 0,
                "uid": user.get("id"),
                "uname": user.get("name", "본사"),
            },
        )
        await conn.commit()

    return ApiResponse(status="success", message="공고가 등록되었습니다.")


@router.put("/programs/{program_id}")
async def update_program(
    program_id: int,
    title: str = Query(None),
    content: str = Query(None),
    summary: str = Query(None),
    category: str = Query(None),
    status: str = Query(None),
    recruit_start: str = Query(None),
    recruit_end: str = Query(None),
    capacity: int = Query(None),
    location: str = Query(None),
    fee: str = Query(None),
    contact: str = Query(None),
    is_pinned: int = Query(None),
    is_visible: int = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """공고 수정 — 🔒 본사 전용. 전달된 필드만 갱신한다."""
    _require_hq(user)

    sets, params = [], {"pid": program_id}

    def put(col, val):
        sets.append(f"{col} = :{col}")
        params[col] = val

    if title is not None:
        t = _clean(title, 200)
        if not t:
            raise HTTPException(400, "공고 제목을 입력해주세요.")
        put("title", t)
    if content is not None:
        put("content", _clean(content, 20000))
    if summary is not None:
        put("summary", _clean(summary, 300))
    if category is not None:
        put("category", _clean(category, 80))
    if status is not None:
        if status not in VALID_PROGRAM_STATUSES:
            raise HTTPException(400, "잘못된 모집 상태입니다.")
        put("status", status)
    if recruit_start is not None:
        put("recruit_start", _clean(recruit_start, 20))
    if recruit_end is not None:
        put("recruit_end", _clean(recruit_end, 20))
    if capacity is not None:
        put("capacity", capacity or 0)
    if location is not None:
        put("location", _clean(location, 120))
    if fee is not None:
        put("fee", _clean(fee, 80))
    if contact is not None:
        put("contact", _clean(contact, 120))
    if is_pinned is not None:
        put("is_pinned", 1 if is_pinned else 0)
    if is_visible is not None:
        put("is_visible", 1 if is_visible else 0)

    if not sets:
        raise HTTPException(400, "수정할 항목이 없습니다.")

    sets.append("updated_at = :now")
    params["now"] = datetime.now()

    async with db as conn:
        chk = await conn.execute(text("SELECT id FROM edu_programs WHERE id=:pid"), {"pid": program_id})
        if not chk.fetchone():
            raise HTTPException(404, "공고를 찾을 수 없습니다.")

        await conn.execute(
            text(f"UPDATE edu_programs SET {', '.join(sets)} WHERE id=:pid"), params
        )
        await conn.commit()

    return ApiResponse(status="success", message="공고가 수정되었습니다.")


@router.delete("/programs/{program_id}")
async def delete_program(
    program_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """공고 삭제 — 🔒 본사 전용.

    신청 데이터는 보존한다 (title 스냅샷이 남아 있음).
    program_id 만 NULL 처리해 고아 참조를 막는다.
    """
    _require_hq(user)

    async with db as conn:
        chk = await conn.execute(text("SELECT id FROM edu_programs WHERE id=:pid"), {"pid": program_id})
        if not chk.fetchone():
            raise HTTPException(404, "공고를 찾을 수 없습니다.")

        await conn.execute(
            text("UPDATE edu_applications SET program_id=NULL WHERE program_id=:pid"),
            {"pid": program_id},
        )
        await conn.execute(text("DELETE FROM edu_programs WHERE id=:pid"), {"pid": program_id})
        await conn.commit()

    return ApiResponse(status="success", message="공고가 삭제되었습니다. (접수된 신청은 보존됩니다)")


@router.get("/programs/{program_id}/applicants")
async def list_program_applicants(
    program_id: int,
    status: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """특정 공고의 신청자 목록 — 🔒 본사 전용 (공고 → 신청자 펼쳐보기)"""
    _require_hq(user)

    where = ["program_id = :pid"]
    params = {"pid": program_id}
    if status and status in VALID_STATUSES:
        where.append("status = :st")
        params["st"] = status

    async with db as conn:
        rows = await conn.execute(text(
            f"""SELECT * FROM edu_applications WHERE {' AND '.join(where)}
                ORDER BY created_at DESC LIMIT 2000"""
        ), params)
        items = [_row_to_dict("application", r) for r in rows.fetchall()]

    return ApiResponse(status="success", data=items)


# ============================================================
# [본사 전용] 신청자 관리
# ============================================================

@router.get("/list")
async def list_applications(
    status: str = Query(None),
    q: str = Query(None),
    program_id: int = Query(None),
    region: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """교육 신청 전체 목록 — 🔒 본사 전용"""
    _require_hq(user)

    where, params = [], {}
    if status and status in VALID_STATUSES:
        where.append("status = :st")
        params["st"] = status
    if program_id:
        where.append("program_id = :pid")
        params["pid"] = program_id
    if region:
        where.append("region = :rg")
        params["rg"] = _clean(region, 80)
    if q:
        where.append("(name LIKE :q OR phone LIKE :q OR title LIKE :q OR organization LIKE :q)")
        params["q"] = f"%{_clean(q, 100)}%"
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db as conn:
        rows = await conn.execute(
            text(f"SELECT * FROM edu_applications {clause} ORDER BY created_at DESC LIMIT 2000"),
            params,
        )
        items = [_row_to_dict("application", r) for r in rows.fetchall()]

    return ApiResponse(status="success", data=items)


@router.get("/instructor/list")
async def list_instructor_applications(
    status: str = Query(None),
    q: str = Query(None),
    region: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """소속 강사 신청 목록 (지역 필터) — 🔒 본사 전용"""
    _require_hq(user)

    where, params = [], {}
    if status and status in VALID_STATUSES:
        where.append("status = :st")
        params["st"] = status
    if region:
        where.append("region = :rg")
        params["rg"] = _clean(region, 80)
    if q:
        where.append("(name LIKE :q OR phone LIKE :q OR organization LIKE :q OR certificate_detail LIKE :q)")
        params["q"] = f"%{_clean(q, 100)}%"
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db as conn:
        rows = await conn.execute(
            text(f"SELECT * FROM edu_instructor_applications {clause} ORDER BY created_at DESC LIMIT 2000"),
            params,
        )
        items = [_row_to_dict("instructor", r) for r in rows.fetchall()]

    return ApiResponse(status="success", data=items)


@router.get("/instructor/regions")
async def instructor_regions(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """강사 신청 지역 목록 + 건수 — 🔒 본사 전용 (지역별 분류용)

    지역 미입력은 '미지정' 으로 묶는다.
    """
    _require_hq(user)

    async with db as conn:
        rows = await conn.execute(text(
            """SELECT COALESCE(NULLIF(TRIM(region), ''), '미지정') AS rg, COUNT(*)
               FROM edu_instructor_applications
               GROUP BY rg ORDER BY COUNT(*) DESC, rg ASC"""
        ))
        regions = [{"region": r[0], "count": r[1]} for r in rows.fetchall()]

        # 전체
        total = await conn.execute(text("SELECT COUNT(*) FROM edu_instructor_applications"))
        total_cnt = total.scalar() or 0

    return ApiResponse(status="success", data={"regions": regions, "total": total_cnt})


@router.post("/status/{kind}/{item_id}")
async def update_status(
    kind: str,
    item_id: int,
    status: str = Query(...),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """승인 / 반려 상태 변경 — 🔒 본사 전용"""
    _require_hq(user)
    table = _table_of(kind)

    if status not in VALID_STATUSES:
        raise HTTPException(400, "잘못된 상태값입니다.")

    async with db as conn:
        chk = await conn.execute(text(f"SELECT id FROM {table} WHERE id=:iid"), {"iid": item_id})
        if not chk.fetchone():
            raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")

        await conn.execute(
            text(f"UPDATE {table} SET status=:st, updated_at=:at WHERE id=:iid"),
            {"st": status, "at": datetime.now(), "iid": item_id},
        )
        await conn.commit()

    return ApiResponse(status="success", message=f"{STATUS_LABEL_KR.get(status, status)} 처리되었습니다.")


@router.post("/note/{kind}/{item_id}")
async def update_note(
    kind: str,
    item_id: int,
    note: str = Query(""),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """본사 메모 저장 (신청자 비노출) — 🔒 본사 전용"""
    _require_hq(user)
    table = _table_of(kind)

    async with db as conn:
        await conn.execute(
            text(f"UPDATE {table} SET admin_note=:note, updated_at=:at WHERE id=:iid"),
            {"note": _clean(note, 4000), "at": datetime.now(), "iid": item_id},
        )
        await conn.commit()

    return ApiResponse(status="success", message="메모가 저장되었습니다.")


@router.delete("/{kind}/{item_id}")
async def delete_application(
    kind: str,
    item_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """신청 삭제 — 🔒 본사 전용. 첨부 PDF 도 함께 정리."""
    _require_hq(user)
    table = _table_of(kind)

    async with db as conn:
        row = await conn.execute(text(f"SELECT * FROM {table} WHERE id=:iid"), {"iid": item_id})
        item = row.fetchone()
        if not item:
            raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")

        if table == "edu_instructor_applications":
            pdf_rel = item[12]
            if pdf_rel:
                fp = os.path.join(UPLOAD_DIR, os.path.basename(pdf_rel))
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                except Exception:
                    pass

        await conn.execute(text(f"DELETE FROM {table} WHERE id=:iid"), {"iid": item_id})
        await conn.commit()

    return ApiResponse(status="success", message="삭제되었습니다.")


@router.get("/stats")
async def get_stats(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """요약 통계 — 🔒 본사 전용"""
    _require_hq(user)

    async with db as conn:
        out = {}
        for key, table in (("application", "edu_applications"),
                           ("instructor", "edu_instructor_applications")):
            rows = await conn.execute(
                text(f"SELECT status, COUNT(*) FROM {table} GROUP BY status")
            )
            counts = {s: 0 for s in VALID_STATUSES}
            total = 0
            for st, cnt in rows.fetchall():
                counts[st] = cnt
                total += cnt
            out[key] = {"total": total, "counts": counts}

        # 공고 통계
        prows = await conn.execute(text(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_cnt
               FROM edu_programs WHERE is_visible=1"""
        ))
        pr = prows.fetchone()
        out["program"] = {"total": pr[0] or 0, "open": pr[1] or 0}

        # 지역 수
        rrows = await conn.execute(text(
            """SELECT COUNT(DISTINCT COALESCE(NULLIF(TRIM(region),''),'미지정'))
               FROM edu_instructor_applications"""
        ))
        out["region_count"] = rrows.scalar() or 0

    return ApiResponse(status="success", data=out)


# ============================================================
# [본사 전용] 강사카드 PDF / CSV / 안내 이력
# ============================================================

@router.get("/file/{item_id}")
async def download_instructor_pdf(
    item_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """강사카드 PDF 다운로드 — 🔒 본사 전용."""
    _require_hq(user)

    async with db as conn:
        row = await conn.execute(
            text("SELECT pdf_path, pdf_name, name FROM edu_instructor_applications WHERE id=:iid"),
            {"iid": item_id},
        )
        item = row.fetchone()

    if not item or not item[0]:
        raise HTTPException(404, "첨부된 강사카드가 없습니다.")

    fp = os.path.join(UPLOAD_DIR, os.path.basename(item[0]))
    if not os.path.isfile(fp):
        raise HTTPException(404, "파일을 찾을 수 없습니다.")

    from fastapi.responses import FileResponse
    return FileResponse(fp, media_type="application/pdf",
                        filename=item[1] or f"{item[2] or 'instructor'}_card.pdf")


@router.get("/csv/{kind}")
async def export_csv(
    kind: str,
    status: str = Query(None),
    program_id: int = Query(None),
    region: str = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """CSV 내보내기 — 🔒 본사 전용 (개인정보 포함)"""
    _require_hq(user)
    table = _table_of(kind)

    where, params = [], {}
    if status and status in VALID_STATUSES:
        where.append("status = :st")
        params["st"] = status
    if table == "edu_applications" and program_id:
        where.append("program_id = :pid")
        params["pid"] = program_id
    if region:
        where.append("region = :rg")
        params["rg"] = _clean(region, 80)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db as conn:
        rows = await conn.execute(
            text(f"SELECT * FROM {table} {clause} ORDER BY created_at DESC LIMIT 5000"),
            params,
        )
        items = [_row_to_dict("instructor" if table == "edu_instructor_applications" else "application", r)
                 for r in rows.fetchall()]

    if table == "edu_instructor_applications":
        header = ["접수일", "상태", "이름", "연락처", "이메일", "지역", "소속",
                  "생년월일", "경력", "자격증유무", "자격증상세", "강사카드", "비고", "본사메모"]
        fields = ["created_at", "status_label", "name", "phone", "email", "region",
                  "organization", "birth_date", "career", "has_certificate",
                  "certificate_detail", "pdf_name", "memo", "admin_note"]
    else:
        header = ["접수일", "상태", "공고", "이름", "연락처", "이메일", "지역", "소속", "비고", "본사메모"]
        fields = ["created_at", "status_label", "title", "name", "phone", "email",
                  "region", "organization", "memo", "admin_note"]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for it in items:
        w.writerow([it.get(f, "") if it.get(f) is not None else "" for f in fields])

    from fastapi.responses import Response
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="edu_{kind}_{stamp}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/notify/{kind}/{item_id}")
async def log_notify(
    kind: str,
    item_id: int,
    channel: str = Query("sms"),
    subject: str = Query(None),
    body: str = Query(...),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """승인 안내 발송 이력 기록 — 🔒 본사 전용.

    실제 발송은 하지 않는다 (외부 연동 없음 → 오발송 위험 0).
    """
    _require_hq(user)
    table = _table_of(kind)

    ch = (channel or "sms").lower()
    if ch not in ("sms", "email"):
        ch = "sms"

    async with db as conn:
        row = await conn.execute(
            text(f"SELECT name, phone, email FROM {table} WHERE id=:iid"), {"iid": item_id}
        )
        item = row.fetchone()
        if not item:
            raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")

        await conn.execute(
            text("""INSERT INTO edu_notify_logs
                    (target_type, target_id, recipient_name, recipient_phone, recipient_email,
                     channel, subject, body, sent_by, sent_by_name)
                    VALUES (:tt, :tid, :rn, :rp, :re, :ch, :sub, :body, :uid, :uname)"""),
            {
                "tt": "instructor" if table == "edu_instructor_applications" else "application",
                "tid": item_id,
                "rn": item[0], "rp": item[1], "re": item[2],
                "ch": ch,
                "sub": _clean(subject, 200),
                "body": _clean(body, 8000),
                "uid": user.get("id"),
                "uname": user.get("name", "본사"),
            },
        )
        await conn.commit()

    return ApiResponse(status="success", message="발송 이력이 기록되었습니다.")


@router.get("/notify/list")
async def list_notify_logs(
    kind: str = Query(None),
    item_id: int = Query(None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """안내 발송 이력 조회 — 🔒 본사 전용"""
    _require_hq(user)

    where, params = [], {}
    if kind:
        where.append("target_type = :tt")
        params["tt"] = "instructor" if "inst" in kind else "application"
    if item_id:
        where.append("target_id = :tid")
        params["tid"] = item_id
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db as conn:
        rows = await conn.execute(
            text(f"""SELECT id, target_type, target_id, recipient_name, recipient_phone,
                            recipient_email, channel, subject, body, sent_by_name, sent_at
                     FROM edu_notify_logs {clause} ORDER BY sent_at DESC LIMIT 500"""),
            params,
        )
        items = [{
            "id": r[0], "target_type": r[1], "target_id": r[2],
            "recipient_name": r[3], "recipient_phone": r[4], "recipient_email": r[5],
            "channel": r[6], "subject": r[7], "body": r[8],
            "sent_by_name": r[9],
            "sent_at": str(r[10]) if r[10] else None,
        } for r in rows.fetchall()]

    return ApiResponse(status="success", data=items)
