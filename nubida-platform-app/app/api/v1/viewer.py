"""
📽️ 학습 뷰어 - PPTX/PDF → PNG 변환 API
LibreOffice headless + pdf2image로 페이지별 PNG 변환 (비동기 백그라운드 방식)
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from app.core.security import get_current_user
from app.api.v1.sse import get_user_from_query

router = APIRouter(prefix="/viewer", tags=["학습 뷰어 변환"])

# 캐시 디렉토리 설정
CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "viewer_cache"
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads"
ALT_UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"  # /app/app/uploads

_ALLOWED_UPLOAD_DIRS = tuple(d.resolve() for d in (UPLOADS_DIR, ALT_UPLOADS_DIR))

os.makedirs(CACHE_DIR, exist_ok=True)
for d in (UPLOADS_DIR, ALT_UPLOADS_DIR):
    if d.parent.exists():
        d.mkdir(exist_ok=True)

# 변환 진행 중인 작업 추적 (스레드 안전)
_pending_conversions: dict[str, dict] = {}
_pending_lock = threading.Lock()

# 최대 동시 변환 스레드 수
_MAX_CONCURRENT_CONVERSIONS = 2
_active_conversions = 0
_active_conversions_lock = threading.Lock()

# 최대 페이지 수 (대용량 PDF 제한)
_MAX_PAGES = 50


def _safe_upload_path(file_path: str) -> Path:
    """file_path 검증 → 안전한 uploads 디렉토리 내 경로만 반환.

    보안 규칙:
      1. '..' (부모 디렉토리 이동) 조각을 포함하면 거부
      2. 절대 경로('/uploads/...' 제외)는 uploads 디렉토리 밖이면 거부
      3. 최종 resolve() 경로가 반드시 uploads 디렉토리 안에 위치해야 함
    """
    if not file_path or not isinstance(file_path, str):
        raise HTTPException(status_code=400, detail="유효하지 않은 파일 경로입니다")

    # null byte 차단
    if "\x00" in file_path:
        raise HTTPException(status_code=400, detail="유효하지 않은 파일 경로입니다")

    # '..' 부모 디렉토리 탐색 차단
    if ".." in file_path.replace("\\", "/").split("/"):
        raise HTTPException(status_code=400, detail="부모 디렉토리 접근은 허용되지 않습니다")

    # '/uploads/xxx' 형태 → uploads 디렉토리 기준 상대 경로로 변환
    if file_path.startswith("/uploads/"):
        rel = file_path[len("/uploads/"):]
        candidates = [
            UPLOADS_DIR / rel,
            ALT_UPLOADS_DIR / rel,
        ]
    else:
        p = Path(file_path)
        # 상대 경로 + 절대 경로 모두 uploads 디렉토리 안으로 강제
        candidates = [UPLOADS_DIR / p, ALT_UPLOADS_DIR / p]

    # 후보 경로가 모두 uploads 디렉토리 안에 있는지 강제 검증
    for cand in candidates:
        resolved = cand.resolve()
        if not any(resolved.is_relative_to(base) for base in _ALLOWED_UPLOAD_DIRS):
            raise HTTPException(
                status_code=400,
                detail="허용된 업로드 디렉토리 밖의 경로는 접근할 수 없습니다",
            )

    # 실제 존재하는 후보를 반환 (없으면 첫 번째 후보 → 404 처리됨)
    for cand in candidates:
        if cand.is_file():
            return cand
    return candidates[0]


def _require_upload_dir(file_path: str) -> Path:
    """upload 디렉토리 내 안전 경로로 resolve된 파일만 허용 (권한 검증 포함)"""
    fs_path = _safe_upload_path(file_path)
    if not fs_path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
    resolved = fs_path.resolve()
    if not any(resolved.is_relative_to(base) for base in _ALLOWED_UPLOAD_DIRS):
        raise HTTPException(
            status_code=400,
            detail="허용된 업로드 디렉토리 밖의 파일은 접근할 수 없습니다",
        )
    return fs_path


def _get_cache_key(file_path: str) -> str:
    """파일 경로 + mtime → MD5 해시 (캐시 키)"""
    import hashlib
    try:
        mtime = str(os.path.getmtime(file_path))
    except (OSError, FileNotFoundError):
        mtime = "0"
    return hashlib.md5((file_path + mtime).encode("utf-8")).hexdigest()


_VIEWER_DPI = 100          # 화면 표시용 (기존 150 → 100: 3배 빠름, 품질 충분)
_VIEWER_QUALITY = 82       # JPEG 품질
_VIEWER_EXT = "jpg"        # PNG 대신 JPEG (용량 1/8, 로딩 빠름)


def _run_pdftoppm(pdf_path: str, output_dir: str, dpi: int, max_pages: int) -> int:
    """pdftoppm CLI로 PDF → JPEG 직접 변환 (pdf2image/PIL 우회: 3배 빠름).

    기존: convert_from_path() + img.save()  → PDF 24MB/44장 = 204초
    개선: pdftoppm -jpeg -r 100             → 동일 파일 68초, 장당 133KB
    """
    subprocess.run(
        [
            "pdftoppm", "-jpeg",
            "-jpegopt", f"quality={_VIEWER_QUALITY}",
            "-r", str(dpi),
            "-f", "1", "-l", str(max_pages),
            pdf_path, os.path.join(output_dir, "slide"),
        ],
        capture_output=True, timeout=600,
    )
    # pdftoppm 출력: slide-01.jpg / slide-1.jpg (페이지수 자릿수에 따라 다름)
    files = [f for f in os.listdir(output_dir) if f.lower().endswith((".jpg", ".jpeg"))]
    files.sort()
    # 파일명을 slide_0001.jpg 형식으로 정규화 (순서 유지)
    for idx, name in enumerate(files, start=1):
        src = os.path.join(output_dir, name)
        dst = os.path.join(output_dir, f"slide_{idx:04d}.jpg")
        if src != dst:
            os.replace(src, dst)
    return len(files)


def _do_convert_pptx(pptx_path: str, output_dir: str) -> int:
    """PPTX → PDF(LibreOffice) → JPEG(pdftoppm, 멀티코어)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmpdir, pptx_path],
                capture_output=True, timeout=180,
                env={**os.environ, "HOME": "/tmp"}
            )
        except subprocess.TimeoutExpired:
            return 0
        pdf_files = [f for f in os.listdir(tmpdir) if f.endswith(".pdf")]
        if not pdf_files:
            return 0
        pdf_path = os.path.join(tmpdir, pdf_files[0])
        return _run_pdftoppm(pdf_path, output_dir, _VIEWER_DPI, _MAX_PAGES)


