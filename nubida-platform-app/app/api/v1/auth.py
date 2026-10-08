from fastapi import APIRouter, Depends, HTTPException, Query
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.core import totp as _totp
from app.core.security import (
    hash_password, verify_password, create_access_token, needs_rehash,
    get_current_user, require_role, create_unique_registration_code
)
from app.models import User
from app.schemas import LoginRequest, UserCreate, PasswordChange, ApiResponse, FindIdRequest, FindPasswordRequest

router = APIRouter(prefix="/auth", tags=["인증"])


async def _nubida_machine_locked(user, db) -> bool:
    """누비다머신 잠금 판정 — 학생이면 소속 원장의 잠금 플래그, 그 외엔 자기 계정 값"""
    if user.role == "student" and user.director_id:
        director = (await db.execute(
            select(User).where(User.id == user.director_id)
        )).scalar_one_or_none()
        if director:
            return bool(director.nubida_machine_locked or False)
    return bool(user.nubida_machine_locked or False)


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timedelta, timezone

    # ══════════════════════════════════════════════════════════════
    #  로그인 시도 제한 (rate limit) — 2026-09-14 보안 점검
    # --------------------------------------------------------------
    #  · 계정당 연속 5회 실패 → 10분 잠금
    #  · 잠금 중에는 올바른 비밀번호도 거부 (무차별 대입 차단)
    #  · 로그인 성공 시 카운터/잠금 즉시 초기화
    # ══════════════════════════════════════════════════════════════
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_MINUTES = 10

    def _now():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    # ── 잠금 상태 확인 (계정이 존재할 때만) ──
    if user is not None:
        _locked = getattr(user, "locked_until", None)
        if _locked is not None and _now() < _locked:
            _remain = int((_locked - _now()).total_seconds() // 60) + 1
            raise HTTPException(
                status_code=429,
                detail=f"로그인 시도가 너무 많습니다. {_remain}분 후 다시 시도해 주세요.",
            )
        # 잠금 시각이 지났으면 자동 해제
        if _locked is not None and _now() >= _locked:
            user.locked_until = None
            user.failed_login_attempts = 0
            await db.commit()

    # ── 인증 실패 처리 ──
    if not user or not verify_password(req.password, user.password_hash):
        if user is not None:
            _fails = int(getattr(user, "failed_login_attempts", 0) or 0) + 1
            # ⚠️ HTTPException 을 던지면 이 요청의 세션이 정리될 수 있으므로
            #    실패 카운트는 "별도 세션"으로 확실히 커밋한다 (2026-09-14).
            from app.core.database import async_session as _async_session
            async with _async_session() as _s:
                _u = (await _s.execute(
                    select(User).where(User.id == user.id)
                )).scalar_one_or_none()
                if _u is not None:
                    _u.failed_login_attempts = _fails
                    if _fails >= MAX_FAILED_ATTEMPTS:
                        _u.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
                    await _s.commit()

            if _fails >= MAX_FAILED_ATTEMPTS:
                raise HTTPException(
                    status_code=429,
                    detail=f"로그인 {MAX_FAILED_ATTEMPTS}회 실패로 계정이 {LOCKOUT_MINUTES}분간 잠겼습니다.",
                )
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    if not user.is_active:
        if user.approved_by is None:
            if user.role in ("branch_admin", "director"):
                raise HTTPException(status_code=403, detail="본사 관리자의 승인 대기 중인 계정입니다. 승인 후 이용 가능합니다.")
            elif user.role in ("student", "parent"):
                raise HTTPException(status_code=403, detail="원장님의 승인 대기 중인 계정입니다. 승인 후 이용 가능합니다.")
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다. 관리자에게 문의하세요.")
        else:
            raise HTTPException(status_code=403, detail="거절 또는 비활성화된 계정입니다. 관리자에게 문의하세요.")

    # ── 이중로그인 방지: 로그인마다 login_version 증가 → 이전 기기 토큰 즉시 무효화 ──
    user.login_version = int(user.login_version or 1) + 1
    # ── 로그인 시도 제한: 성공했으므로 실패 카운터/잠금 초기화 (2026-09-14) ──
    user.failed_login_attempts = 0
    user.locked_until = None
    # ── 비밀번호 자동 업그레이드: 구형(무염 SHA-256/평문) → PBKDF2 (2026-09-14) ──
    try:
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(req.password)
    except Exception:
        pass
    await db.commit()
    await db.refresh(user)

    # ══════════════════════════════════════════════════════════════
    #  관리자 2단계 인증 (TOTP) — 2026-09-14 보안 강화
    # --------------------------------------------------------------
    #  · super_admin/admin/hq_admin 이고 totp_enabled=1 이면
    #    비밀번호가 맞아도 여기서 6자리 코드를 요구한다.
    #  · totp_code 가 없으면 {"totp_required": true} 를 data 로 반환(401 아님)
    #    → 프론트는 코드 입력 화면을 띄우고 같은 엔드포인트에 totp_code 를 붙여 재요청.
    #  · login_version 증가는 "최종 성공 시점"으로 미룬다(2단계 도중 세션 무효화 방지).
    # ══════════════════════════════════════════════════════════════
    _needs_totp = (
        bool(getattr(user, "totp_enabled", False))
        and user.role in ("super_admin", "admin", "hq_admin")
        and bool(getattr(user, "totp_secret", None))
    )
    if _needs_totp:
        _code = (getattr(req, "totp_code", None) or "").strip()
        _recovery_ok = False
        if _code and not _code.isdigit():
            # 복구코드 사용 시도
            try:
                _hashes = json.loads(user.totp_recovery or "[]")
            except Exception:
                _hashes = []
            if _totp.verify_recovery_code(_code, _hashes):
                _recovery_ok = True
                _used = _totp.hash_recovery_code(_code)
                _remain_hashes = [h for h in _hashes if h != _used]
                # ⚠️ 복구코드는 1회용 — 여기서 "별도 세션"으로 즉시 소모 커밋한다.
                #    (요청 세션에서만 바꾸면 반환/예외 시 롤백되어 재사용 가능해진다)
                from app.core.database import async_session as _as_rc
                async with _as_rc() as _s_rc:
                    _u_rc = (await _s_rc.execute(
                        select(User).where(User.id == user.id)
                    )).scalar_one_or_none()
                    if _u_rc is not None:
                        _u_rc.totp_recovery = json.dumps(_remain_hashes, ensure_ascii=False)
                        await _s_rc.commit()
                user.totp_recovery = json.dumps(_remain_hashes, ensure_ascii=False)

        if not _code:
            # 1단계: 코드 필요 응답 (비밀번호는 이미 검증됨)
            return ApiResponse(data={
                "totp_required": True,
                "message": "2단계 인증 코드를 입력해 주세요.",
            })

        if not _recovery_ok and not _totp.verify_totp(user.totp_secret, _code):
            # 실패도 카운트에 반영 (무차별 대입 차단)
            _fails = int(getattr(user, "failed_login_attempts", 0) or 0) + 1
            from app.core.database import async_session as _as2
            async with _as2() as _s2:
                _u2 = (await _s2.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
                if _u2 is not None:
                    _u2.failed_login_attempts = _fails
                    if _fails >= 5:
                        _u2.locked_until = _now() + timedelta(minutes=10)
                    await _s2.commit()
            raise HTTPException(status_code=401, detail="2단계 인증 코드가 올바르지 않습니다.")

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "name": user.name,
        "branch_id": user.branch_id or 0,
        "login_version": user.login_version,
    })

    return ApiResponse(data={
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "branch_id": user.branch_id,
            "nubida_machine_locked": await _nubida_machine_locked(user, db),
        }
    })


