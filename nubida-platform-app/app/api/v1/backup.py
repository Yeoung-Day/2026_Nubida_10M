"""
💾 DB 백업 관리 API
"""
from fastapi import APIRouter, Depends
import os, glob, json
from datetime import datetime

from app.core.security import require_role
from app.schemas import ApiResponse

router = APIRouter(prefix="/backups", tags=["백업"])
BACKUP_DIR = "/root/shared/nubida-platform/backups"
DB_PATH = "/root/shared/nubida-platform/backend/nubida.db"
BACKUP_SCRIPT = "/root/shared/nubida-platform/backend/backup_db.py"


@router.get("/list")
async def list_backups(current_user: dict = Depends(require_role("admin", "super_admin"))):
    """백업 파일 목록 조회"""
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "nubida_backup_*.db.gz")), reverse=True)
    items = []
    for f in backups:
        fname = os.path.basename(f)
        size_bytes = os.path.getsize(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        items.append({
            "filename": fname,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "created_at": mtime.isoformat(),
        })
    total_size = sum(i["size_bytes"] for i in items)
    return ApiResponse(data={
        "backups": items,
        "total_count": len(items),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "retention_days": 7,
        "db_size_mb": round(os.path.getsize(DB_PATH) / (1024 * 1024), 2) if os.path.exists(DB_PATH) else 0,
        "next_backup": "매일 04:00",
    })


@router.post("/run")
async def run_backup(current_user: dict = Depends(require_role("admin", "super_admin"))):
    """수동 백업 실행"""
    import subprocess, sys
    result = subprocess.run([sys.executable, BACKUP_SCRIPT], capture_output=True, text=True)
    success = result.returncode == 0
    return ApiResponse(
        data={"success": success, "output": result.stdout.strip(), "error": result.stderr.strip() if not success else ""},
        message="백업 완료" if success else "백업 실패"
    )


@router.post("/cleanup")
async def cleanup_backups(current_user: dict = Depends(require_role("admin", "super_admin"))):
    """오래된 백업 정리 (7일 초과 삭제)"""
    cutoff = datetime.now() - __import__('datetime', fromlist=['timedelta']).timedelta(days=7)
    deleted = 0
    for f in glob.glob(os.path.join(BACKUP_DIR, "nubida_backup_*.db.gz")):
        try:
            fname = os.path.basename(f)
            date_str = fname.split("_")[2]
            fdate = datetime.strptime(date_str, "%Y%m%d")
            if fdate < cutoff:
                os.remove(f)
                deleted += 1
        except:
            pass
    remaining = len(glob.glob(os.path.join(BACKUP_DIR, "nubida_backup_*.db.gz")))
    return ApiResponse(data={"deleted": deleted, "remaining": remaining})