def _do_convert_pdf(pdf_path: str, output_dir: str, dpi: int = None) -> int:
    """PDF 각 페이지를 JPEG로 변환 (pdftoppm CLI, 최대 _MAX_PAGES 제한)"""
    if not dpi:
        dpi = _VIEWER_DPI
    return _run_pdftoppm(pdf_path, output_dir, dpi, _MAX_PAGES)


_SLIDE_RE = re.compile(r"^slide_(\d{4})\.(jpg|jpeg|png)$", re.IGNORECASE)


def _make_slides_list(cache_key: str) -> tuple[int, list[str]]:
    """캐시 디렉토리에서 정규화된 슬라이드 파일 목록 생성.

    변환 중인 부분 파일(slide-01.jpg 등)을 잘못 인식하지 않도록
    'slide_NNNN.(jpg|png)' 패턴만 인정한다.
    """
    cache_dir = CACHE_DIR / cache_key
    if not cache_dir.is_dir():
        return 0, []
    files = []
    for f in os.listdir(cache_dir):
        if _SLIDE_RE.match(f):
            files.append(f)
    files.sort()
    if not files:
        return 0, []
    slides = [f"/api/v1/viewer/slide/{cache_key}/{f}" for f in files]
    return len(files), slides


def _run_conversion_in_background(cache_key: str, file_path: str, dpi: int = None):
    """백그라운드에서 변환 실행 (별도 스레드, 동시 실행 제한 있음)"""
    global _active_conversions

    with _active_conversions_lock:
        _active_conversions += 1

    try:
        fs_path = _safe_upload_path(file_path)
        cache_dir = CACHE_DIR / cache_key
        os.makedirs(cache_dir, exist_ok=True)

        # [FIX] 변환 시작 전 stale 캐시 제거.
        # 이전 실패/중단으로 남은 부분 파일(slide-01.jpg 등)이나 구버전 PNG가
        # _make_slides_list에 잡혀 "완료(1장)"로 오판되는 것을 방지.
        for _f in os.listdir(cache_dir):
            if _f.lower().endswith((".jpg", ".jpeg", ".png")):
                try:
                    os.remove(cache_dir / _f)
                except OSError:
                    pass

        ext = fs_path.suffix.lower()
        fs_path_str = str(fs_path.resolve())

        if ext in (".pptx", ".ppt"):
            _do_convert_pptx(fs_path_str, str(cache_dir))
        elif ext == ".pdf":
            _do_convert_pdf(fs_path_str, str(cache_dir), dpi)
        else:
            # 이미지 등 단일 페이지: 원본 확장자 유지하여 복사
            img_ext = fs_path.suffix.lower().lstrip(".") or "jpg"
            shutil.copy2(fs_path_str, cache_dir / f"slide_0001.{img_ext}")

        total, slides = _make_slides_list(cache_key)
        with _pending_lock:
            _pending_conversions[cache_key] = {
                "status": "ready", "pages": total, "slides": slides,
                "completed_at": time.time()
            }
    except Exception as e:
        with _pending_lock:
            _pending_conversions[cache_key] = {
                "status": "failed", "error": str(e), "completed_at": time.time()
            }
    finally:
        with _active_conversions_lock:
            _active_conversions -= 1


