/**
 * 누비다플랫폼 — SSE 실시간 알림 클라이언트
 * 
 * 사용법:
 *   const sse = new SSEClient(token);
 *   sse.on('portfolio_submitted', (data) => { showToast(data); });
 *   sse.on('*', (msg) => { console.log('SSE:', msg); });
 *   sse.connect();
 * 
 * 로그아웃 시:
 *   sse.disconnect();
 */
class SSEClient {
    constructor(token) {
        this.token = token;
        this.eventSource = null;
        this.handlers = {};
        this.reconnectDelay = 3000;
        this.maxReconnectDelay = 30000;
        this.connected = false;
        this._reconnectTimer = null;
    }

    /**
     * SSE 서버에 연결
     */
    connect() {
        if (this.eventSource) this.disconnect();
        
        const url = '/api/v1/sse/stream';
        this.eventSource = new EventSource(url);
        
        this.eventSource.onopen = () => {
            this.connected = true;
            this.reconnectDelay = 3000;
            console.log('🔔 SSE 알림 연결됨');
            // 연결 성공 시 읽지 않은 알림 조회
            this._fetchNotifications();
        };

        this.eventSource.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'connected') return;
                
                // 특정 타입 핸들러 호출
                if (this.handlers[msg.type]) {
                    this.handlers[msg.type](msg.data);
                }
                // 전체 핸들러 호출
                if (this.handlers['*']) {
                    this.handlers['*'](msg);
                }
                // 알림 UI 업데이트
                this._updateBadge();
            } catch (e) {
                console.warn('SSE 메시지 파싱 오류:', e);
            }
        };

        this.eventSource.onerror = () => {
            this.connected = false;
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            // 지수 백오프로 재연결
            this._reconnectTimer = setTimeout(() => {
                this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
                this.connect();
            }, this.reconnectDelay);
        };
    }

    /**
     * 이벤트 타입별 핸들러 등록
     * @param {string} eventType - 이벤트 타입 ('*'는 모든 이벤트)
     * @param {Function} callback - 콜백 함수
     */
    on(eventType, callback) {
        this.handlers[eventType] = callback;
    }

    /**
     * SSE 연결 종료
     */
    disconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this.connected = false;
        console.log('🔔 SSE 연결 종료');
    }

    /**
     * 읽지 않은 알림 조회
     */
    async _fetchNotifications() {
        try {
            const resp = await fetch('/api/v1/sse/notifications', {
                headers: { 'Authorization': 'Bearer ' + this.token }
            });
            const data = await resp.json();
            if (data.status === 'success' && data.data.notifications.length > 0) {
                this._updateBadge(data.data.notifications.length);
            }
        } catch (e) {
            console.warn('알림 조회 실패:', e);
        }
    }

    /**
     * 읽지 않은 알림 배지 업데이트
     */
    async _updateBadge() {
        try {
            const resp = await fetch('/api/v1/sse/notifications', {
                headers: { 'Authorization': 'Bearer ' + this.token }
            });
            const data = await resp.json();
            if (data.status === 'success') {
                const count = data.data.total || 0;
                // 타이틀 업데이트 (알림 개수 표시)
                const badge = document.getElementById('notifBadge');
                if (badge) {
                    badge.textContent = count > 99 ? '99+' : count;
                    badge.style.display = count > 0 ? 'flex' : 'none';
                }
            }
        } catch (e) {
            // 조용히 실패
        }
    }
}

/**
 * 알림 토스트 표시 (SSE 메시지 수신 시)
 */
function showNotificationToast(title, message, type) {
    // 기존 토스트가 있으면 제거
    const existing = document.querySelector('.notif-toast');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = 'notif-toast';
    
    const icons = {
        portfolio_submitted: '📁',
        payment_completed: '💳',
        class_started: '🎥',
        grade_updated: '📊',
    };
    const icon = icons[type] || '🔔';
    
    toast.innerHTML = `
        <div class="notif-toast-icon">${icon}</div>
        <div class="notif-toast-body">
            <div class="notif-toast-title">${esc(title)}</div>
            <div class="notif-toast-msg">${esc(message)}</div>
        </div>
        <button class="notif-toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    
    // 스타일 추가
    toast.style.cssText = `
        position: fixed; top: 16px; right: 16px; z-index: 9999;
        display: flex; align-items: center; gap: 12px;
        padding: 12px 16px; background: #fff; border-radius: 12px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.15);
        border-left: 4px solid var(--md-primary, #1A73E8);
        max-width: 360px; animation: slideIn 0.3s ease;
        font-family: 'Noto Sans KR', sans-serif;
    `;
    
    document.body.appendChild(toast);
    
    // 5초 후 자동 제거
    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// 토스트 애니메이션 스타일
const style = document.createElement('style');
style.textContent = `
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
@keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
.notif-toast-icon { font-size: 1.5rem; flex-shrink: 0; }
.notif-toast-body { flex: 1; min-width: 0; }
.notif-toast-title { font-weight: 600; font-size: 0.875rem; color: #1a1a1a; }
.notif-toast-msg { font-size: 0.75rem; color: #666; margin-top: 2px; }
.notif-toast-close { background: none; border: none; font-size: 1.25rem; cursor: pointer; color: #999; padding: 0 4px; }
.notif-toast-close:hover { color: #333; }
`;
document.head.appendChild(style);
