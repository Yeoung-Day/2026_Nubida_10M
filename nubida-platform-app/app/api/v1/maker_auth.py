"""
🔐 메이커 코딩 교육 시스템 — 인증 API
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta

from app.core.database import get_db
from app.core.config import settings
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from app.models import MakerStudent, Studio, User
from app.schemas import ApiResponse

router = APIRouter(prefix="/maker", tags=["메이커 코딩 - 인증"])


@router.post("/auth/login")
async def maker_login(data: dict, db: AsyncSession = Depends(get_db)):
    """학생/원장/본사 통합 로그인"""
    login_id = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "student")

    if not login_id or not password:
        raise HTTPException(400, detail="아이디와 비밀번호를 입력해주세요.")

    if role == "student":
        result = await db.execute(
            select(MakerStudent).where(MakerStudent.login_id == login_id)
        )
        student = result.scalar_one_or_none()
        if not student or not verify_password(password, student.password_hash):
            raise HTTPException(401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")
        if not student.is_active:
            raise HTTPException(403, detail="비활성화된 계정입니다.")

        token = create_access_token({
            "sub": str(student.id),
            "role": "maker_student",
            "studio_id": student.studio_id,
            "name": student.name,
        }, expires_delta=timedelta(hours=12))

        return ApiResponse(data={
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": student.id,
                "name": student.name,
                "role": "maker_student",
                "studio_id": student.studio_id,
                "grade": student.grade,
            }
        })

    elif role == "admin":
        result = await db.execute(
            select(Studio).where(Studio.admin_name == login_id)
        )
        studio = result.scalar_one_or_none()
        if not studio or not verify_password(password, studio.password_hash or ""):
            raise HTTPException(401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")

        token = create_access_token({
            "sub": str(studio.id),
            "role": "maker_admin",
            "name": studio.name,
            "studio_id": studio.id,
        }, expires_delta=timedelta(hours=12))

        return ApiResponse(data={
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": studio.id,
                "name": studio.name,
                "role": "maker_admin",
                "admin_name": studio.admin_name,
            }
        })

    elif role == "superadmin":
        result = await db.execute(
            select(User).where(User.username == login_id)
        )
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")
        if user.role not in ("super_admin", "admin"):
            raise HTTPException(403, detail="본사 관리자만 접근 가능합니다.")

        token = create_access_token({
            "sub": str(user.id),
            "role": "maker_superadmin",
            "name": user.name,
            "username": user.username,
        }, expires_delta=timedelta(hours=12))

        return ApiResponse(data={
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "name": user.name,
                "username": user.username,
                "role": "maker_superadmin",
            }
        })

    raise HTTPException(400, detail="올바르지 않은 역할(role)입니다.")


async def get_maker_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """메이커 시스템 인증 사용자 확인"""
    payload = decode_token(credentials.credentials)
    role = payload.get("role")
    if role not in ("maker_student", "maker_admin", "maker_superadmin"):
        raise HTTPException(401, detail="올바르지 않은 토큰입니다.")
    return {
        "id": int(payload.get("sub", 0)),
        "role": role,
        "name": payload.get("name", ""),
        "studio_id": payload.get("studio_id"),
    }