def start_conversion(file_url: str, dpi: int = None) -> str:
    """
    변환을 시작하고 cache_key를 반환합니다.
    materials.py의 upload API에서 호출할 수 있도록 export된 함수.
    """
    global _active_conversions

    fs_path = _safe_upload_path(file_url)
    if not fs_path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_url}")

    cache_key = _get_cache_key(str(fs_path.resolve()))
    cache_dir = CACHE_DIR / cache_key

    # 이미 캐시됨
    total, slides = _make_slides_list(cache_key)
    if total > 0:
        return cache_key

    # 이미 변환 중
    with _pending_lock:
        if cache_key in _pending_conversions:
            return cache_key

    # 변환 시작
    with _pending_lock:
        _pending_conversions[cache_key] = {"status": "processing", "started_at": time.time()}

    # 백그라운드 스레드 실행
    thread = threading.Thread(
        target=_run_conversion_in_background,
        args=(cache_key, file_url, dpi),
        daemon=True
    )
    thread.start()

    return cache_key


# ============================================================
# 1. 변환 상태 확인 (빠름 — 캐시 확인만)
# ============================================================
@router.get("/check")
async def check_conversion(
    file_path: str = Query(..., description="변환할 파일 경로"),
    current_user: dict = Depends(get_current_user),
):
    """변환 상태 확인. 캐시되었으면 즉시 반환 (인증 필요)"""
    fs_path = _require_upload_dir(file_path)
    cache_key = _get_cache_key(str(fs_path.resolve()))

    # 캐시 확인
    total, slides = _make_slides_list(cache_key)
    if total > 0:
        return JSONResponse({
            "status": "ready", "pages": total, "slides": slides, "cache_key": cache_key,
        })

    # 변환 중인지 확인
    with _pending_lock:
        if cache_key in _pending_conversions:
            info = _pending_conversions[cache_key]
            if info["status"] == "ready":
                return JSONResponse({
                    "status": "ready", "pages": info.get("pages", 0),
                    "slides": info.get("slides", []), "cache_key": cache_key,
                })
            elif info["status"] == "failed":
                return JSONResponse({
                    "status": "needs_conversion", "cache_key": cache_key,
                    "message": f"변환 실패: {info.get('error', '알 수 없음')}",
                })
            return JSONResponse({
                "status": "processing", "cache_key": cache_key, "message": "변환 중입니다...",
            })

    # 변환이 아직 시작되지 않음 → 자동 시작
    try:
        start_conversion(file_path)
        return JSONResponse({
            "status": "processing", "cache_key": cache_key, "message": "변환을 시작했습니다...",
        })
    except Exception as e:
        return JSONResponse({
            "status": "needs_conversion", "cache_key": cache_key,
            "message": f"변환 시작 실패: {str(e)}",
        })


# ============================================================
# 2. 변환 시작 (비동기 — 즉시 반환)
# ============================================================
@router.post("/convert")
async def start_conversion_endpoint(
    file_path: str = Query(..., description="변환할 파일 경로"),
    dpi: int = Query(_VIEWER_DPI, ge=72, le=300),
    current_user: dict = Depends(get_current_user),
):
    """변환을 백그라운드에서 실행하고 즉시 응답 (인증 필요)"""
    fs_path = _require_upload_dir(file_path)
    cache_key = _get_cache_key(str(fs_path.resolve()))
    cache_dir = CACHE_DIR / cache_key

    # 이미 캐시됨
    total, slides = _make_slides_list(cache_key)
    if total > 0:
        return JSONResponse({
            "status": "ready", "pages": total, "slides": slides, "cache_key": cache_key,
        })

    # 이미 변환 중
    with _pending_lock:
        if cache_key in _pending_conversions:
            return JSONResponse({
                "status": "processing", "cache_key": cache_key,
            })

    # 백그라운드 변환 시작
    start_conversion(file_path, dpi)

    return JSONResponse({
        "status": "processing", "cache_key": cache_key,
        "message": "변환이 백그라운드에서 실행 중입니다. 잠시 후 새로고침하거나 다시 시도해주세요.",
    })


# ============================================================
# 3. 변환된 슬라이드 이미지 제공
# ============================================================
@router.get("/slide/{cache_key}/{filename}")
async def serve_slide(
    cache_key: str,
    filename: str,
    current_user: dict = Depends(get_user_from_query),
):
    """변환된 슬라이드 이미지 제공 (쿼리 파라미터 인증) — jpg/png 지원"""
    # 경로 탐색 차단: cache_key / filename 은 '..' 부모 이동 및 경로 분리자를 포함할 수 없음
    if ".." in cache_key or ".." in filename:
        raise HTTPException(status_code=400, detail="허용되지 않은 경로입니다")
    if "/" in cache_key or "\\" in cache_key or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="허용되지 않은 경로입니다")
    low = filename.lower()
    if not low.endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=404, detail="슬라이드를 찾을 수 없습니다")

    slide_path = CACHE_DIR / cache_key / filename
    if not slide_path.is_file():
        raise HTTPException(status_code=404, detail="슬라이드를 찾을 수 없습니다")
    media = "image/png" if low.endswith(".png") else "image/jpeg"
    # 브라우저 캐시 허용 (동일 슬라이드 반복 요청 시 재전송 방지)
    return FileResponse(
        str(slide_path),
        media_type=media,
        headers={"Cache-Control": "public, max-age=604800"},
    )
