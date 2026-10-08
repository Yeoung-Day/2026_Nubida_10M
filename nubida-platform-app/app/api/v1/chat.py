"""누비다플랫폼 채팅 시스템 — REST API + WebSocket"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from sqlalchemy import select, and_, or_, desc, func as sa_func
from sqlalchemy.orm import selectinload
from datetime import datetime
import json

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas import ApiResponse
from app.models import User, ChatRoom, ChatParticipant, ChatMessage, Branch
from app.chat import manager as ws_manager

router = APIRouter(prefix="/chat", tags=["Chat"])


# ============================================================
# 권한 검증 헬퍼
# ============================================================

async def _can_access_room(room_id: int, user: dict, db) -> bool:
    """사용자가 특정 채팅방에 접근 가능한지 확인"""
    result = await db.execute(
        select(ChatParticipant).where(
            and_(ChatParticipant.room_id == room_id, ChatParticipant.user_id == user["id"])
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        return True
    # super_admin/admin은 모든 방 접근 가능
    if user.get("role") in ("super_admin", "admin"):
        return True
    return False


async def _get_available_users(user: dict, db):
    """현재 사용자가 채팅 가능한 사용자 목록 반환

    - super_admin/admin: 전체 사용자
    - branch_admin/branch_manager: 동일 branch_id 소속 사용자 + 본사
    - director: 동일 branch_id 소속 사용자 + 에듀케어 + 본사
    - student/parent: 동일 director_id + branch_id 소속 사용자 + 원장 + 에듀케어 + 본사
    """
    role = user.get("role", "")
    user_id = user["id"]
    branch_id = user.get("branch_id")
    director_id = user.get("director_id")

    # 공통: 본사(super_admin/admin)는 항상 표시 가능한 대상
    hq_roles = ["admin", "super_admin"]

    if role in hq_roles:
        # 본사: 모든 사용자
        result = await db.execute(select(User).where(User.is_active == True))
        return result.scalars().all()

    elif role in ("branch_admin", "branch_manager"):
        # 에듀케어: 동일 branch_id 소속 사용자 + 본사
        result = await db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    or_(
                        User.branch_id == branch_id,
                        User.role.in_(hq_roles),
                        User.id == user_id
                    )
                )
            )
        )
        return result.scalars().all()

    elif role == "director":
        # 원장: 동일 branch_id 소속 사용자 + 에듀케어 + 본사
        result = await db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    or_(
                        User.branch_id == branch_id,
                        User.role.in_(["branch_admin", "branch_manager"] + hq_roles),
                        User.id == user_id
                    )
                )
            )
        )
        return result.scalars().all()

    elif role == "student":
        # 학생: 동일 director_id + branch_id 소속 + 원장 + 에듀케어 + 본사
        result = await db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    or_(
                        and_(
                            User.branch_id == branch_id,
                            or_(
                                User.director_id == director_id,
                                User.id == user_id
                            )
                        ),
                        and_(
                            User.branch_id == branch_id,
                            User.role == "director"
                        ),
                        User.role.in_(["branch_admin", "branch_manager"] + hq_roles),
                    )
                )
            )
        )
        return result.scalars().all()

    elif role == "parent":
        # 학부모: 동일 director_id + branch_id 소속 + 원장 + 에듀케어 + 본사
        result = await db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    or_(
                        and_(
                            User.branch_id == branch_id,
                            or_(
                                User.director_id == director_id,
                                User.id == user_id
                            )
                        ),
                        and_(
                            User.branch_id == branch_id,
                            User.role == "director"
                        ),
                        User.role.in_(["branch_admin", "branch_manager"] + hq_roles),
                    )
                )
            )
        )
        return result.scalars().all()

    return []


# ============================================================
# REST API
# ============================================================

@router.get("/rooms/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """전체 안 읽은 메시지 수"""
    subq = select(
        ChatParticipant.room_id,
        ChatParticipant.last_read_id
    ).where(ChatParticipant.user_id == current_user["id"]).subquery()

    result = await db.execute(
        select(sa_func.count(ChatMessage.id)).where(
            and_(
                ChatMessage.room_id == subq.c.room_id,
                ChatMessage.id > subq.c.last_read_id,
                ChatMessage.sender_id != current_user["id"]
            )
        )
    )
    count = result.scalar() or 0
    return ApiResponse(data={"unread_count": count})


@router.get("/rooms")
async def get_my_rooms(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """내 채팅방 목록"""
    result = await db.execute(
        select(ChatRoom).join(
            ChatParticipant,
            ChatParticipant.room_id == ChatRoom.id
        ).where(
            ChatParticipant.user_id == current_user["id"]
        ).order_by(ChatRoom.updated_at.desc())
    )
    rooms = result.scalars().all()

    room_list = []
    for room in rooms:
        # 마지막 메시지
        msg_result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.room_id == room.id
            ).order_by(ChatMessage.id.desc()).limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()

        # 참여자 수
        participant_count_result = await db.execute(
            select(sa_func.count(ChatParticipant.id)).where(
                ChatParticipant.room_id == room.id
            )
        )
        participant_count = participant_count_result.scalar() or 0

        # 안 읽은 메시지 수
        my_participant_result = await db.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.room_id == room.id,
                    ChatParticipant.user_id == current_user["id"]
                )
            )
        )
        my_participant = my_participant_result.scalar_one_or_none()
        last_read_id = my_participant.last_read_id if my_participant else 0

        unread_result = await db.execute(
            select(sa_func.count(ChatMessage.id)).where(
                and_(
                    ChatMessage.room_id == room.id,
                    ChatMessage.id > last_read_id,
                    ChatMessage.sender_id != current_user["id"]
                )
            )
        )
        unread_count = unread_result.scalar() or 0

        # 1:1 채팅: 방 이름이 없으면 상대방 이름을 기본 표시 (사용자가 설정한 이름은 유지)
        display_name = room.name
        if room.room_type == "direct" and not room.name:
            other_result = await db.execute(
                select(User).join(
                    ChatParticipant,
                    ChatParticipant.user_id == User.id
                ).where(
                    and_(
                        ChatParticipant.room_id == room.id,
                        ChatParticipant.user_id != current_user["id"]
                    )
                ).limit(1)
            )
            other_user = other_result.scalar_one_or_none()
            if other_user:
                display_name = other_user.name

        room_list.append({
            "id": room.id,
            "room_type": room.room_type,
            "name": display_name,
            "created_by": room.created_by,
            "participant_count": participant_count,
            "last_message": {
                "content": last_msg.content[:100] if last_msg else "",
                "sender_name": last_msg.sender_name if hasattr(last_msg, 'sender_name') else "",
                "created_at": str(last_msg.created_at) if last_msg else None
            } if last_msg else None,
            "unread_count": unread_count,
            "updated_at": str(room.updated_at),
        })

    return ApiResponse(data=room_list)


@router.post("/rooms")
async def create_room(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """채팅방 생성"""
    room_type = data.get("room_type", "direct")
    name = data.get("name", "")
    user_ids = data.get("user_ids", [])

    if room_type == "direct":
        # 1:1 채팅 — 이미 존재하는 방이 있는지 확인
        target_user_id = data.get("user_id")
        if not target_user_id:
            raise HTTPException(status_code=400, detail="user_id가 필요합니다.")
        
        # 이미 존재하는 1:1 방 찾기
        existing_result = await db.execute(
            select(ChatRoom).where(ChatRoom.room_type == "direct")
        )
        existing_rooms = existing_result.scalars().all()
        for room in existing_rooms:
            part_result = await db.execute(
                select(ChatParticipant).where(ChatParticipant.room_id == room.id)
            )
            participants = part_result.scalars().all()
            pids = {p.user_id for p in participants}
            if pids == {current_user["id"], target_user_id}:
                return ApiResponse(data={"id": room.id, "room_type": "direct", "existing": True})

        user_ids = [current_user["id"], target_user_id]
        if not name:
            # 상대방 이름 찾기
            user_result = await db.execute(select(User).where(User.id == target_user_id))
            target_user = user_result.scalar_one_or_none()
            name = target_user.name if target_user else ""

    elif room_type == "group":
        if not name:
            raise HTTPException(status_code=400, detail="그룹방 이름이 필요합니다.")
        if not user_ids:
            raise HTTPException(status_code=400, detail="참여자 목록이 필요합니다.")

    elif room_type == "announcement":
        if not name:
            raise HTTPException(status_code=400, detail="공지방 이름이 필요합니다.")
        if not user_ids:
            raise HTTPException(status_code=400, detail="수신자 목록이 필요합니다.")

    # 방 생성
    room = ChatRoom(
        room_type=room_type,
        name=name,
        created_by=current_user["id"],
    )
    db.add(room)
    await db.flush()

    # 참여자 추가
    for uid in set(user_ids):
        db.add(ChatParticipant(
            room_id=room.id,
            user_id=uid,
            role="admin" if uid == current_user["id"] else "member"
        ))

    await db.commit()
    await db.refresh(room)

    return ApiResponse(data={"id": room.id, "room_type": room_type, "existing": False})


@router.get("/rooms/{room_id}/messages")
async def get_messages(
    room_id: int,
    before: int = Query(0, description="이 message_id 이전 메시지"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """메시지 내역"""
    if not await _can_access_room(room_id, current_user, db):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    query = select(ChatMessage).where(ChatMessage.room_id == room_id)
    if before:
        query = query.where(ChatMessage.id < before)
    query = query.order_by(ChatMessage.id.desc()).limit(limit)

    result = await db.execute(query)
    messages = result.scalars().all()

    # sender 정보를 포함
    msg_list = []
    for msg in reversed(messages):
        sender_result = await db.execute(select(User).where(User.id == msg.sender_id))
        sender = sender_result.scalar_one_or_none()
        msg_list.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_name": sender.name if sender else "알 수 없음",
            "sender_role": sender.role if sender else "",
            "message_type": msg.message_type,
            "content": msg.content,
            "file_url": msg.file_url or "",
            "file_name": msg.file_name or "",
            "created_at": str(msg.created_at),
        })

    return ApiResponse(data=msg_list)


@router.put("/rooms/{room_id}/read")
async def mark_read(
    room_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """읽음 처리"""
    message_id = data.get("message_id")
    if not message_id:
        raise HTTPException(status_code=400, detail="message_id가 필요합니다.")

    result = await db.execute(
        select(ChatParticipant).where(
            and_(
                ChatParticipant.room_id == room_id,
                ChatParticipant.user_id == current_user["id"]
            )
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=403, detail="참여자가 아닙니다.")

    if message_id > participant.last_read_id:
        participant.last_read_id = message_id
        await db.commit()

        # WebSocket으로 읽음 알림
        await ws_manager.broadcast(room_id, {
            "type": "read_receipt",
            "data": {
                "user_id": current_user["id"],
                "user_name": current_user.get("name", ""),
                "last_read_id": message_id,
            }
        })

    return ApiResponse(data={"last_read_id": message_id})


@router.get("/rooms/{room_id}/participants")
async def get_participants(
    room_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """참여자 목록"""
    if not await _can_access_room(room_id, current_user, db):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    result = await db.execute(
        select(User, ChatParticipant.role).join(
            ChatParticipant,
            and_(
                ChatParticipant.user_id == User.id,
                ChatParticipant.room_id == room_id
            )
        )
    )
    rows = result.all()

    return ApiResponse(data=[{
        "user_id": user.id,
        "name": user.name,
        "role": user.role,
        "participant_role": participant_role,
    } for user, participant_role in rows])


@router.post("/rooms/{room_id}/participants")
async def add_participants(
    room_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """참여자 초대 (group 방만)"""
    user_ids = data.get("user_ids", [])
    if not user_ids:
        raise HTTPException(status_code=400, detail="user_ids가 필요합니다.")

    # 방 타입 확인
    result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    if room.room_type != "group":
        raise HTTPException(status_code=400, detail="그룹방만 초대할 수 있습니다.")

    # 권한 확인
    if not await _can_access_room(room_id, current_user, db):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    added = []
    for uid in user_ids:
        exists = await db.execute(
            select(ChatParticipant).where(
                and_(ChatParticipant.room_id == room_id, ChatParticipant.user_id == uid)
            )
        )
        if not exists.scalar_one_or_none():
            db.add(ChatParticipant(room_id=room_id, user_id=uid, role="member"))
            added.append(uid)

    await db.commit()
    return ApiResponse(data={"added_user_ids": added})


@router.delete("/rooms/{room_id}/participants/{user_id}")
async def remove_participant(
    room_id: int,
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """참여자 내보내기"""
    result = await db.execute(
        select(ChatParticipant).where(
            and_(ChatParticipant.room_id == room_id, ChatParticipant.user_id == user_id)
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=404, detail="참여자를 찾을 수 없습니다.")

    await db.delete(participant)
    await db.commit()
    return ApiResponse(message="내보내기 완료")


@router.post("/rooms/{room_id}/leave")
async def leave_room(
    room_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """채팅방 나가기 (참여자 본인)"""
    result = await db.execute(
        select(ChatParticipant).where(
            and_(
                ChatParticipant.room_id == room_id,
                ChatParticipant.user_id == current_user["id"]
            )
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=404, detail="참여자가 아닙니다.")

    await db.delete(participant)
    await db.commit()

    # WebSocket으로 퇴장 알림
    await ws_manager.broadcast(room_id, {
        "type": "system",
        "data": {"content": f"{current_user.get('name', '')}님이 방을 나갔습니다."}
    })

    return ApiResponse(message="방을 나갔습니다.")


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """채팅방 삭제 (방장/본사만)"""
    result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    
    # 권한 확인 (생성자 or super_admin/admin)
    is_creator = room.created_by == current_user["id"]
    is_admin = current_user.get("role") in ("super_admin", "admin")
    if not is_creator and not is_admin:
        raise HTTPException(status_code=403, detail="방 삭제 권한이 없습니다.")
    
    # 참여자 삭제
    await db.execute(
        ChatParticipant.__table__.delete().where(ChatParticipant.room_id == room_id)
    )
    # 메시지 삭제
    await db.execute(
        ChatMessage.__table__.delete().where(ChatMessage.room_id == room_id)
    )
    
    await db.delete(room)
    await db.commit()
    
    return ApiResponse(message="채팅방이 삭제되었습니다.")


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """채팅방 이름/설명 변경"""
    result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    
    # 권한 확인 (참여자만)
    part_result = await db.execute(
        select(ChatParticipant).where(
            and_(ChatParticipant.room_id == room_id, ChatParticipant.user_id == current_user["id"])
        )
    )
    if not part_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="참여자가 아닙니다.")
    
    if "name" in data:
        room.name = data["name"]
    
    await db.commit()
    return ApiResponse(message="채팅방이 수정되었습니다.")


@router.get("/users-available")
async def get_available_users(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """현재 사용자가 채팅 가능한 사용자 목록"""
    users = await _get_available_users(current_user, db)
    users = [u for u in users if u.id != current_user["id"]]

    # 소속(지사)명 매핑 — 원장/에듀케어 표시용
    branch_ids = {u.branch_id for u in users if u.branch_id}
    branch_map: dict = {}
    if branch_ids:
        br_res = await db.execute(
            select(Branch.id, Branch.name).where(Branch.id.in_(branch_ids))
        )
        branch_map = {bid: bname for bid, bname in br_res.all()}

    return ApiResponse(data=[{
        "id": u.id,
        "name": u.name,
        "role": u.role,
        "branch_id": u.branch_id,
        "branch_name": branch_map.get(u.branch_id) or "",
        # 소속배지 정책(9/7): region 우선 → branch_name 폴백
        "region": getattr(u, 'region', '') or "",
        "academy_type": getattr(u, 'academy_type', '') or "",
    } for u in users])


# ============================================================
# 채팅 파일 업로드
# ============================================================

import uuid
from pathlib import Path
from fastapi import UploadFile, File, Request

CHAT_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "chat"
CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/rooms/{room_id}/upload")
async def upload_chat_file(
    room_id: int,
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """채팅방 파일 업로드"""
    from fastapi.responses import JSONResponse

    # 방 존재 확인
    room = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    if not room.scalar_one_or_none():
        return JSONResponse(status_code=404, content={"status": "error", "detail": "방을 찾을 수 없습니다."})

    # 참여 확인
    participant = await db.execute(
        select(ChatParticipant).where(
            ChatParticipant.room_id == room_id,
            ChatParticipant.user_id == current_user["id"]
        )
    )
    if not participant.scalar_one_or_none():
        return JSONResponse(status_code=403, content={"status": "error", "detail": "참여하지 않은 방입니다."})

    # 파일 저장
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = CHAT_UPLOAD_DIR / safe_name
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"/uploads/chat/{safe_name}"

    # 메시지 생성
    msg = ChatMessage(
        room_id=room_id,
        sender_id=current_user["id"],
        message_type="file",
        content=file.filename or safe_name,
        file_url=file_url,
        file_name=file.filename or safe_name,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return JSONResponse(content={
        "status": "success",
        "data": {
            "id": msg.id,
            "file_url": file_url,
            "file_name": file.filename or safe_name,
            "file_size": len(content),
        }
    })


# ============================================================
# WebSocket
# ============================================================

@router.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: int,
    token: str = Query(...),
    db=Depends(get_db),
):
    """채팅 WebSocket 연결"""
    # JWT 검증
    try:
        from app.core.security import decode_token
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        user_role = payload.get("role", "")
        user_name = payload.get("name", "")
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 방 접근 권한 확인
    can_access = await _can_access_room(room_id, {"id": user_id, "role": user_role}, db)
    if not can_access:
        await websocket.close(code=4003, reason="Forbidden")
        return

    # 연결
    await ws_manager.connect(websocket, room_id, user_id)

    # 입장 시스템 메시지
    system_msg = ChatMessage(
        room_id=room_id,
        sender_id=user_id,
        message_type="system",
        content=f"{user_name}님이 입장했습니다."
    )
    db.add(system_msg)
    await db.commit()
    await db.refresh(system_msg)

    await ws_manager.broadcast(room_id, {
        "type": "system",
        "data": {"content": system_msg.content, "message_id": system_msg.id}
    }, exclude_user_id=None)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg_data = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager.send_personal(websocket, {
                    "type": "error",
                    "data": {"message": "JSON 형식이 올바르지 않습니다."}
                })
                continue

            msg_type = msg_data.get("type", "")
            payload = msg_data.get("data", {})

            if msg_type == "message":
                content = payload.get("content", "").strip()
                message_type = payload.get("message_type", "text")
                file_url = payload.get("file_url", "")
                file_name = payload.get("file_name", "")

                if not content and message_type == "text":
                    continue

                # DB 저장
                chat_msg = ChatMessage(
                    room_id=room_id,
                    sender_id=user_id,
                    message_type=message_type,
                    content=content,
                    file_url=file_url,
                    file_name=file_name,
                )
                db.add(chat_msg)
                await db.commit()
                await db.refresh(chat_msg)

                # 방 updated_at 갱신
                room_result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
                room = room_result.scalar_one_or_none()
                if room:
                    room.updated_at = datetime.utcnow()
                    await db.commit()

                # 브로드캐스트
                await ws_manager.broadcast(room_id, {
                    "type": "message",
                    "data": {
                        "id": chat_msg.id,
                        "sender_id": user_id,
                        "sender_name": user_name,
                        "sender_role": user_role,
                        "content": content,
                        "message_type": message_type,
                        "file_url": file_url,
                        "file_name": file_name,
                        "created_at": str(chat_msg.created_at),
                    }
                })

            elif msg_type == "read":
                message_id = payload.get("message_id")
                if message_id:
                    # last_read_id 갱신
                    part_result = await db.execute(
                        select(ChatParticipant).where(
                            and_(ChatParticipant.room_id == room_id, ChatParticipant.user_id == user_id)
                        )
                    )
                    participant = part_result.scalar_one_or_none()
                    if participant and message_id > participant.last_read_id:
                        participant.last_read_id = message_id
                        await db.commit()

                    await ws_manager.broadcast(room_id, {
                        "type": "read_receipt",
                        "data": {
                            "user_id": user_id,
                            "user_name": user_name,
                            "last_read_id": message_id,
                        }
                    }, exclude_user_id=user_id)

            elif msg_type == "typing":
                await ws_manager.broadcast(room_id, {
                    "type": "typing",
                    "data": {
                        "user_id": user_id,
                        "user_name": user_name,
                        "is_typing": payload.get("is_typing", False),
                    }
                }, exclude_user_id=user_id)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(room_id, user_id)
        # 퇴장 시스템 메시지
        exit_msg = ChatMessage(
            room_id=room_id,
            sender_id=user_id,
            message_type="system",
            content=f"{user_name}님이 퇴장했습니다."
        )
        db.add(exit_msg)
        await db.commit()
        await ws_manager.broadcast(room_id, {
            "type": "system",
            "data": {"content": exit_msg.content}
        }, exclude_user_id=None)


# ============================================================
# 메시지 수정/삭제 API
# ============================================================

@router.put("/messages/{message_id}")
async def edit_message(
    message_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """메시지 내용 수정 (작성자만 가능)"""
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다.")
    if msg.sender_id != current_user["id"] and current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")
    if msg.message_type == "system":
        raise HTTPException(status_code=400, detail="시스템 메시지는 수정할 수 없습니다.")

    new_content = data.get("content", "").strip()
    if not new_content:
        raise HTTPException(status_code=400, detail="내용이 필요합니다.")

    msg.content = new_content
    await db.commit()

    await ws_manager.broadcast(msg.room_id, {
        "type": "edit",
        "data": {
            "id": msg.id,
            "content": msg.content,
            "edited_at": str(datetime.utcnow()),
        }
    })
    return ApiResponse(message="메시지가 수정되었습니다.")


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """메시지 삭제 (작성자 또는 관리자만 가능)"""
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다.")
    if msg.sender_id != current_user["id"] and current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")
    if msg.message_type == "system":
        raise HTTPException(status_code=400, detail="시스템 메시지는 삭제할 수 없습니다.")

    await db.delete(msg)
    await db.commit()

    await ws_manager.broadcast(msg.room_id, {
        "type": "delete",
        "data": {"id": message_id}
    })
    return ApiResponse(message="메시지가 삭제되었습니다.")