# In-memory store for password reset tokens (DEV only, no SMTP yet)
password_reset_tokens: dict = {}
# 발급 토큰 메타 (토큰 -> {username, ts}) — 만료 검증용
_password_reset_issued: dict = {}
_RESET_TOKEN_TTL = 600  # 10분


@router.post("/find-id")
async def find_id(req: FindIdRequest, db: AsyncSession = Depends(get_db)):
    if not req.email and not req.phone:
        raise HTTPException(status_code=400, detail="이메일 또는 휴대전화를 입력해주세요.")
    
    if req.email:
        result = await db.execute(
            select(User).where(User.name == req.name, User.email == req.email)
        )
    else:
        result = await db.execute(
            select(User).where(User.name == req.name, User.phone == req.phone)
        )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="일치하는 계정을 찾을 수 없습니다.")
    return ApiResponse(data={"username": user.username, "created_at": str(user.created_at)})


@router.get("/check-username")
async def check_username(
    username: str = Query(..., min_length=3),
    db: AsyncSession = Depends(get_db),
):
    """아이디 중복 확인"""
    import re
    if not re.match(r'^[a-zA-Z0-9]+$', username):
        raise HTTPException(status_code=400, detail="영문과 숫자만 입력 가능합니다.")
    if len(username) < 4:
        raise HTTPException(status_code=400, detail="아이디는 4자 이상이어야 합니다.")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    # pending.db에서도 확인
    from app.pending_db import get_pending_conn
    pend_conn = get_pending_conn()
    pend_c = pend_conn.cursor()
    pend_c.execute(
        "SELECT id FROM pending_approvals WHERE username = %s AND status = 'pending'",
        (username,)
    )
    if pend_c.fetchone():
        pend_conn.close()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
    pend_conn.close()

    return ApiResponse(data={"username": username, "available": True})


