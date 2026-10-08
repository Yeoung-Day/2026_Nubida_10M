"""
SSE 이벤트 버스 — 인메모리 pub/sub
"""
import asyncio
import json
from typing import Dict, Set
from datetime import datetime

class EventBus:
    """SSE 이벤트 버스 — 구독자에게 실시간 이벤트 전달"""
    
    def __init__(self):
        self._subscribers: Dict[int, Set[asyncio.Queue]] = {}
    
    def subscribe(self, user_id: int) -> asyncio.Queue:
        """사용자별 이벤트 큐 구독"""
        if user_id not in self._subscribers:
            self._subscribers[user_id] = set()
        queue = asyncio.Queue()
        self._subscribers[user_id].add(queue)
        return queue
    
    def unsubscribe(self, user_id: int, queue: asyncio.Queue):
        """구독 해제"""
        if user_id in self._subscribers:
            self._subscribers[user_id].discard(queue)
            if not self._subscribers[user_id]:
                del self._subscribers[user_id]
    
    async def publish(self, user_id: int, event_type: str, data: dict):
        """특정 사용자에게 이벤트 발행"""
        if user_id in self._subscribers:
            message = json.dumps({
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            })
            for queue in self._subscribers[user_id]:
                await queue.put(message)
    
    async def broadcast(self, event_type: str, data: dict, role: str = None):
        """모든 구독자 또는 특정 역할 구독자에게 브로드캐스트"""
        # For simplicity, publish to all subscribers
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        })
        for queues in self._subscribers.values():
            for queue in queues:
                await queue.put(message)

event_bus = EventBus()
