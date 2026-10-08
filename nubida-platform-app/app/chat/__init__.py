"""WebSocket Connection Manager for chat"""
from fastapi import WebSocket
from typing import Dict, Set
import json


class ConnectionManager:
    """채팅방 WebSocket 연결 관리"""

    def __init__(self):
        # active_connections[room_id][user_id] = WebSocket
        self.active_connections: Dict[int, Dict[int, WebSocket]] = {}

    async def connect(self, ws: WebSocket, room_id: int, user_id: int):
        await ws.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][user_id] = ws

    async def disconnect(self, room_id: int, user_id: int):
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast(self, room_id: int, message: dict, exclude_user_id: int = None):
        """방 내 모든 연결에 메시지 전송"""
        if room_id not in self.active_connections:
            return
        disconnected = []
        data = json.dumps(message, ensure_ascii=False, default=str)
        for uid, ws in self.active_connections[room_id].items():
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(uid)
        for uid in disconnected:
            await self.disconnect(room_id, uid)

    async def send_personal(self, ws: WebSocket, message: dict):
        """특정 WebSocket에만 전송"""
        try:
            data = json.dumps(message, ensure_ascii=False, default=str)
            await ws.send_text(data)
        except Exception:
            pass

    def get_room_users(self, room_id: int) -> Set[int]:
        """방 내 접속 중인 사용자 ID 목록"""
        if room_id not in self.active_connections:
            return set()
        return set(self.active_connections[room_id].keys())

    def is_connected(self, room_id: int, user_id: int) -> bool:
        """특정 사용자가 방에 연결되어 있는지 확인"""
        return room_id in self.active_connections and user_id in self.active_connections[room_id]


# 싱글톤 인스턴스
manager = ConnectionManager()