@router.post("/find-password")
async def find_password(req: FindPasswordRequest, db: AsyncSession = Depends(get_db)):
    if not req.email and not req.phone:
        raise HTTPException(status_code=400, detail="이메일 또는 휴대전화를 입력해주세요.")

    # 본인확인 조건 구성 (아이디 + (이메일 or 휴대전화) + 이름이 주어지면 이름까지 일치)
    conds = [User.username == req.username]
    if req.email:
        conds.append(User.email == req.email)
    else:
        conds.append(User.phone == req.phone)
    name_in = getattr(req, "name", None)
    if name_in:
        conds.append(User.name == name_in)

    result = await db.execute(select(User).where(*conds))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="입력하신 정보와 일치하는 계정을 찾을 수 없습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다. 관리자에게 문의해주세요.")

    # 본인확인이 끝났으므로 재설정 토큰 즉시 발급 (화면에서 바로 재설정 — 이메일/SMS 불필요)
    import secrets as _secrets, time as _time
    token = _secrets.token_urlsafe(24)
    password_reset_tokens[req.username] = token
    _password_reset_issued[token] = {"username": req.username, "ts": _time.time()}

    return ApiResponse(
        data={
            "reset_token": token,
            "username": user.username,
            "name": user.name,
        },
        message="본인 확인이 완료되었습니다. 새 비밀번호를 입력해주세요.",
    )


@router.post("/reset-password")
async def reset_password(data: dict, db: AsyncSession = Depends(get_db)):
    """비밀번호 재설정 (본인확인 토큰 검증 후 변경)"""
    import time as _time
    token = (data.get("token") or "").strip()
    new_password = data.get("new_password") or ""

    if not token or not new_password:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청입니다.")

    # 토큰 검증 (메타 저장소 우선, 하위호환으로 기존 dict도 확인)
    username = None
    meta = _password_reset_issued.get(token)
    if meta:
        if _time.time() - meta["ts"] > _RESET_TOKEN_TTL:
            _password_reset_issued.pop(token, None)
            raise HTTPException(status_code=400, detail="재설정 시간이 만료되었습니다. 처음부터 다시 시도해주세요.")
        username = meta["username"]
    else:
        for uname, stored_token in password_reset_tokens.items():
            if stored_token and stored_token == token:
                username = uname
                break

    if not username:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청입니다.")

    # 비밀번호 정책 검증
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.password_hash = hash_password(new_password)
    await db.commit()

    # 사용된 토큰 제거 (1회용)
    _password_reset_issued.pop(token, None)
    password_reset_tokens.pop(username, None)

    return ApiResponse(message="비밀번호가 성공적으로 변경되었습니다.")


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "registration_code": user.registration_code,
        "branch_id": user.branch_id,
        "is_active": user.is_active,
        "onboarding_done": bool(user.onboarding_done or False),
        "nubida_machine_locked": await _nubida_machine_locked(user, db),
        "created_at": str(user.created_at)
    })


