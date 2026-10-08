/**
 * 누비다플랫폼 — 인증 관리
 */

// 인증 준비 완료 후 실행될 콜백 목록
window._authReadyCallbacks = window._authReadyCallbacks || [];

/**
 * 인증 준비(refreshCurrentUser 완료) 후 실행할 콜백 등록
 * 이미 준비가 완료된 경우 즉시 실행됨
 * @param {Function} callback
 */
function onAuthReady(callback) {
    if (window._authReady) {
        callback();
    } else {
        window._authReadyCallbacks.push(callback);
    }
}

function isAuthenticated() {
    return !!(localStorage.getItem('token') || localStorage.getItem('access_token'));
}

function getCurrentUser() {
    try {
        return JSON.parse(localStorage.getItem('user'));
    } catch {
        return null;
    }
}

function requireAuth() {
    if (!isAuthenticated()) {
        window.location.href = '/pages/login.html';
    }
}

async function handleLogin(username, password) {
    const res = await apiPost('/auth/login', { username, password });
    const { access_token, user } = res.data;

    localStorage.setItem('token', access_token);
    localStorage.setItem('user', JSON.stringify(user));

    // 역할별 리다이렉트
    const roleRoutes = {
        'super_admin': '/pages/headquarters/dashboard.html',
        'admin': '/pages/headquarters/dashboard.html',
        'branch_admin': '/pages/branch/dashboard.html',
        'branch_manager': '/pages/branch/dashboard.html',
        'branch_staff': '/pages/branch/dashboard.html',
        'director': '/pages/director/dashboard.html',
        'student': '/pages/student/dashboard.html',
        'parent': '/pages/parent/dashboard.html',
    };
    window.location.href = roleRoutes[user.role] || '/pages/branch/dashboard.html';
}

function handleLogout() {
    // Push 구독 해제 (비동기 — 결과를 기다리지 않음)
    try {
        if (typeof unsubscribePush === 'function') {
            unsubscribePush();
        }
    } catch (e) { /* 무시 */ }

    localStorage.removeItem('token');
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    window.location.href = '/pages/login.html';
}

/**
 * 사이드바에 사용자 정보 표시
 */
function renderSidebarUser() {
    const user = getCurrentUser();
    if (!user) return;

    const nameEl = document.querySelector('.sidebar-footer .user-name');
    const roleEl = document.querySelector('.sidebar-footer .user-role');
    if (nameEl) nameEl.textContent = `${user.name}님 반갑습니다`;
    if (roleEl) {
        const code = user.registration_code ? `${user.registration_code}` : '';
        const codeDisplay = code ? ` ${code}` : '';
        const baseLabels = {
            'super_admin': '최고관리자',
            'admin': '관리자',
            'branch_manager': '지사 관리자',
            'branch_admin': '지사 관리자',
            'branch_staff': '지사 직원',
            'director': '공부방장',
            'teacher': '강사',
            'student': '학생',
            'parent': '학부모',
        };
        const baseLabel = baseLabels[user.role] || user.role;
        roleEl.textContent = `${baseLabel}${codeDisplay}`;
    }
}

/**
 * 페이지 로드 시 최신 user 정보로 localStorage 갱신 (재로그인 불필요)
 * 기존 localStorage.user 에 registration_code 등 최신 필드가 누락된 경우 대비
 */
async function refreshCurrentUser() {
    if (!isAuthenticated()) {
        _signalAuthReady();
        return;
    }
    try {
        const res = await apiGet('/auth/me');
        if (res && res.data) {
            localStorage.setItem('user', JSON.stringify(res.data));
            renderSidebarUser();
        }
    } catch (e) {
        console.warn('사용자 정보 갱신 실패 — 새로고침 또는 재로그인 필요', e);
    } finally {
        _signalAuthReady();
    }
}

/**
 * refreshCurrentUser 완료 후 등록된 모든 콜백 실행
 */
function _signalAuthReady() {
    if (window._authReady) return;
    window._authReady = true;
    const cbs = window._authReadyCallbacks || [];
    window._authReadyCallbacks = [];
    cbs.forEach(function(cb) {
        try { cb(); } catch (e) { console.warn('onAuthReady 콜백 오류:', e); }
    });
}

// 페이지 로드 시 자동 실행 (script가 body 하단에 있으므로 DOM 준비됨)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshCurrentUser);
} else {
    refreshCurrentUser();
}
