from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import hashlib
import base64
import secrets
import hmac

# ---------------------------------------------------------------------------
# 비밀번호 해시 (PBKDF2-HMAC-SHA256)
#   형식: pbkdf2_sha256$<iterations>$<b64_salt>$<b64_hash>
#   - 무염 SHA-256(기존) 및 평문도 검증 가능 → 기존 사용자 로그인 유지
#   - 로그인 성공 시 PBKDF2 로 자동 교체(needs_rehash)
# ---------------------------------------------------------------------------
_PBKDF2_ITERATIONS = 260_000
_PBKDF2_PREFIX = "pbkdf2_sha256$"

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

security = HTTPBearer()


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 으로 비밀번호를 해시 (매번 새 salt)."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "{}${}${}${}".format(
        "pbkdf2_sha256",
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )

def get_password_hash(password: str) -> str:
    """hash_password 별칭"""
    return hash_password(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """PBKDF2 / 기존 무염 SHA-256 / 평문 모두 검증 (하위 호환)."""
    if not hashed_password:
        return False
    stored = hashed_password.strip()

    # 1) PBKDF2
    if stored.startswith(_PBKDF2_PREFIX):
        try:
            _, iters, b64salt, b64hash = stored.split("$")
            salt = base64.b64decode(b64salt)
            expected = base64.b64decode(b64hash)
            dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, int(iters))
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False

    # 2) 기존 무염 SHA-256 (64자리 hex)
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        legacy = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored)

    # 3) 평문 (마이그레이션 중 임시)
    return hmac.compare_digest(stored, plain_password)


def needs_rehash(hashed_password: str) -> bool:
    """저장된 해시가 구형(무염 SHA-256/평문)이면 True → 로그인 시 자동 교체."""
    if not hashed_password:
        return False
    return not hashed_password.strip().startswith(_PBKDF2_PREFIX)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """현재 인증된 사용자 정보 반환 (이중로그인 방지 — login_version 검증 포함)"""
    payload = decode_token(credentials.credentials)
    user_id: int = payload.get("sub")
    role: str = payload.get("role")
    if user_id is None or role is None:
        raise HTTPException(status_code=401, detail="토큰 정보가 올바르지 않습니다.")

    # ── 이중로그인 방지: JWT의 login_version과 DB 최신 버전 비교 ──
    token_ver = payload.get("login_version")
    if token_ver is not None:
        try:
            from app.core.database import async_session
            from app.models import User as _User
            from sqlalchemy import select as _select
            async with async_session() as _db:
                row = (await _db.execute(
                    _select(_User.login_version).where(_User.id == int(user_id))
                )).scalar_one_or_none()
            if row is None:
                raise HTTPException(
                    status_code=401,
                    detail="계정 정보를 찾을 수 없습니다. 다시 로그인해 주세요.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if int(row) != int(token_ver):
                raise HTTPException(
                    status_code=401,
                    detail="다른 기기에서 로그인되어 자동 로그아웃되었습니다. 다시 로그인해 주세요.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception:
            pass

    return {"id": int(user_id), "role": role, "username": payload.get("username"), "name": payload.get("name", ""), "branch_id": payload.get("branch_id", 0)}


def require_role(*roles: str):
    """특정 역할만 접근 허용"""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="접근 권한이 없습니다."
            )
        return current_user
    return role_checker

def generate_registration_code() -> str:
    """#000000 형식의 6자리 고유 등록코드 생성"""
    import random as _random
    return f"#{_random.randint(0, 999999):06d}"


async def create_unique_registration_code(db) -> str:
    """#000000 형식의 6자리 고유 등록코드 생성 — DB 중복 체크 후 유일한 코드 반환"""
    from sqlalchemy import select
    from app.models import User
    import random as _random

    for _ in range(50):  # 최대 50회 재시도 (사실상 충돌 불가)
        code = f"#{_random.randint(0, 999999):06d}"
        existing = await db.execute(select(User).where(User.registration_code == code))
        if not existing.scalar_one_or_none():
            return code

    # 극히 드문 경우 — 모든 코드가 사용됨 (1M명 이상)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="사용 가능한 등록코드를 생성할 수 없습니다. 모든 코드가 소진되었습니다."
    )
