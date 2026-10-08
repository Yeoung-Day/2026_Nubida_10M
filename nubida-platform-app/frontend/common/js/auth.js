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
        // 비로그인 상태로 보호된 사용자 페이지 접근 시 → 메인페이지로 이동
        // (메인페이지에서 공지/서비스를 둘러본 뒤 로그인할 수 있도록)
        window.location.replace('/');
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
    if (nameEl) nameEl.textContent = `${user.name}${user.name.endsWith('님') ? '' : '님'} 반갑습니다`;
    if (roleEl) {
        const code = user.registration_code ? `${user.registration_code}` : '';
        const codeDisplay = code ? ` ${code}` : '';
        const baseLabels = {
            'super_admin': '최고관리자',
            'admin': '관리자',
            'branch_manager': '에듀케어',
            'branch_admin': '에듀케어',
            'branch_staff': '에듀케어 직원',
            'director': '원장',
            'teacher': '강사',
            'student': '학생',
            'parent': '학부모',
        };
        const baseLabel = baseLabels[user.role] || user.role;
        roleEl.textContent = `${baseLabel}${codeDisplay}`;
    }
}

/* ============================================================
   세션 유효성 감시 (이중로그인 대응)
   - 다른 기기에서 로그인하면 이 기기의 토큰이 즉시 무효화됨(401)
   - 탭이 다시 활성화될 때 + 주기적으로 /auth/me 를 확인하여
     무효화된 세션을 빠르게 감지 → 로그인 페이지로 이동
   ============================================================ */
(function initSessionWatch() {
    if (window.__nubidaSessionWatch) return;
    window.__nubidaSessionWatch = true;

    var CHECK_INTERVAL = 60000;   // 60초
    var _lastCheck = 0;
    var _checking = false;

    async function checkSession(force) {
        if (_checking) return;
        if (!isAuthenticated()) return;
        // 로그인/공개 페이지에서는 검사하지 않음
        var p = window.location.pathname;
        if (p.indexOf('login.html') !== -1 || p.indexOf('register.html') !== -1 ||
            p.indexOf('find-id.html') !== -1 || p.indexOf('find-password.html') !== -1) return;

        var now = Date.now();
        if (!force && now - _lastCheck < CHECK_INTERVAL - 5000) return;
        _lastCheck = now;
        _checking = true;

        try {
            // 401 이면 api() 내부에서 토큰 제거 + 로그인 페이지 이동 + alert 처리됨
            await apiGet('/auth/me');
        } catch (e) {
            // 401 은 api() 가 처리. 그 외 네트워크 오류는 무시(오프라인 등)
        } finally {
            _checking = false;
        }
    }

    // 1) 주기적 확인
    setInterval(function() { checkSession(false); }, CHECK_INTERVAL);

    // 2) 탭이 다시 보일 때 즉시 확인 (다른 기기 로그인 후 돌아온 경우)
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') checkSession(true);
    });

    // 3) 창 포커스 복귀 시
    window.addEventListener('focus', function() { checkSession(true); });

    // 4) 페이지 로드 후 첫 확인 (약간 지연 — 초기 로딩 방해 방지)
    setTimeout(function() { checkSession(true); }, 3000);
})();

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
        applyMachineLock();   // 사용자 정보 갱신 후 누비다머신 잠금 UI 적용
        _signalAuthReady();
    }
}

/* ============================================================
   누비다머신 잠금 가드 (원장 잠금 시 학생 전체 차단)
   - 사이드바/탑네비/드롭다운의 ml-studio·ml-arduino 링크 숨김 (잠금 시)
   - 잠금 해제 시 숨긴 링크 원복 → 다시 표시 (data-ml-hidden 마커 기반)
   - ml-studio.html / ml-arduino.html 직접 URL 진입 시 대시보드로 리다이렉트
   - 백엔드 /api/v1/ml/* 403 가드의 1차(프론트) 방어선
   ============================================================ */
function applyMachineLock() {
    var user = getCurrentUser();
    var locked = !!(user && user.role === 'student' && user.nubida_machine_locked);

    // 0) 잠금 해제 상태 → 이 함수가 숨긴 요소만 원복 (해제 시 메뉴 다시 표시)
    if (!locked) {
        document.querySelectorAll('[data-ml-hidden="1"]').forEach(function(el) {
            el.style.display = '';
            el.removeAttribute('data-ml-hidden');
        });
        return;
    }

    // 1) 직접 URL 진입 차단 — 누비다머신 전용 페이지
    var path = window.location.pathname || '';
    if (/(^|\/)ml-(studio|arduino)\.html$/i.test(path)) {
        alert('🔒 누비다머신 사용이 원장님에 의해 잠금 처리되었습니다.\n자세한 내용은 원장님께 문의해 주세요.');
        window.location.replace('/pages/student/dashboard.html');
        return;
    }

    // 2) 모든 ml 링크 숨김 (사이드바 / 탑네비 / 드롭다운 공통)
    document.querySelectorAll('a[href*="ml-studio.html"], a[href*="ml-arduino.html"]').forEach(function(a) {
        if (a.style.display !== 'none') {
            a.style.display = 'none';
            a.setAttribute('data-ml-hidden', '1');
        }
    });

    // 3) 드롭다운 메뉴에 ml 항목만 있어 비어 버린 경우 → 드롭다운 전체 숨김
    document.querySelectorAll('.top-navbar-dropdown').forEach(function(dd) {
        var items = dd.querySelectorAll('.top-navbar-dropdown-item');
        var hasAny = false;
        items.forEach(function(i) { if (i.style.display !== 'none') hasAny = true; });
        if (items.length && !hasAny) {
            var trigger = dd.querySelector('.top-nav-item');
            if (trigger && trigger.style.display !== 'none') {
                trigger.style.display = 'none';
                trigger.setAttribute('data-ml-hidden', '1');
            }
        }
    });
}

// 페이지 로드 즉시 1차 적용 (저장된 user 기준 — 빠른 차단), 이후 refreshCurrentUser 응답 시 2차 적용
applyMachineLock();

/* ============================================================
   ⚡ 잠금 간헐 노출 수정 (09/09, 미러 반영)
   잠금(누비다머신 정지) 기준은 서버(/auth/me)의 최신 user 값.
   그런데 일부 학생 페이지는 refreshCurrentUser()를 스스로 호출하지 않아
   localStorage에 남은 과거(잠금 전) 정보로만 판정 → 누비다머신 링크가
   그대로 보이는 간헐 문제가 있었다.
   → 인증 상태면 auth.js가 자동으로 최신 user/잠금을 한 번 가져와
     applyMachineLock()을 재적용하도록 함 (응답 완료 시 내부에서 처리).
   ============================================================ */
if (isAuthenticated()) {
    // 중복 중계 방지 (이미 페이지가 개별 호출해 준비된 경우 재요청 생략)
    if (!window._authRefreshAuto) {
        window._authRefreshAuto = true;
        refreshCurrentUser();
    } else {
        applyMachineLock();
    }
} else {
    _signalAuthReady();
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
