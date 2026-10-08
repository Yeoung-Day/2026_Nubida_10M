"""TOTP (RFC 6238) — 외부 패키지 없이 stdlib 만으로 구현

배경: 누비다플랫폼 컨테이너에 pyotp/qrcode 미설치 + 인터넷 없음
목적: 관리자(super_admin/admin/hq_admin) 2단계 인증

지원:
  · 시크릿 생성 (base32, 160bit = RFC 권장)
  · TOTP 코드 생성/검증 (30초 주기, 6자리, ±1 윈도우 허용)
  · otpauth:// URI (Google Authenticator / Authy 등록용)
  · 복구코드(백업코드) 생성/해시
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# ── RFC 6238 권장 파라미터 ──
DIGITS = 6
PERIOD = 30
ALGORITHM = "sha1"
WINDOW = 1          # ±1 스텝 허용 (시간 오차 감안, 총 90초 유효)


def generate_secret(length_bytes: int = 20) -> str:
    """base32 시크릿 생성 (20바이트 = 160bit, RFC 4226 권장)"""
    raw = secrets.token_bytes(length_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226 HOTP"""
    # base32 패딩 복원
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def totp_now(secret_b32: str, at: float = None, digits: int = DIGITS) -> str:
    """현재 시각의 TOTP 코드"""
    t = time.time() if at is None else at
    return _hotp(secret_b32, int(t) // PERIOD, digits)


def verify_totp(secret_b32: str, code: str, window: int = WINDOW, at: float = None) -> bool:
    """TOTP 검증 — ±window 스텝 허용 (기본 ±30초)"""
    if not code:
        return False
    code = str(code).strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    t = time.time() if at is None else at
    counter = int(t) // PERIOD
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + offset), code):
            return True
    return False


def provisioning_uri(secret_b32: str, username: str, issuer: str = "Nubida Platform") -> str:
    """otpauth:// URI — QR 코드/수동입력용"""
    label = quote(f"{issuer}:{username}")
    params = f"secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(count: int = 8) -> list:
    """복구코드 생성 (기기 분실 대비) — XXXX-XXXX 형식"""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(5).upper()   # 10 hex chars
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """복구코드 저장용 해시 (SHA-256, 대소문자 무시)"""
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def verify_recovery_code(code: str, stored_hashes: list) -> bool:
    """복구코드 검증 (사용된 코드는 호출측에서 목록에서 제거)"""
    h = hash_recovery_code(code)
    return any(hmac.compare_digest(h, s) for s in (stored_hashes or []))


if __name__ == "__main__":
    print("=== 자체 검증 ===")
    secret = generate_secret()
    print("시크릿:", secret, f"({len(secret)}자)")
    print("현재 코드:", totp_now(secret))
    print("URI:", provisioning_uri(secret, "admin"))

    # RFC 6238 공식 테스트 벡터 (SHA1, secret="12345678901234567890")
    rfc_secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    vectors = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
               (1234567890, "89005924"), (2000000000, "69279037")]
    ok = True
    for ts, expect in vectors:
        got = _hotp(rfc_secret, ts // 30, 8)
        ok = ok and (got == expect)
    print(f"RFC 6238 벡터(8자리): {'✅ 전부 일치' if ok else '❌ 불일치'}")

    # 검증 로직
    code = totp_now(secret)
    print("검증(정답):", verify_totp(secret, code))
    print("검증(오답):", verify_totp(secret, "000000"))
    print("검증(이전스텝 ±30s):", verify_totp(secret, totp_now(secret, time.time() - 30)))
    print("검증(범위밖 -90s):", verify_totp(secret, totp_now(secret, time.time() - 90)))

    # 복구코드
    codes = generate_recovery_codes()
    print("복구코드 샘플:", codes[0])
    hs = [hash_recovery_code(c) for c in codes]
    print("복구코드 검증:", verify_recovery_code(codes[0], hs), "/ 오답:", verify_recovery_code("XXXX-XXXX", hs))

    # 서로 다른 시크릿은 다른 코드
    s2 = generate_secret()
    print("시크릿 다름 확인:", totp_now(secret) != totp_now(s2) or "⏳동시생성(정상가능)")
    print()
    print("✅ totp.py 준비 완료")
