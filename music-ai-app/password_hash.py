"""
Nubida 공통 비밀번호 해시 유틸리티 (외부 패키지 불필요 — 표준 라이브러리만)

형식: pbkdf2_sha256$<iterations>$<base64_salt>$<base64_hash>
  - salt: 16바이트 난수 (매번 새로 생성 → 같은 비밀번호도 다른 해시)
  - iterations: 260,000 (OWASP 2023 권장 SHA-256 기준)
  - 하위 호환: 기존 평문/SHA-256 해시도 검증 가능 → 로그인 시 자동 업그레이드
"""
import hashlib
import hmac
import os
import base64

ITERATIONS = 260_000
ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """새 비밀번호를 PBKDF2 해시로 변환 (매번 새 salt)"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "{}${}${}${}".format(
        ALGO,
        ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(plain: str, stored: str) -> bool:
    """저장된 해시와 평문 비교 — PBKDF2 / SHA-256 / 평문 모두 지원"""
    if not stored:
        return False
    stored = str(stored)

    # 1) PBKDF2 형식
    if stored.startswith(ALGO + "$"):
        try:
            _, iters, salt_b64, hash_b64 = stored.split("$", 3)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, int(iters))
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False

    # 2) 기존 SHA-256 (64자 hex, salt 없음) — 로그인 성공 시 자동 업그레이드 대상
    if len(stored) == 64:
        try:
            int(stored, 16)
            legacy = hashlib.sha256(plain.encode("utf-8")).hexdigest()
            return hmac.compare_digest(legacy, stored)
        except ValueError:
            pass

    # 3) 평문 (기존 데이터) — 로그인 성공 시 자동 업그레이드 대상
    return hmac.compare_digest(plain, stored)


def needs_rehash(stored: str) -> bool:
    """이 해시가 업그레이드 필요한지 (PBKDF2 아니면 True)"""
    return not str(stored or "").startswith(ALGO + "$")
