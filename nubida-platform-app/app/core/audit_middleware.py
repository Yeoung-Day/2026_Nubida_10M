"""
🔍 감사 로깅 미들웨어 — API 요청을 AccessLog 테이블에 기록
POST/PUT/PATCH/DELETE 요청만 기록 (GET 제외),
/api/v1/auth/login 및 /api/health 는 기록에서 제외.
"""
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.database import async_session
from app.models import AccessLog


# 기록에서 제외할 경로 패턴
SKIP_PATHS = {"/api/v1/auth/login", "/api/health"}

# 기록할 HTTP 메서드 (쓰기 작업만)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    """API 요청을 감사 로그에 기록하는 미들웨어"""

    async def dispatch(self, request: Request, call_next):
        # WebSocket Upgrade 요청은 미들웨어를 통과시킴 (BaseHTTPMiddleware 버그 우회)
        upgrade = request.headers.get("upgrade", "").lower()
        connection = request.headers.get("connection", "").lower()
        if upgrade == "websocket" or "upgrade" in connection:
            return await call_next(request)

        # GET 요청은 건너뜀
        if request.method not in WRITE_METHODS:
            return await call_next(request)

        # 제외 경로 건너뜀
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # /api/v1/* 경로만 기록
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        # 응답 처리
        response = await call_next(request)

        # 백그라운드에서 DB 기록 (비동기, 논블로킹)
        try:
            # `request.state` 에서 user 정보 추출 (인증 미들웨어가 주입)
            user_id = None
            if hasattr(request.state, "user") and request.state.user:
                user_id = request.state.user.get("id")

            # client IP
            ip_address = request.client.host if request.client else "unknown"

            # 요청 상세 정보
            details = {
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "status_code": response.status_code,
            }

            # 비동기 세션에서 로그 저장
            async with async_session() as session:
                log_entry = AccessLog(
                    user_id=user_id,
                    action=f"{request.method} {request.url.path}",
                    ip_address=ip_address,
                    details=details,
                )
                session.add(log_entry)
                await session.commit()
        except Exception:
            # 로깅 실패는 무시 — 요청 자체에 영향 주지 않음
            pass

        return response