@router.patch("/me/onboarding")
async def update_onboarding(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """온보딩 완료 상태 저장 — 사용 가이드가 무한 재표시되지 않도록 함"""
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if not isinstance(data.get("onboarding_done"), bool):
        raise HTTPException(status_code=400, detail="onboarding_done은 true/false 여야 합니다.")

    user.onboarding_done = data["onboarding_done"]
    await db.commit()
    await db.refresh(user)
    return ApiResponse(
        message="온보딩 상태가 저장되었습니다.",
        data={"onboarding_done": user.onboarding_done},
    )


@router.put("/me")
async def update_me(data: dict, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    for field in ["name", "email", "phone"]:
        if field in data:
            setattr(user, field, data[field])

    await db.commit()
    return ApiResponse(message="정보가 수정되었습니다.")


@router.put("/password")
async def change_password(req: PasswordChange, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()

    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")

    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return ApiResponse(message="비밀번호가 변경되었습니다.")


@router.get("/me/notifications")
async def get_notification_settings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current_user["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    settings = getattr(user, "notification_settings", None) or {}
    return ApiResponse(data=settings)


@router.put("/me/notifications")
async def update_notification_settings(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(User).where(User.id == current_user["id"]).values(notification_settings=data)
    )
    await db.commit()
    return ApiResponse(message="알림 설정이 저장되었습니다.")


@router.get("/verify-code")
async def verify_code(
    code: str = Query(..., description="등록코드 (예: #000001)"),
    db: AsyncSession = Depends(get_db),
):
    """등록코드 유효성 검증 — role 파라미터로 필터링 가능
    - 학생/학부모: 원장(director) 코드
    - 원장: 에듀케어(branch_admin) 코드
    """
    input_code = code.strip().lstrip("#")
    
    # 먼저 원장 코드 검색
    result = await db.execute(
        select(User).where(User.registration_code == "#" + input_code, User.role == "director")
    )
    user = result.scalar_one_or_none()
    role_type = "director"
    
    # 원장 코드가 없으면 에듀케어 코드 검색
    if not user:
        result = await db.execute(
            select(User).where(User.registration_code == "#" + input_code, User.role == "branch_admin")
        )
        user = result.scalar_one_or_none()
        role_type = "branch_admin"
    
    # pending.db에도 검색
    if not user:
        from app.pending_db import get_pending_conn
        pend_conn = get_pending_conn()
        pend_c = pend_conn.cursor()
        pend_c.execute(
            "SELECT id, username, name, role, branch_id FROM pending_approvals WHERE registration_code = %s AND role IN ('director','branch_admin') AND status = 'pending'",
            ("#" + input_code,)
        )
        pend_row = pend_c.fetchone()
        if pend_row:
            user = type('Obj', (), {
                'id': pend_row[0],
                'username': pend_row[1],
                'name': pend_row[2],
                'role': pend_row[3],
                'branch_id': pend_row[4],
            })()
            role_type = pend_row[3]
        pend_conn.close()
    
    if not user:
        raise HTTPException(status_code=404, detail="유효하지 않은 등록코드입니다.")

    branch_name = None
    if user.branch_id:
        from app.models import Branch
        br = await db.get(Branch, user.branch_id)
        if br:
            branch_name = br.name

    label = "원장" if role_type == "director" else "에듀케어"
    return ApiResponse(data={
        "name": user.name,
        "user_id": user.id,
        "branch_id": user.branch_id,
        "branch_name": branch_name,
        "registration_code": user.registration_code,
        "role": role_type,
        "label": label,
    })


@router.post("/register")
async def register(req: UserCreate, db: AsyncSession = Depends(get_db)):
    # 중복 확인 (메인 DB)
    result = await db.execute(select(User).where(
        (User.username == req.username) | (User.email == req.email)
    ))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 존재하는 이메일입니다.")

    # 등록코드 처리: 학생/학부모는 입력한 코드로 원장/지사 연결
    branch_id = req.branch_id
    user_director_id = None
    if req.registration_code:
        input_code = req.registration_code.strip().lstrip("#")
        # 원장(director) 또는 에듀케어(branch_admin)의 등록코드로 검색 (메인 DB)
        code_result = await db.execute(
            select(User).where(User.registration_code == "#" + input_code, User.role.in_(["director", "branch_admin"]))
        )
        matched_user = code_result.scalar_one_or_none()
        
        # 메인 DB에 없으면 pending.db에서 검색
        if not matched_user:
            from app.pending_db import get_pending_conn
            pend_conn = get_pending_conn()
            try:
                pend_c = pend_conn.cursor()
                pend_c.execute(
                    "SELECT id, username, name, role, branch_id FROM pending_approvals WHERE registration_code = %s AND role IN ('director','branch_admin') AND status = 'pending'",
                    ("#" + input_code,)
                )
                pend_row = pend_c.fetchone()
                if pend_row:
                    # pending.db 사용자를 dict로 변환 (DictCursor/SQLite 래퍼 모두 dict 반환)
                    matched_user = type('Obj', (), {
                        'id': pend_row['id'],
                        'username': pend_row['username'],
                        'name': pend_row['name'],
                        'role': pend_row['role'],
                        'branch_id': pend_row['branch_id'],
                    })()
            finally:
                pend_conn.close()
        
        if matched_user:
            if matched_user.branch_id:
                branch_id = matched_user.branch_id
            # 등록코드가 원장(director)이면 학생의 director_id 설정
            if matched_user.role == "director" and req.role in ("student", "parent"):
                user_director_id = matched_user.id

    # branch_name으로 지사 검색 (원장/에듀케어)
    if not branch_id and getattr(req, 'branch_name', None):
        from app.models import Branch
        br_result = await db.execute(
            select(Branch).where(Branch.name == req.branch_name, Branch.status == "active")
        )
        br = br_result.scalar_one_or_none()
        if br:
            branch_id = br.id

    # 6자리 고유 등록코드 생성 (#000000 형식) — 중복 체크 포함
    code = await create_unique_registration_code(db)

    # ============================================================
    # 🚨 보안: 공개 회원가입 허용 역할 화이트리스트 (2026-09-14)
    # ------------------------------------------------------------
    # 이전에는 클라이언트가 보낸 role 을 그대로 저장해서
    # 누구나 {"role":"super_admin"} 으로 본사 관리자 계정을
    # 자가 생성할 수 있었다 (권한 상승 취약점).
    #
    # 정책:
    #   · student / parent          → 허용 (원장 승인 필요)
    #   · director / branch_admin   → 허용 (단, pending.db 에 저장되어
    #                                 본사 승인 전까지 로그인 불가)
    #   · super_admin / admin 등    → 🚫 차단, student 로 강등
    # ============================================================
    PUBLIC_SIGNUP_ROLES = {"student", "parent", "director", "branch_admin", "branch_manager"}
    PRIVILEGED_ROLES = {"super_admin", "admin", "hq_admin", "root", "staff"}

    _requested = (req.role or "student").strip().lower()
    if _requested in PRIVILEGED_ROLES:
        # 관리자급 역할 자가 등록 시도 → 차단하고 student 로 강등
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "🚨 권한 상승 시도 차단 — username=%s requested_role=%s",
            getattr(req, "username", "?"), _requested,
        )
        req.role = "student"
    elif _requested not in PUBLIC_SIGNUP_ROLES:
        # 알 수 없는 역할 → student 로 안전하게 강등
        req.role = "student"
    else:
        req.role = _requested

    # ============================================================
    # 승인 정책: branch_admin/director → pending.db 저장 (본사 승인)
    #            student/parent → 메인 DB 저장 (원장 승인 필요)
    # ============================================================
    roles_need_hq_approval = {"branch_admin", "branch_manager", "director"}

    if req.role in roles_need_hq_approval:
        # --- 승인 전: pending.db에 저장 ---
        from app.pending_db import add_pending_user
        pending_id = add_pending_user(
            username=req.username,
            email=req.email,
            password_hash=hash_password(req.password),
            name=req.name,
            phone=req.phone or '',
            role=req.role,
            branch_id=branch_id,
            director_id=user_director_id,
            registration_code=code,
            academy_type=getattr(req, 'academy_type', ''),
            region=getattr(req, 'region', ''),
            branch_name=getattr(req, 'branch_name', '') or req.name,
        )
        return ApiResponse(
            message="회원가입이 완료되었습니다. 본사 관리자의 승인 후 이용 가능합니다.",
            data={
                "id": pending_id,
                "username": req.username,
                "name": req.name,
                "role": req.role,
                "registration_code": code,
                "is_active": False,
                "pending": True,
            }
        )

    # --- student/parent: 메인 DB에 저장 (원장 승인 필요) ---
    roles_require_approval = {"student", "parent"}
    is_active = req.role not in roles_require_approval

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        phone=req.phone,
        role=req.role,
        branch_id=branch_id,
        director_id=user_director_id,
        registration_code=code,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    msg = "회원가입이 완료되었습니다."
    if not is_active:
        msg = "회원가입이 완료되었습니다. 원장님의 승인 후 이용 가능합니다."

    return ApiResponse(
        message=msg,
        data={
            "id": user.id, "username": user.username, "name": user.name,
            "role": user.role, "registration_code": user.registration_code,
            "is_active": user.is_active,
        }
    )


# ============================================================
# 승인 관련 API
# ============================================================

from pydantic import BaseModel
from typing import List, Optional


class ApproveUserRequest(BaseModel):
    user_id: int
    approve: bool = True  # True=승인, False=거절/비활성화


@router.post("/approve")
async def approve_user(
    req: ApproveUserRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """사용자 승인/거절
    - 본사(super_admin): 모든 역할 승인 가능 (pending.db의 branch_admin/director 포함)
    - 원장(director): 자기 지사(branch_id)의 학생(student), 학부모(parent)만 승인 가능
    """
    current_role = current_user["role"]

    # 본사(super_admin) 처리
    if current_role == "super_admin":
        from app.models import Branch, Academy
        from app.pending_db import approve_pending_user

        # 먼저 pending.db에서 조회
        pending_data = approve_pending_user(req.user_id)
        if pending_data:
            # pending.db -> 메인 DB users로 이동
            exist = await db.execute(select(User).where(
                (User.username == pending_data["username"]) | (User.email == pending_data["email"])
            ))
            if exist.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="이미 존재하는 이메일입니다.")

            user = User(
                username=pending_data["username"],
                email=pending_data["email"],
                password_hash=pending_data["password_hash"],
                name=pending_data["name"],
                phone=pending_data.get("phone", "") or "",
                role=pending_data["role"],
                branch_id=pending_data.get("branch_id"),
                director_id=pending_data.get("director_id"),
                registration_code=pending_data.get("registration_code", "") or "",
                is_active=True,
                approved_by=current_user["id"],
            )
            # 가입일자 보존: pending 신청일(requested_at)을 created_at으로 승계.
            # 미지정 시 server_default=now()가 '승인 시각'을 가입일로 저장하는 버그가 있었음.
            _req_at = pending_data.get("requested_at")
            if _req_at:
                try:
                    from datetime import datetime as _dt
                    user.created_at = _dt.fromisoformat(str(_req_at))
                except Exception:
                    pass
            db.add(user)
            await db.flush()
            await db.refresh(user)

            # branch_admin 승인 시 branches 자동 생성
            if user.role == "branch_admin" and not user.branch_id:
                import secrets, string
                code = "".join(secrets.choice(string.digits) for _ in range(6))
                new_branch = Branch(
                    name=user.name, code="#" + code,
                    address=user.phone or "", phone=user.phone or "",
                    status="active", branch_type="franchise", is_approved=True,
                )
                db.add(new_branch)
                await db.flush()
                user.branch_id = new_branch.id

            await db.commit()
            await db.refresh(user)

            # pending 쪽에 승인일시 기록 (approved_at) — 감사 추적용
            try:
                from app.pending_db import mark_pending_approved
                mark_pending_approved(req.user_id)
            except Exception:
                pass

            return ApiResponse(
                message=f"{user.name}({user.username}) 님의 계정이 승인되었습니다.",
                data={"id": user.id, "username": user.username, "name": user.name,
                      "role": user.role, "is_active": True,
                      "approved_by": current_user["id"]}
            )

        # pending.db에 없으면 메인 DB에서 처리 (기존 데이터 호환)
        result = await db.execute(select(User).where(User.id == req.user_id))
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

        if req.approve:
            target.is_active = True
            target.approved_by = current_user["id"]
            if target.role == "branch_admin" and not target.branch_id:
                import secrets, string
                code = "".join(secrets.choice(string.digits) for _ in range(6))
                new_branch = Branch(
                    name=target.name, code="#" + code,
                    address=target.phone or "", phone=target.phone or "",
                    status="active", branch_type="franchise", is_approved=True,
                )
                db.add(new_branch)
                await db.flush()
                target.branch_id = new_branch.id
            action = "승인"
        else:
            target.is_active = False
            target.approved_by = None
            action = "거절"
        await db.commit()
        await db.refresh(target)
        return ApiResponse(
            message=f"{target.name}({target.username}) 님의 계정이 {action}되었습니다.",
            data={"id": target.id, "username": target.username, "name": target.name,
                   "role": target.role, "is_active": target.is_active,
                   "approved_by": target.approved_by}
        )

    # 원장(director)이 student/parent 승인
    elif current_role == "director":
        result = await db.execute(select(User).where(User.id == req.user_id))
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
        director_branch = current_user.get("branch_id")
        if not director_branch:
            raise HTTPException(status_code=403, detail="원장님 계정에 소속된 지사가 없습니다. 본사에 문의하세요.")
        if target.branch_id != director_branch:
            raise HTTPException(status_code=403, detail="다른 지사의 계정은 승인할 수 없습니다.")
        if target.role not in {"student", "parent"}:
            raise HTTPException(status_code=403, detail="원장은 학생/학부모만 승인할 수 있습니다.")
        if req.approve:
            target.is_active = True
            target.approved_by = current_user["id"]
            target.director_id = current_user["id"]
            action = "승인"
        else:
            target.is_active = False
            target.approved_by = None
            action = "거절"
        await db.commit()
        await db.refresh(target)
        return ApiResponse(
            message=f"{target.name}({target.username}) 님의 계정이 {action}되었습니다.",
            data={"id": target.id, "username": target.username, "name": target.name,
                   "role": target.role, "is_active": target.is_active,
                   "approved_by": target.approved_by}
        )

    else:
        raise HTTPException(status_code=403, detail="승인 권한이 없습니다.")


@router.get("/pending-approvals")
async def get_pending_approvals(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """승인 대기 중인 사용자 목록 조회
    - 본사(super_admin): 모든 역할 (메인 DB 미승인 + pending.db)
    - 원장(director): 자기 지사 학생/학부모만
    """
    current_role = current_user["role"]
    current_branch = current_user.get("branch_id")

    users = []

    if current_role == "super_admin":
        # 본사: 메인 DB 미승인 사용자
        result = await db.execute(
            select(User).where(
                User.is_active == False,
                User.withdrawn_at.is_(None),  # 탈퇴생 제외 — 승인 대기만
            ).order_by(User.created_at.desc())
        )
        users = result.scalars().all()

        # + pending.db의 승인 대기 사용자
        from app.pending_db import get_all_pending_users
        pending_users = get_all_pending_users(status="pending")
        for pu in pending_users:
            users.append(PendingUserProxy(pu))

    elif current_role == "director" and current_branch:
        # 원장: 자기 지사 + 자기 원장코드로 등록된 학생/학부모만
        target_roles = ["student", "parent"]
        result = await db.execute(
            select(User).where(
                User.role.in_(target_roles),
                User.branch_id == current_branch,
                User.director_id == current_user["id"],
                User.is_active == False,
                User.withdrawn_at.is_(None),  # 탈퇴생 제외 — 승인 대기만
            ).order_by(User.created_at.desc())
        )
        users = result.scalars().all()
    else:
        raise HTTPException(status_code=403, detail="조회 권한이 없습니다.")

    return ApiResponse(data=[
        {
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "email": u.email,
            "phone": u.phone,
            "role": u.role,
            "branch_id": u.branch_id,
            "registration_code": u.registration_code,
            "created_at": str(getattr(u, 'requested_at', getattr(u, 'created_at', ''))),
            "pending": getattr(u, 'pending', False),
        }
        for u in users
    ])


class PendingUserProxy:
    """pending.db의 사용자를 메인 DB User 객체처럼 사용하기 위한 프록시"""
    def __init__(self, data):
        self.id = data["id"]
        self.username = data["username"]
        self.name = data["name"]
        self.email = data["email"]
        self.phone = data.get("phone", "")
        self.role = data["role"]
        self.branch_id = data.get("branch_id")
        self.registration_code = data.get("registration_code", "")
        self.is_active = False
        self.created_at = data.get("requested_at", "")
        self.pending = True


# ══════════════════════════════════════════════════════════════════
#  관리자 2단계 인증 (TOTP) 관리 — 2026-09-14
# --------------------------------------------------------------
#  · /auth/totp/setup    : 시크릿 + otpauth URI 발급 (아직 비활성)
#  · /auth/totp/enable   : 코드 확인 후 활성화 + 복구코드 발급
#  · /auth/totp/disable  : 비밀번호 확인 후 해제
#  · /auth/totp/status   : 현재 상태 조회
#  대상 역할: super_admin / admin / hq_admin
# ══════════════════════════════════════════════════════════════════

MFA_ROLES = ("super_admin", "admin", "hq_admin")


def _mfa_user(current_user: dict):
    if current_user.get("role") not in MFA_ROLES:
        raise HTTPException(status_code=403, detail="관리자만 2단계 인증을 사용할 수 있습니다.")


@router.get("/totp/status")
async def totp_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """2단계 인증 상태 조회"""
    user = (await db.execute(
        select(User).where(User.id == int(current_user["id"]))
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    _codes = []
    if user.totp_recovery:
        try:
            _codes = json.loads(user.totp_recovery)
        except Exception:
            _codes = []
    return ApiResponse(data={
        "role": user.role,
        "eligible": user.role in MFA_ROLES,
        "enabled": bool(user.totp_enabled),
        "confirmed_at": str(user.totp_confirmed_at) if user.totp_confirmed_at else None,
        "recovery_remaining": len(_codes),
    })


@router.post("/totp/setup")
async def totp_setup(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """2단계 인증 등록 시작 — 시크릿과 otpauth URI 반환 (아직 미활성)

    ⚠️ totp_enabled 는 아직 0 이다. /totp/enable 에서 코드를 확인해야 켜진다.
    """
    _mfa_user(current_user)
    user = (await db.execute(
        select(User).where(User.id == int(current_user["id"]))
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    secret = _totp.generate_secret()
    user.totp_secret = secret
    user.totp_enabled = False   # 확인 전까지는 비활성
    await db.commit()

    uri = _totp.provisioning_uri(secret, user.username)
    return ApiResponse(data={
        "secret": secret,
        "otpauth_uri": uri,
        "issuer": "Nubida Platform",
        "account": user.username,
        "digits": _totp.DIGITS,
        "period": _totp.PERIOD,
        "message": "인증 앱에서 QR 또는 시크릿을 등록한 뒤, 표시되는 6자리 코드로 활성화하세요.",
    })


@router.post("/totp/enable")
async def totp_enable(
    req: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """코드 확인 후 2단계 인증 활성화 + 복구코드 발급 (1회만 표시)"""
    _mfa_user(current_user)
    code = str(req.get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=400, detail="인증 코드를 입력해 주세요.")

    user = (await db.execute(
        select(User).where(User.id == int(current_user["id"]))
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="먼저 2단계 인증 등록을 시작해 주세요.")
    if not _totp.verify_totp(user.totp_secret, code):
        raise HTTPException(status_code=401, detail="인증 코드가 올바르지 않습니다. 시간을 확인해 주세요.")

    codes = _totp.generate_recovery_codes(8)
    user.totp_enabled = True
    user.totp_recovery = json.dumps([_totp.hash_recovery_code(c) for c in codes], ensure_ascii=False)
    from datetime import datetime as _dt
    user.totp_confirmed_at = _dt.utcnow()
    await db.commit()

    return ApiResponse(data={
        "enabled": True,
        "recovery_codes": codes,
        "message": "2단계 인증이 활성화되었습니다. 복구코드를 안전한 곳에 보관하세요. 이 화면을 닫으면 다시 볼 수 없습니다.",
    })


@router.post("/totp/disable")
async def totp_disable(
    req: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """비밀번호 확인 후 2단계 인증 해제"""
    _mfa_user(current_user)
    pw = str(req.get("password", ""))
    if not pw:
        raise HTTPException(status_code=400, detail="비밀번호를 입력해 주세요.")

    user = (await db.execute(
        select(User).where(User.id == int(current_user["id"]))
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if not verify_password(pw, user.password_hash):
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery = None
    user.totp_confirmed_at = None
    await db.commit()
    return ApiResponse(data={"enabled": False, "message": "2단계 인증이 해제되었습니다."})
