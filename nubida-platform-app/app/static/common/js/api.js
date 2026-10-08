/**
 * 누비다플랫폼 — API 호출 유틸리티
 */

const API_BASE = '/api/v1';

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

    const res = await fetch(`${API_BASE}${path}`, options);

    // 401 Unauthorized: 정확한 HTTP 상태 코드 감지 → 토큰/사용자 정보 제거 후 로그인 페이지로 리다이렉트
    if (res.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/pages/login.html';
        throw new Error('Unauthorized');
    }

    const text = await res.text();
    let json;
    try {
        json = JSON.parse(text);
    } catch (parseErr) {
        throw new Error(text || `서버 응답 오류 (${res.status})`);
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

