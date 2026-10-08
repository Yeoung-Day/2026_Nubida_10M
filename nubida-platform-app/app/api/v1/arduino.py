"""
🤖 아두이노 웹 코딩 에디터 API
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.api.v1.ml import _ensure_ml_unlocked  # 누비다머신 잠금(소속 원장 단위) 공동 가드 — ml과 동일
from app.models import ArduinoCode, Course
from app.schemas import ApiResponse

router = APIRouter(prefix="/arduino", tags=["아두이노 코딩"])


def sanitize_filename(name: str) -> str:
    """파일명에서 특수문자 제거"""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    return name.strip() or "sketch"


# ============================================================
# 코드 목록 조회 (강좌별)
# ============================================================

@router.get("/codes")
async def list_codes(
    course_id: int = Query(None),
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """강좌별 아두이노 코드 목록 조회"""
    query = select(ArduinoCode)

    if course_id:
        query = query.where(ArduinoCode.course_id == course_id)
    else:
        query = query.where(ArduinoCode.user_id == current_user["id"])

    query = query.order_by(desc(ArduinoCode.updated_at))
    result = await db.execute(query)
    codes = result.scalars().all()

    return ApiResponse(data=[
        {
            "id": c.id,
            "course_id": c.course_id,
            "title": c.title,
            "description": c.description or "",
            "tags": c.tags or "",
            "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            "created_at": c.created_at.isoformat() if c.created_at else "",
        }
        for c in codes
    ])


# ============================================================
# 코드 상세 조회
# ============================================================

@router.get("/codes/{code_id}")
async def get_code(
    code_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """아두이노 코드 상세 조회"""
    result = await db.execute(
        select(ArduinoCode).where(ArduinoCode.id == code_id)
    )
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")

    return ApiResponse(data={
        "id": code.id,
        "course_id": code.course_id,
        "user_id": code.user_id,
        "title": code.title,
        "code": code.code,
        "description": code.description or "",
        "tags": code.tags or "",
        "updated_at": code.updated_at.isoformat() if code.updated_at else "",
        "created_at": code.created_at.isoformat() if code.created_at else "",
    })


# ============================================================
# 코드 생성
# ============================================================

@router.post("/codes")
async def create_code(
    data: dict,
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """새 아두이노 코드 생성"""
    title = data.get("title", "새 스케치").strip() or "새 스케치"
    course_id = data.get("course_id")

    # 코스 존재 확인
    if course_id:
        result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="강좌를 찾을 수 없습니다.")

    code = ArduinoCode(
        course_id=course_id,
        user_id=current_user["id"],
        title=title,
        code=data.get("code", ""),
        description=data.get("description", ""),
        tags=data.get("tags", ""),
    )
    db.add(code)
    await db.commit()
    await db.refresh(code)

    return ApiResponse(
        message="코드가 생성되었습니다.",
        data={"id": code.id, "title": code.title}
    )


# ============================================================
# 코드 업데이트
# ============================================================

@router.put("/codes/{code_id}")
async def update_code(
    code_id: int,
    data: dict,
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """아두이노 코드 저장"""
    result = await db.execute(
        select(ArduinoCode).where(ArduinoCode.id == code_id)
    )
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")

    if "title" in data:
        code.title = data["title"].strip() or code.title
    if "code" in data:
        code.code = data["code"]
    if "description" in data:
        code.description = data.get("description", "")
    if "tags" in data:
        code.tags = data.get("tags", "")
    if "course_id" in data:
        code.course_id = data["course_id"]

    await db.commit()
    await db.refresh(code)

    return ApiResponse(
        message="코드가 저장되었습니다.",
        data={"id": code.id, "title": code.title}
    )


# ============================================================
# 코드 삭제
# ============================================================

@router.delete("/codes/{code_id}")
async def delete_code(
    code_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """아두이노 코드 삭제"""
    result = await db.execute(
        select(ArduinoCode).where(ArduinoCode.id == code_id)
    )
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")

    await db.delete(code)
    await db.commit()

    return ApiResponse(message="코드가 삭제되었습니다.")


# ============================================================
# .ino 파일 다운로드
# ============================================================

@router.get("/codes/{code_id}/download")
async def download_code(
    code_id: int,
    current_user: dict = Depends(_ensure_ml_unlocked),  # 학생만 + 소속 원장 잠금 시 403 (누비다머신)
    db: AsyncSession = Depends(get_db),
):
    """아두이노 .ino 파일 다운로드"""
    result = await db.execute(
        select(ArduinoCode).where(ArduinoCode.id == code_id)
    )
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다.")

    from fastapi.responses import PlainTextResponse

    filename = sanitize_filename(code.title) + ".ino"

    return PlainTextResponse(
        content=code.code or "",
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
