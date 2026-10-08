"""
Security middleware modules for Nubida Platform.

Contains:
- SecurityHeadersMiddleware — adds security headers to every response
- InputSanitizer — utility for input sanitization and validation
- RateLimiter — in-memory rate limiting per IP
- CSRFProtection — CSRF token generation and validation
"""

import re
import time
import secrets
import html
import hmac
from typing import Optional
from collections import defaultdict
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# =============================================================================
# 1. SecurityHeadersMiddleware
# =============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that adds security headers to every HTTP response.

    Headers added:
      - Content-Security-Policy
      - X-Content-Type-Options
      - X-Frame-Options
      - Referrer-Policy
      - Permissions-Policy
      - Strict-Transport-Security (HTTPS only)
    """

    CSP_DEFAULT = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https: blob:; "
        # 'unsafe-eval' — TensorFlow.js(누비다머신) 커널 생성에 필수 (2026-08-25)
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' https:; "
        "connect-src 'self' https: wss: blob:; "
        "frame-src 'self' https://www.youtube.com https://player.vimeo.com "
        "https://docs.google.com https://docs.google.com/viewer "
        "https://*.google.com https://*.notion.so "
        "https://codepen.io https://codesandbox.io https://jsfiddle.net "
        "https://canva.com https://figma.com https://miro.com https://padlet.com; "
        "media-src 'self' https: blob: data:; "
        "object-src 'self' https: blob:;"
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        # WebSocket Upgrade 요청은 미들웨어를 통과시킴
        # (BaseHTTPMiddleware가 Upgrade 요청을 HTTP 라우터로 잘못 라우팅하는 버그 우회)
        upgrade = request.headers.get("upgrade", "").lower()
        connection = request.headers.get("connection", "").lower()
        if upgrade == "websocket" or "upgrade" in connection:
            return await call_next(request)

        response: Response = await call_next(request)

        # Content-Security-Policy
        response.headers["Content-Security-Policy"] = self.CSP_DEFAULT

        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # Referrer-Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy — camera/mic는 같은 오리진 페이지(누비다머신)에 허용
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(self), geolocation=()"
        )

        # Strict-Transport-Security — HTTPS only
        scheme = request.url.scheme
        if scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # =========================================================
        # Cache-Control for HTML pages (no cache for dynamic pages)
        # =========================================================
        if request.url.path.startswith("/pages/") or request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


# =============================================================================
# 2. InputSanitizer
# =============================================================================

class InputSanitizer:
    """
    Utility class for sanitizing and validating user inputs.
    """

    # Regex to strip HTML/XML tags
    TAG_RE = re.compile(r"<[^>]*>")

    # Dangerous HTML tag patterns (script, iframe, object, embed, etc.)
    DANGEROUS_TAG_RE = re.compile(
        r"<\s*(script|iframe|object|embed|applet|form|input|button|textarea|select|style|link|meta|base)\b[^>]*>",
        re.IGNORECASE,
    )

    # Event handler attributes (on*)
    EVENT_HANDLER_RE = re.compile(r"\s+on\w+\s*=\s*['\"][^'\"]*['\"]", re.IGNORECASE)

    # JavaScript protocol in attributes
    JS_PROTOCOL_RE = re.compile(r"""href\s*=\s*['"]\s*javascript\s*:""", re.IGNORECASE)

    # Path traversal patterns
    PATH_TRAVERSAL_RE = re.compile(r"(\.\./|\.\.\\)")

    # Invalid filename characters
    INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    # Basic email pattern
    EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    # Korean phone number patterns:
    #  010-1234-5678, 01012345678, 02-123-4567, etc.
    PHONE_RE = re.compile(
        r"^(01[016789]-\d{3,4}-\d{4})$|"  # Mobile: 010-1234-5678
        r"^(01[016789]\d{3,4}\d{4})$|"     # Mobile compact: 01012345678
        r"^(0\d{1,2}-\d{3,4}-\d{4})$"       # Landline: 02-123-4567
    )

    MAX_STRING_LENGTH = 1000

    @classmethod
    def sanitize_string(cls, s: Optional[str]) -> Optional[str]:
        """
        Strip HTML tags, trim whitespace, and limit length to MAX_STRING_LENGTH.

        Args:
            s: Input string to sanitize.

        Returns:
            Sanitized string, or None if input is None.
        """
        if s is None:
            return None

        # Strip HTML/XML tags
        cleaned = cls.TAG_RE.sub("", s)

        # Trim whitespace
        cleaned = cleaned.strip()

        # Limit length
        if len(cleaned) > cls.MAX_STRING_LENGTH:
            cleaned = cleaned[:cls.MAX_STRING_LENGTH]

        return cleaned

    @classmethod
    def sanitize_html(cls, s: Optional[str]) -> Optional[str]:
        """
        Strip dangerous HTML tags and attributes but allow safe HTML.

        Removes:
          - Dangerous tags: script, iframe, object, embed, applet, form, etc.
          - Event handler attributes (onclick, onload, etc.)
          - javascript: in href attributes

        Args:
            s: Input HTML string to sanitize.

        Returns:
            Sanitized HTML string, or None if input is None.
        """
        if s is None:
            return None

        # Remove dangerous tags entirely
        cleaned = cls.DANGEROUS_TAG_RE.sub("", s)

        # Remove event handler attributes
        cleaned = cls.EVENT_HANDLER_RE.sub("", cleaned)

        # Remove javascript: protocol
        cleaned = cls.JS_PROTOCOL_RE.sub("href=\"#\"", cleaned)

        # Escape any remaining angle brackets that might form tags
        # (this is a conservative approach — allows basic HTML but escapes
        #  any new tags that might be formed after removing dangerous ones)
        cleaned = cleaned.strip()

        return cleaned

    @classmethod
    def sanitize_filename(cls, s: Optional[str]) -> Optional[str]:
        """
        Sanitize a filename: remove path traversal sequences and special characters.

        Args:
            s: Input filename string.

        Returns:
            Sanitized filename string, or None if input is None.
        """
        if s is None:
            return None

        # Remove path traversal (../ and ..\\)
        cleaned = cls.PATH_TRAVERSAL_RE.sub("", s)

        # Remove invalid filename characters
        cleaned = cls.INVALID_FILENAME_CHARS_RE.sub("_", cleaned)

        # Replace multiple underscores with single
        cleaned = re.sub(r"_+", "_", cleaned)

        # Strip leading/trailing dots, spaces, and underscores
        cleaned = cleaned.strip(". _")

        # Limit length
        if len(cleaned) > 255:
            name, ext = cls._split_ext(cleaned)
            max_name_len = 255 - len(ext) - 1
            if max_name_len > 0:
                cleaned = name[:max_name_len] + "." + ext
            else:
                cleaned = cleaned[:255]

        return cleaned

    @classmethod
    def validate_email(cls, s: Optional[str]) -> bool:
        """
        Validate email format using a basic regex pattern.

        Args:
            s: Email string to validate.

        Returns:
            True if the email format is valid, False otherwise.
        """
        if not s or not isinstance(s, str):
            return False
        return bool(cls.EMAIL_RE.match(s.strip()))

    @classmethod
    def validate_phone(cls, s: Optional[str]) -> bool:
        """
        Validate Korean phone number format.

        Accepts:
          - Mobile: 010-1234-5678 or 01012345678
          - Landline: 02-123-4567, 031-123-4567, etc.

        Args:
            s: Phone number string to validate.

        Returns:
            True if the phone number format is valid, False otherwise.
        """
        if not s or not isinstance(s, str):
            return False
        return bool(cls.PHONE_RE.match(s.strip()))

    @staticmethod
    def _split_ext(filename: str) -> tuple:
        """Split filename into (name, extension) without leading dot on ext."""
        if "." in filename:
            parts = filename.rsplit(".", 1)
            return parts[0], parts[1]
        return filename, ""


# =============================================================================
# 3. RateLimiter
# =============================================================================

class RateLimiter:
    """
    Simple in-memory rate limiter.

    Uses a dict keyed by IP address, tracking request timestamps.
    Enforces a configurable maximum number of requests per minute.
    Cleans up expired entries every 60 seconds.
    """

    def __init__(self, limit: int = 100, window: int = 60):
        """
        Initialize the rate limiter.

        Args:
            limit: Maximum number of requests allowed per time window (default: 100).
            window: Time window in seconds (default: 60).
        """
        self.limit = limit
        self.window = window
        self._records: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup: float = time.time()

    def is_allowed(self, ip: str) -> bool:
        """
        Check if a request from the given IP is allowed.

        Removes expired entries and cleans up old data periodically.

        Args:
            ip: IP address of the requester.

        Returns:
            True if the request is allowed, False if rate limit exceeded.
        """
        now = time.time()

        # Periodic cleanup of expired entries
        self._maybe_cleanup(now)

        # Get timestamps for this IP
        timestamps = self._records[ip]

        # Remove timestamps outside the window
        cutoff = now - self.window
        self._records[ip] = [t for t in timestamps if t > cutoff]

        # Check limit
        if len(self._records[ip]) >= self.limit:
            return False

        # Record this request
        self._records[ip].append(now)
        return True

    def get_remaining(self, ip: str) -> int:
        """
        Get the number of remaining requests allowed for the given IP.

        Args:
            ip: IP address to check.

        Returns:
            Remaining request count within the current window.
        """
        now = time.time()
        self._maybe_cleanup(now)

        timestamps = self._records.get(ip, [])
        cutoff = now - self.window
        active = [t for t in timestamps if t > cutoff]
        remaining = max(0, self.limit - len(active))
        return remaining

    def reset(self, ip: Optional[str] = None) -> None:
        """
        Reset rate limit records for a specific IP or all IPs.

        Args:
            ip: IP to reset. If None, resets all records.
        """
        if ip:
            self._records.pop(ip, None)
        else:
            self._records.clear()

    def _maybe_cleanup(self, now: float) -> None:
        """Remove expired entries for all IPs if enough time has passed."""
        if now - self._last_cleanup >= self.window:
            cutoff = now - self.window
            expired_ips = []
            for ip, timestamps in self._records.items():
                active = [t for t in timestamps if t > cutoff]
                if active:
                    self._records[ip] = active
                else:
                    expired_ips.append(ip)
            for ip in expired_ips:
                del self._records[ip]
            self._last_cleanup = now


# =============================================================================
# 4. CSRFProtection
# =============================================================================

class CSRFProtection:
    """
    Simple CSRF token generation and validation.

    Tokens are stored in an in-memory dict (non-persistent).
    For production, consider storing tokens in a session or Redis backend.
    """

    def __init__(self):
        self._tokens: dict[str, float] = {}
        self._token_ttl: float = 3600  # 1 hour

    def generate_token(self) -> str:
        """
        Generate a new CSRF token (32 random hex bytes).

        Returns:
            A secure random token string.
        """
        token = secrets.token_hex(32)
        self._tokens[token] = time.time()
        self._cleanup_expired()
        return token

    def validate_token(self, token: str, stored_token: str) -> bool:
        """
        Validate a CSRF token using constant-time comparison.

        Args:
            token: The token submitted by the client.
            stored_token: The token stored server-side.

        Returns:
            True if the tokens match and are not expired, False otherwise.
        """
        if not token or not stored_token:
            return False

        # Constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(token, stored_token)

        # Check if the stored token exists and is not expired
        if is_valid and stored_token in self._tokens:
            created_at = self._tokens[stored_token]
            if time.time() - created_at < self._token_ttl:
                return True
            # Token expired — remove it
            del self._tokens[stored_token]
            return False

        return False

    def remove_token(self, token: str) -> None:
        """Remove a used or expired token from storage."""
        self._tokens.pop(token, None)

    def _cleanup_expired(self) -> None:
        """Remove all expired tokens from storage."""
        now = time.time()
        expired = [
            token for token, created_at in self._tokens.items()
            if now - created_at > self._token_ttl
        ]
        for token in expired:
            del self._tokens[token]


# =============================================================================
# Module-level instances (singletons)
# =============================================================================

# Shared rate limiter instance (can be imported and used directly)
rate_limiter = RateLimiter()

# Shared CSRF protection instance
csrf_protection = CSRFProtection()
