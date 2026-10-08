/**
 * 누비다플랫폼 — API 호출 유틸리티
 */

const API_BASE = (window.location.protocol === 'https:' ? 'https:' : 'http:') + '//' + window.location.host + '/api/v1';

async function api(method, path, data = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };

    const token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }

    // 타임아웃 — AI 답변 생성은 오래 걸릴 수 있어 경로별로 다르게 적용
    //   /ai/chat : LLM 생성(백엔드 LLM_TIMEOUT=180초) → 넉넉히 240초
    //   그 외     : 일반 API → 45초
    const isAiChat = /\/ai\/chat\b/.test(path);
    const timeoutMs = isAiChat ? 240000 : 45000;
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(function () { timedOut = true; controller.abort(); }, timeoutMs);
    options.signal = controller.signal;

    let res;
    try {
        res = await fetch(`${API_BASE}${path}`, options);
    } catch (e) {
        clearTimeout(timeout);
        // AbortError(타임아웃) / 네트워크 실패를 사용자 친화적 메시지로 변환
        if (timedOut || (e && e.name === 'AbortError')) {
            throw new Error(isAiChat
                ? '답변이 너무 길어지고 있어요. 잠시 후 다시 시도해 주세요.'
                : '요청 시간이 초과되었어요. 네트워크 상태를 확인한 뒤 다시 시도해 주세요.');
        }
        throw new Error('서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.');
    }
    clearTimeout(timeout);

    const text = await res.text();
    let json;
    try { json = JSON.parse(text); } catch(e) { json = null; }

    // 401 Unauthorized: 정확한 HTTP 상태 코드 감지
    if (res.status === 401) {
        const detail = json?.detail || json?.message || '로그인이 필요합니다.';

        // 로그인 페이지일 때는 401을 정상 실패로 처리 (리다이렉트 금지)
        if (!window.location.pathname.includes('/login.html')) {
            // 🔒 이중로그인 방지 — 다른 기기 로그인으로 세션이 무효화된 경우 안내 후 로그아웃
            const isDuplicate = /다른\s*기기에서\s*로그인/.test(detail);
            if (isDuplicate) {
                try { alert('🔒 다른 기기에서 로그인되어 자동 로그아웃되었습니다.\n보안을 위해 다시 로그인해 주세요.'); } catch(e) {}
            }
            localStorage.removeItem('token');
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.href = '/pages/login.html';
        }
        throw new Error(detail);
    }

    if (!res.ok) {
        const detail = Array.isArray(json.detail) ? json.detail.map(d => d.msg || d.message).join('; ') : json.detail;
        throw new Error(json.message || detail || `오류 발생 (${res.status})`);
    }

    return json;
}

// 편의 메서드
window.apiGet    = (path) => api('GET', path);
window.apiPost   = (path, data) => api('POST', path, data);
window.apiPut    = (path, data) => api('PUT', path, data);
window.apiPatch  = (path, data) => api('PATCH', path, data);
window.apiDelete = (path) => api('DELETE', path);

/**
 * 페이지네이션 렌더링
 */
function renderPagination(containerId, pagination) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const { page, total_pages } = pagination;
    let html = '';

    if (page > 1) {
        html += `<button onclick="window.goToPage(${page - 1})">‹</button>`;
    }

    const start = Math.max(1, page - 2);
    const end = Math.min(total_pages, page + 2);
    for (let i = start; i <= end; i++) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="window.goToPage(${i})">${i}</button>`;
    }

    if (page < total_pages) {
        html += `<button onclick="window.goToPage(${page + 1})">›</button>`;
    }

    container.innerHTML = html;
}

/**
 * 알림 메시지 표시
 */
function showAlert(message, type = 'success') {
    // 기존 알림 제거 (누적 방지)
    document.querySelectorAll('.alert').forEach(function(el) { el.remove(); });
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;
    const container = document.querySelector('.main-content') || document.body;
    container.prepend(alertDiv);
    setTimeout(() => alertDiv.remove(), 4000);
}

/**
 * 모달 열기/닫기
 */
function openModal(id) { document.getElementById(id)?.classList.add('active'); }
function closeModal(id) { document.getElementById(id)?.classList.remove('active'); }

/**
 * 로딩 표시
 */
function showLoading(containerId) {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = '<div class="loading-spinner" style="margin:40px auto"></div>';
}

/**
 * Service Worker 등록 (PWA)
 */
// Service Worker — 아두이노 페이지에서는 비활성화 (캐시 문제 우회)
// 별도로 활성화 필요 시 주석 해제
/*
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/service-worker.js')
            .then(reg => console.log('[PWA] SW registered:', reg.scope))
            .catch(err => console.error('[PWA] SW registration failed:', err));
    });
}
*/

/**/

// Force unregister all active service workers and clear stale caches on reload
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(function(registrations) {
        for (let registration of registrations) {
            registration.unregister().then(function() {
                console.log('[PWA] Active SW unregistered successfully.');
            });
        }
    });
}
if ('caches' in window) {
    caches.keys().then(function(keys) {
        return Promise.all(keys.map(function(key) {
            return caches.delete(key);
        }));
    }).then(function() {
        console.log('[PWA] Stale caches deleted successfully.');
    });
}

