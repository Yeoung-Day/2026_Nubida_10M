"""
👥 회원 통합 API — 회원가입, 토큰 관리, 회원 연결
"""
import secrets
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.core.database import get_db
from app.core.security import hash_password, generate_registration_code, create_unique_registration_code, get_current_user
from app.models import User, UserToken, MembershipLink
from app.schemas import ApiResponse

router = APIRouter(prefix="/member", tags=["회원 통합"])


def _generate_nbd_token() -> str:
    """NBD-XXXXXXXX 형식의 토큰 생성"""
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    return f"NBD-{random_part}"


# ============================================================
# 1. 회원 등록
# ============================================================


@router.post("/register")
async def register_member(data: dict, db: AsyncSession = Depends(get_db)):
    """새로운 회원 등록 (자동 토큰 생성)"""
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    # 🚨 보안 (2026-09-14): 클라이언트가 보낸 role 을 그대로 저장하면
    #    누구나 {"role":"super_admin"} 으로 관리자 계정을 자가 생성할 수 있다.
    #    공개 가입은 student/parent 만 허용하고 관리자급은 student 로 강등한다.
    _raw_role = (data.get("role") or "student").strip().lower()
    _PUBLIC_ROLES = {"student", "parent"}
    _PRIVILEGED = {"super_admin", "admin", "hq_admin", "root", "staff",
                   "director", "branch_admin", "branch_manager"}
    if _raw_role in _PRIVILEGED:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "🚨 권한 상승 시도 차단(member) — username=%s requested_role=%s",
            username, _raw_role,
        )
        role = "student"
    elif _raw_role not in _PUBLIC_ROLES:
        role = "student"
    else:
        role = _raw_role
    branch_id = data.get("branch_id")

    # email이 없으면 username을 email로 사용
    if not email and username:
        email = username

    if not all([username, email, password, name]):
        raise HTTPException(status_code=400, detail="username, email, password, name은 필수 입력값입니다.")

    # 중복 확인
    result = await db.execute(
        select(User).where(or_(User.username == username, User.email == email))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 존재하는 사용자명 또는 이메일입니다.")

    # 사용자 생성
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        name=name,
        phone=phone,
        role=role,
        branch_id=branch_id,
        registration_code=await create_unique_registration_code(db),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 토큰 생성 (1년 후 만료)
    token_value = _generate_nbd_token()
    user_token = UserToken(
        user_id=user.id,
        token=token_value,
        purpose="registration",
        is_used=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db.add(user_token)
    await db.commit()

    return ApiResponse(data={
        "user": {
            "id": user.id,
            "name": user.name,
            "role": user.role,
        },
        "token": token_value,
    })


# ============================================================
# 2. 토큰 재발급
# ============================================================


@router.post("/token/regenerate")
async def regenerate_token(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자의 토큰 재발급 (기존 토큰 삭제 후 새로 생성)"""
    user_id = current_user["id"]

    # 기존 토큰 삭제 (user_id unique constraint)
    result = await db.execute(
        select(UserToken).where(UserToken.user_id == user_id)
    )
    old_token = result.scalar_one_or_none()
    if old_token:
        await db.delete(old_token)

    # 새 토큰 생성
    token_value = _generate_nbd_token()
    new_token = UserToken(
        user_id=user_id,
        token=token_value,
        purpose="registration",
        is_used=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db.add(new_token)
    await db.commit()

    return ApiResponse(data={
        "token": token_value,
    })


# ============================================================
# 3. 내 토큰 조회
# ============================================================


@router.get("/token/my")
async def get_my_token(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자의 활성 토큰 조회"""
    user_id = current_user["id"]

    result = await db.execute(
        select(UserToken).where(
            UserToken.user_id == user_id,
            UserToken.is_used == False,
        )
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(status_code=404, detail="사용 가능한 토큰이 없습니다.")

    return ApiResponse(data={
        "token": token.token,
    })


# ============================================================
# 4. 회원 연결 (토큰 기반)
# ============================================================


@router.post("/link")
async def link_member(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """토큰으로 다른 회원과 연결"""
    token_value = data.get("token", "").strip()
    relationship = data.get("relationship", "parent_child").strip()

    if not token_value:
        raise HTTPException(status_code=400, detail="token은 필수 입력값입니다.")

    # 토큰으로 사용자 조회 (미사용 & 만료 전)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserToken).where(
            UserToken.token == token_value,
            UserToken.is_used == False,
            UserToken.expires_at > now,
        )
    )
    user_token = result.scalar_one_or_none()
    if not user_token:
        raise HTTPException(status_code=404, detail="유효하지 않은 토큰입니다.")

    parent_user_id = current_user["id"]
    child_user_id = user_token.user_id

    if parent_user_id == child_user_id:
        raise HTTPException(status_code=400, detail="자기 자신과 연결할 수 없습니다.")

    # 중복 연결 확인
    result = await db.execute(
        select(MembershipLink).where(
            MembershipLink.parent_id == parent_user_id,
            MembershipLink.child_id == child_user_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="이미 연결된 회원입니다.")

    # 연결 생성
    link = MembershipLink(
        parent_id=parent_user_id,
        child_id=child_user_id,
        relationship=relationship,
        status="active",
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    return ApiResponse(data={
        "link": {
            "parent_id": link.parent_id,
            "child_id": link.child_id,
            "relationship": link.relationship,
        }
    })


# ============================================================
# 5. 내 연결 목록 조회
# ============================================================


@router.get("/links")
async def get_my_links(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자의 모든 연결 목록 (부모/자식 관계 모두 포함)"""
    user_id = current_user["id"]

    result = await db.execute(
        select(MembershipLink).where(
            or_(
                MembershipLink.parent_id == user_id,
                MembershipLink.child_id == user_id,
            )
        )
    )
    links = result.scalars().all()

    result_data = []
    for link in links:
        if link.parent_id == user_id:
            # 내가 부모인 경우 → 자식 정보
            related_user = await db.execute(select(User).where(User.id == link.child_id))
            related = related_user.scalar_one_or_none()
            result_data.append({
                "link_id": link.id,
                "relationship": link.relationship,
                "direction": "parent",
                "related_user": {
                    "id": related.id,
                    "name": related.name,
                    "role": related.role,
                } if related else None,
                "created_at": str(link.created_at),
            })
        else:
            # 내가 자식인 경우 → 부모 정보
            related_user = await db.execute(select(User).where(User.id == link.parent_id))
            related = related_user.scalar_one_or_none()
            result_data.append({
                "link_id": link.id,
                "relationship": link.relationship,
                "direction": "child",
                "related_user": {
                    "id": related.id,
                    "name": related.name,
                    "role": related.role,
                } if related else None,
                "created_at": str(link.created_at),
            })

    return ApiResponse(data=result_data)


# ============================================================
# 6. 연결 삭제
# ============================================================


@router.delete("/link/{link_id}")
async def delete_link(
    link_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """연결 삭제 (부모만 가능)"""
    result = await db.execute(select(MembershipLink).where(MembershipLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="연결을 찾을 수 없습니다.")

    if link.parent_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="연결을 삭제할 권한이 없습니다.")

    await db.delete(link)
    await db.commit()

    return ApiResponse(message="연결이 삭제되었습니다.")
