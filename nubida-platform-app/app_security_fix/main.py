"""
누비다플랫폼 통합 공부방 교육 시스템 — FastAPI Application Entry Point
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.security_middleware import SecurityHeadersMiddleware, rate_limiter
from app.core.audit_middleware import AuditMiddleware

os.makedirs("/app/uploads/programs", exist_ok=True)
os.makedirs("/app/uploads/videos", exist_ok=True)
os.makedirs("/app/uploads/portfolio", exist_ok=True)
os.makedirs("/app/uploads/inquiries", exist_ok=True)
os.makedirs("/app/uploads/chat", exist_ok=True)

from app.api.v1 import auth, headquarters, branch, director, student, parent, platform, videos, payments, portfolio, portfolio_templates, classroom, audit, backup, sse, materials, maker_auth, maker_student, maker_admin, maker_superadmin, folders, member, chat, arduino, arduino_upload, push_notifications, excel_export, points, student_points, inquiries


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 시 실행"""
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Security headers middleware (applied before CORS)
app.add_middleware(SecurityHeadersMiddleware)

# Audit logging middleware (applied after security headers)
app.add_middleware(AuditMiddleware)

# CORS — restricted to configured origins (same-origin by default)
ALLOWED_ORIGINS = getattr(settings, "CORS_ORIGINS", None) or ["http://localhost:8000", "http://127.0.0.1:8000", "https://localhost", "capacitor://localhost", "http://localhost"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# API 라우터 등록 (우선순위: API > Static)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(headquarters.router, prefix="/api/v1")
app.include_router(branch.router, prefix="/api/v1")
app.include_router(director.router, prefix="/api/v1")
app.include_router(student.router, prefix="/api/v1")
app.include_router(parent.router, prefix="/api/v1")
app.include_router(platform.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")
app.include_router(portfolio_templates.router, prefix="/api/v1")
app.include_router(classroom.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(backup.router, prefix="/api/v1")
app.include_router(sse.router, prefix="/api/v1")
app.include_router(materials.router, prefix="/api/v1")
from app.api.v1.viewer import router as viewer_router
app.include_router(viewer_router, prefix="/api/v1")
app.include_router(maker_auth.router, prefix="/api/v1")
app.include_router(maker_student.router, prefix="/api/v1")
app.include_router(maker_admin.router, prefix="/api/v1")
app.include_router(maker_superadmin.router, prefix="/api/v1")
app.include_router(folders.router, prefix="/api/v1")
app.include_router(member.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(arduino.router, prefix="/api/v1")
app.include_router(arduino_upload.router, prefix="/api/v1")
app.include_router(push_notifications.router, prefix="/api/v1")
app.include_router(excel_export.router, prefix="/api/v1")
app.include_router(points.router, prefix="/api/v1")
app.include_router(student_points.router, prefix="/api/v1")
app.include_router(inquiries.router, prefix="/api/v1")


# ============================================================
# 글로벌 예외 핸들러 — 모든 예외를 JSON으로 반환
# ============================================================

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 Validation Error → 사용자 친화적 메시지로 변환"""
    errors = exc.errors()
    friendly_messages = []
    for err in errors:
        field = ".".join(str(loc) for loc in err.get("loc", [])) if err.get("loc") else ""
        msg = err.get("msg", "")
        if "password" in field.lower() and "min_length" in msg:
            friendly_messages.append("비밀번호는 6자 이상이어야 합니다.")
        elif "email" in field.lower() and "email" in msg.lower():
            friendly_messages.append("올바른 이메일 형식이 아닙니다.")
        elif "username" in field.lower() and "min_length" in msg:
            friendly_messages.append("아이디는 6자 이상이어야 합니다.")
        elif "min_length" in msg:
            # Extract the minimum length
            import re
            match = re.search(r'(\d+)', msg)
            min_len = match.group(1) if match else ""
            friendly_messages.append(f"{field}은(는) 최소 {min_len}자 이상이어야 합니다.")
        else:
            friendly_messages.append(msg)
    
    detail = " ".join(friendly_messages) if friendly_messages else "입력값이 올바르지 않습니다."
    return JSONResponse(
        status_code=422,
        content={"status": "error", "detail": detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """미처리 예외를 JSON으로 반환 (HTML/텍스트 대신)"""
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": f"Internal Server Error: {str(exc)}"},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    """500 오류를 JSON으로 반환"""
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Internal Server Error: 처리 중 오류가 발생했습니다."},
    )


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}

# SECURITY: /api/debug endpoint removed — it echoed full request headers,
# including auth tokens, to any unauthenticated caller.
# @app.api_route("/api/debug", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
# async def debug_request(request: Request):
#     """Debug: echo request details"""
#     body = await request.body()
#     return JSONResponse({
#         "method": request.method,
#         "path": request.url.path,
#         "headers": dict(request.headers),
#         "query": dict(request.query_params),
#         "body_length": len(body),
#         "body_preview": body[:200].decode("utf-8", errors="replace"),
#         "client": str(request.client),
#     })


# ============================================================
# 프론트엔드 정적 파일 서빙 (페이지별 독립구동)
# API 라우트가 우선, 매칭 안 되면 정적 파일 반환
# ============================================================

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIR_ASSET = FRONTEND_DIR / "common" / "assets"
FRONTEND_DIR_PAGES = FRONTEND_DIR / "pages"
UPLOADS_DIR = Path("/app/uploads")


# ============================================================
# WebSocket 라우트 직접 등록
# (include_router + @router.websocket 조합은 FastAPI에서
#  WebSocket Upgrade 요청을 catch-all 라우트가 가로채는 문제가 있어
#  app 레벨에서 직접 등록)
# ============================================================
from fastapi import WebSocket, Query
from app.core.database import get_db as ws_get_db


@app.websocket("/api/v1/chat/ws/{room_id}")
async def chat_websocket_route(
    websocket: WebSocket,
    room_id: int,
    token: str = Query(...),
    db=Depends(ws_get_db),
):
    from app.api.v1.chat import websocket_endpoint
    await websocket_endpoint(websocket, room_id, token, db)


# SECURITY: /ws-test test WebSocket endpoint removed.
# @app.websocket("/ws-test")
# async def ws_test(websocket: WebSocket):
#     await websocket.accept()
#     await websocket.send_text('{"type":"system","data":{"content":"WebSocket 테스트 연결 성공!"}}')
#     await websocket.close()


# ============================================================
# 루트 경로 — 랜딩 페이지 HTML
# ============================================================


@app.get("/")
async def serve_root():
    index_path = FRONTEND_DIR_PAGES / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path))
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


from fastapi.staticfiles import StaticFiles

# Static file serving - mount multiple directories
# API routes take priority over static files
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/uploads/portfolio", StaticFiles(directory=str(UPLOADS_DIR / "portfolio")), name="uploads_portfolio")
app.mount("/common", StaticFiles(directory=str(FRONTEND_DIR / "common")), name="common")
app.mount("/pages", StaticFiles(directory=str(FRONTEND_DIR_PAGES), html=True), name="pages")
app.mount("/lib", StaticFiles(directory=str(FRONTEND_DIR / "lib")), name="lib")
app.mount("/icons", StaticFiles(directory=str(FRONTEND_DIR / "icons")), name="icons")

# Mount headquarters pages directly under /headquarters for proper relative path resolution
HEADQUARTERS_PAGES = FRONTEND_DIR_PAGES / "headquarters"
if HEADQUARTERS_PAGES.is_dir():
    app.mount("/headquarters", StaticFiles(directory=str(HEADQUARTERS_PAGES), html=True), name="headquarters_pages")

# Root-level page redirects: /login.html -> /pages/login.html, etc.
ROOT_PAGES = ["login.html", "register.html", "find-id.html", "find-password.html", "index.html"]
for _page in ROOT_PAGES:
    _src = FRONTEND_DIR_PAGES / _page
    if _src.is_file():
        @app.get(f"/{_page}")
        async def _serve_root_page(page=_page, src=_src):
            return FileResponse(str(src))

# ============================================================
# SEO 파일 라우트 — sitemap.xml, robots.txt, rss.xml
# ============================================================

@app.get("/sitemap.xml", include_in_schema=False)
async def serve_sitemap():
    _f = FRONTEND_DIR / "sitemap.xml"
    if _f.is_file():
        return Response(content=_f.read_bytes(), media_type="application/xml")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/robots.txt", include_in_schema=False)
async def serve_robots():
    _f = FRONTEND_DIR / "robots.txt"
    if _f.is_file():
        return Response(content=_f.read_bytes(), media_type="text/plain")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/rss.xml", include_in_schema=False)
async def serve_rss():
    _f = FRONTEND_DIR / "rss.xml"
    if _f.is_file():
        return Response(content=_f.read_bytes(), media_type="application/rss+xml")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


# Service worker - special path
from fastapi.responses import FileResponse


@app.get("/service-worker.js")
async def serve_sw():
    sw_path = FRONTEND_DIR / "service-worker.js"
    if sw_path.is_file():
        return FileResponse(str(sw_path), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/manifest.json")
async def serve_manifest():
    m_path = FRONTEND_DIR / "manifest.json"
    if m_path.is_file():
        return FileResponse(str(m_path))
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/favicon.ico")
async def serve_favicon():
    f_path = FRONTEND_DIR / "favicon.ico"
    if f_path.is_file():
        return FileResponse(str(f_path))
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


# ============================================================
# SEO 메타태그 주입 — 모든 HTML 페이지 <head>에 네이버/구글 서치어드바이저 코드 삽입
# ============================================================
from fastapi.responses import Response
import json as _json
from sqlalchemy import text as _sa_text


async def _load_seo_meta_tags() -> str:
    """DB(app_settings + seo)에서 네이버/구글 검색인증 코드를 읽어 메타태그 생성."""
    try:
        from app.core.database import async_session
        async with async_session() as session:
            try:
                row = (await session.execute(
                    _sa_text("SELECT `value` FROM app_settings WHERE `key` = 'seo' LIMIT 1")
                )).fetchone()
            except Exception:
                row = None
        if row and row[0]:
            _val = row[0]
            d = _json.loads(_val) if isinstance(_val, (str, bytes)) else _val
            if not isinstance(d, dict):
                d = {}
            tags = ""
            naver = (d.get("naver_search_code") or "").strip()
            google = (d.get("google_search_code") or "").strip()
            # 네이버 인증코드에서 meta 태그 부분을 제거하고 실제 코드만 추출
            # DB 값: "meta name=naver-site-verification content=44388... /" 형식 — 코드만 추출
            import re as _re
            _m = _re.search(r'content[=:"\'\s]+([a-zA-Z0-9]+)', naver)
            if _m:
                naver = _m.group(1)
            _mg = _re.search(r'content[=:"\'\s]+([a-zA-Z0-9]+)', google)
            if _mg:
                google = _mg.group(1)

            if naver:
                tags += f'<meta name="naver-site-verification" content="{naver}">\n'
            if google:
                tags += f'<meta name="google-site-verification" content="{google}">\n'
            return tags
    except Exception as _e:
        print(f"[SEO] meta 로드 오류: {_e}")
    return ""


@app.middleware("http")
async def inject_seo_meta(request: Request, call_next):
    response = await call_next(request)
    try:
        ct = response.headers.get("content-type", "")
        # .html 또는 / 로 끝나는 경로(메인 페이지) 모두 처리
        path = request.url.path
        is_html = ("text/html" in ct) and (path.endswith(".html") or path == "/")
        if is_html:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            html = body.decode("utf-8", errors="ignore")
            if "<head>" in html:
                meta = await _load_seo_meta_tags()
                if meta:
                    html = html.replace("<head>", "<head>\n" + meta, 1)
                headers = dict(response.headers)
                headers.pop("content-length", None)  # 새 body 길이로 자동 재계산
                return Response(content=html.encode("utf-8"), status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception:
        pass
    return response
