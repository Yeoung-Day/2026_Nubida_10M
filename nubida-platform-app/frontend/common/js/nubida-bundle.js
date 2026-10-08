// js/api.js
/**
 * 누비다플랫폼 — API 호출 유틸리티
 */

const API_BASE = '/api/v1';

async function api(method, path, data = null) {
    const options = {
        method,
        headers: {},
    };

    const token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    if (data && method !== 'GET') {
        if (data instanceof FormData) {
            // FormData: 브라우저가 Content-Type(multipart/form-data, boundary) 자동 설정
            options.body = data;
        } else {
            // JSON: Content-Type application/json 명시
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    options.signal = controller.signal;
    const res = await fetch(`${API_BASE}${path}`, options);
    clearTimeout(timeout);

    const text = await res.text();
    let json;
    try {
        json = JSON.parse(text);
    } catch (parseErr) {
        json = null;
    }

    // 401 Unauthorized: 정확한 HTTP 상태 코드 감지 → 토큰/사용자 정보 제거 후 로그인 페이지로 리다이렉트
    if (res.status === 401) {
        // 이중로그인 방지 — 다른 기기 로그인으로 세션 무효화 시 안내
        const _isDup = !!(json && /다른\s*기기에서\s*로그인/.test(json.detail || ''));
        if (_isDup && !window.location.pathname.includes('/login.html')) {
            try { alert('🔒 다른 기기에서 로그인되어 자동 로그아웃되었습니다.\n보안을 위해 다시 로그인해 주세요.'); } catch(e) {}
        }
        localStorage.removeItem('token');
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/pages/login.html';
        throw new Error('Unauthorized');
    }

    if (!json) {
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



// js/auth.js
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

// 페이지 로드 즉시 1차 적용 (저장된 user 기준 — 빠른 차단), 이후 refreshCurrentUser 응답 시 2차 적용
applyMachineLock();

// 페이지 로드 시 자동 실행 (script가 body 하단에 있으므로 DOM 준비됨)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshCurrentUser);
} else {
    refreshCurrentUser();
}


// js/utils.js
// ============================================================
// 누비다플랫폼 v2 Premium — 공통 유틸리티 함수
// Helper: 날짜/숫자 포맷, 보안, PWA 설치
// ============================================================

// ===== 숫자 포맷 =====
function formatNumber(n) {
    if (n == null) return '-';
    return Number(n).toLocaleString('ko-KR');
}

function formatCurrency(n) {
    if (n == null) return '-';
    return '₩' + Number(n).toLocaleString('ko-KR');
}

// ===== 날짜 포맷 =====
function formatDate(d) {
    if (!d) return '-';
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function formatDateTime(d) {
    if (!d) return '-';
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatTimeAgo(d) {
    if (!d) return '-';
    const ms = Date.now() - new Date(d).getTime();
    if (ms < 60000) return '방금 전';
    if (ms < 3600000) return `${Math.floor(ms / 60000)}분 전`;
    if (ms < 86400000) return `${Math.floor(ms / 3600000)}시간 전`;
    return formatDate(d);
}

// ===== HTML 이스케이프 (XSS 방지) =====
function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ===== 오늘 날짜 표시 =====
function displayToday() {
    const el = document.getElementById('todayDate');
    if (el) el.textContent = formatDateTime(new Date());
}

// ===== PWA 설치 프롬프트 =====
let deferredPrompt = null;
let installButton = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    showInstallButton();
});

function showInstallButton() {
    // 기존 설치 버튼이 있으면 표시
    installButton = document.getElementById('pwaInstallBtn');
    if (installButton) installButton.style.display = 'flex';
}

async function installPWA() {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    deferredPrompt = null;
    if (installButton) installButton.style.display = 'none';
}

window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    if (installButton) installButton.style.display = 'none';
});

// ===== 초기화 =====
document.addEventListener('DOMContentLoaded', () => {
    displayToday();
    // 매 60초마다 시간 갱신
    setInterval(displayToday, 60000);
    // 반응형 사이드바 핸들러 추가
    initResponsive();
});

// ===== 반응형 사이드바 토글 =====
let sidebarOverlay = null;

function initResponsive() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    
    // 오버레이 생성 (사이드바 뒤)
    if (!sidebarOverlay) {
        sidebarOverlay = document.createElement('div');
        sidebarOverlay.className = 'sidebar-overlay';
        sidebarOverlay.onclick = closeSidebar;
        document.body.appendChild(sidebarOverlay);
    }
    
    // Escape 키로 닫기
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeSidebar();
    });
    
    // 윈도우 리사이즈 감지
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (window.innerWidth > 1024) closeSidebar();
        }, 150);
    });
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
    if (sidebarOverlay) {
        sidebarOverlay.classList.toggle('visible');
    }
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.remove('open');
    if (sidebarOverlay) sidebarOverlay.classList.remove('visible');
}
console.log('[utils.js] loaded');


// js/pages-student.js
// ============================================================
// 누비다플랫폼 v2 Premium — 학생학습(Student) 페이지 스크립트
// API: student/dashboard, courses, scores, schedule, attendance
// ============================================================

// ===== 내장 유틸리티 (SW/캐시 문제로 외부 의존 제거) =====
if (typeof window.esc !== 'function') {
    window.esc = function(str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    };
}
if (typeof window.formatNumber !== 'function') {
    window.formatNumber = function(n) {
        if (n == null) return '-';
        return Number(n).toLocaleString('ko-KR');
    };
}

// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: HTML 설정 =====
function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

// ===== Helper: 테이블 렌더링 =====
function renderTable(tbodyId, data, columns) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    if (!data || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-tertiary);padding:24px">데이터가 없습니다.</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(row => {
        const cells = columns.map(col => {
            const val = col.render ? col.render(row[col.key]) : (row[col.key] ?? '-');
            return `<td>${val}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');
}

// ===== Helper: 상태 배지 =====
function statusBadge(status) {
    const map = {
        'active':    ['success', '활성'],
        'inactive':  ['warning', '비활성'],
        'pending':   ['warning', '대기'],
        'completed': ['success', '완료'],
        'failed':    ['danger', '실패'],
        'published': ['success', '발행'],
        'draft':     ['warning', '임시'],
        'in_progress': ['info', '진행중'],
        'not_started': ['warning', '시작전'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 등급 표시 =====
function gradeBadge(grade) {
    const map = {
        'A': 'success', 'A+': 'success', 'A0': 'success',
        'B': 'info', 'B+': 'info', 'B0': 'info',
        'C': 'warning',
        'D': 'danger',
        'F': 'danger',
    };
    const cls = map[grade] || 'info';
    return `<span class="badge badge-${cls}">${esc(grade)}</span>`;
}

document.addEventListener('DOMContentLoaded', () => {
    requireAuth();
    renderSidebarUser();
    initPage();
});

function initPage() {
    const page = window.location.pathname.split('/').pop().replace('.html', '');
    switch(page) {
        case 'dashboard': loadDashboard(); break;
        case 'courses': loadCourses(); break;
        case 'grades': loadGrades(); break;
        case 'portfolio': loadPortfolio(); break;
        case 'timetable': loadTimetable(); break;
        case 'classroom': loadClassroom(); break;
        case 'videos': loadVideos(); break;
        case 'learning': /* no-op, learning.html has its own JS */ break;
    }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        const res = await apiGet('/student/dashboard');
        const d = res?.data || {};
        setText('totalCourses', formatNumber(d?.total_courses || 0));
        setText('completedLessons', formatNumber(d?.completed_lessons || 0));
        setText('avgGrade', d?.avg_grade || '-');
        setText('attendanceRate', (d?.attendance_rate != null) ? d.attendance_rate + '%' : '-');

        // 내 강좌 목록
        const myCoursesEl = document.getElementById('myCourses');
        if (myCoursesEl && d?.recent_courses) {
            if (d.recent_courses.length === 0) {
                myCoursesEl.innerHTML = '<div class="empty-state"><div class="icon">📚</div><p>수강 중인 강좌가 없습니다.</p></div>';
            } else {
                myCoursesEl.innerHTML = d.recent_courses.map(c => `
                    <div class="list-item" style="padding:var(--space-4);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);margin-bottom:var(--space-3);transition:all 0.2s">
                        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                            <div class="list-item-title">${esc(c.name)}</div>
                            <span style="font-size:12px;font-weight:600;color:var(--text-tertiary)">${c.progress || 0}%</span>
                        </div>
                        <div class="list-item-sub" style="margin-bottom:10px">${esc(c.teacher || '')}</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width:${c.progress || 0}%"></div>
                        </div>
                    </div>
                `).join('');
            }
        }

        // 오늘 시간표
        const todayScheduleEl = document.getElementById('todaySchedule');
        if (todayScheduleEl && d?.today_schedule) {
            if (d.today_schedule.length === 0) {
                todayScheduleEl.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>오늘은 수업이 없습니다.</p></div>';
            } else {
                todayScheduleEl.innerHTML = d.today_schedule.map(s => `
                    <div class="list-item">
                        <div class="list-item-title">${esc(s.time)} — ${esc(s.course)}</div>
                        <div class="list-item-sub">${esc(s.teacher || '')} · ${esc(s.room || '')}</div>
                    </div>
                `).join('');
            }
        }

        // 최근 성적
        const gradeData = d?.recent_scores || [];
        const gradeColumns = [
            { key: 'exam_name', render: v => esc(v) },
            { key: 'course_name', render: v => esc(v) },
            { key: 'score', render: v => v != null ? v : '-' },
            { key: 'grade', render: v => v ? gradeBadge(v) : '-' },
            { key: 'date', render: v => formatDate(v) },
        ];
        renderTable('recentGradeBody', gradeData, gradeColumns);
        
        // 최근 포트폴리오
        loadRecentPortfolios();
    } catch(e) { console.error('Dashboard error:', e); }
}

async function loadRecentPortfolios() {
    try {
        const res = await apiGet('/portfolio');
        const items = Array.isArray(res) ? res : (res?.data || res?.items || []);
        const container = document.getElementById('recentPortfolios');
        if (!container) return;
        
        if (!items || items.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="icon">📖</div><p>아직 작성한 학습 노트가 없습니다.</p></div>';
            return;
        }
        
        const recent = items.slice(0, 5);
        container.innerHTML = recent.map(p => `
            <div class="list-item" style="padding:var(--space-3) 0;border-bottom:1px solid var(--border-subtle);cursor:pointer" onclick="window.location.href='portfolio.html'">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div class="list-item-title">${esc(p.title || '제목 없음')}</div>
                        <div class="list-item-sub">${esc(p.subject || '기타')} · ${formatDate(p.created_at)}</div>
                    </div>
                    <span class="badge badge-${p.status === 'published' ? 'success' : 'warning'}">${p.status === 'published' ? '발행' : '임시'}</span>
                </div>
            </div>
        `).join('');
    } catch(e) {
        console.error('Recent portfolios error:', e);
    }
}


// ============================================================
// 강좌 목록
// ============================================================
window.allCourses = [];

async function loadCourses() {
    try {
        const res = await apiGet('/student/catalog');
        allCourses = Array.isArray(res) ? res : (res?.data || res?.courses || []);
        updateCourseStats();
        renderCourses(allCourses);
    } catch(e) {
        console.error('Courses load error:', e);
        setHTML('courseList', '<div class="empty-state"><div class="icon">⚠️</div><p>강좌 정보를 불러올 수 없습니다.</p></div>');
    }
}

function filterCourses() {
    const q = (document.getElementById('courseSearch')?.value || '').trim().toLowerCase();
    const filtered = q ? allCourses.filter(c =>
        (c.name || '').toLowerCase().includes(q) ||
        (c.teacher || '').toLowerCase().includes(q)
    ) : allCourses;
    renderCourses(filtered);
}

function updateCourseStats() {
    const total = allCourses.length;
    const inProgress = allCourses.filter(c => c.status === 'active' || c.status === 'in_progress' || !c.status).length;
    const completed = allCourses.filter(c => c.status === 'completed').length;
    setText('totalCourses', total);
    setText('weekClasses', inProgress);
    setText('completionRate', total > 0 ? Math.round(completed / total * 100) + '%' : '0%');
}

function renderCourses(courses) {
    const container = document.getElementById('courseList');
    if (!container) return;

    if (!courses || courses.length === 0) {
        container.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="icon">📖</div><p>검색 결과가 없습니다.</p></div>';
        return;
    }

    container.innerHTML = courses.map(c => {
        const progress = c.progress || c.progress_pct || 0;
        const status = c.status || 'active';
        const totalMats = c.material_count || 0;
        const completedCnt = c.completed_count || 0;
        // progress_pct 기반 상태: 100% = 완료, 0% = 수강전, 그외 = 진행중
        const statusLabel = (totalMats === 0) ? '자료 없음'
            : (progress >= 100) ? '완료'
            : (completedCnt > 0) ? '진행중'
            : '수강 전';
        return `
            <div class="card course-card">
                <div class="card-body" onclick="showCourseDetail('${c.id}')" style="cursor:pointer">
                    <div class="flex-between mb-8">
                        <h3 class="course-card-title">${esc(c.name || c.title || '')}</h3>
                        ${statusBadge(status)}
                    </div>
                    <div class="small-text mb-8">📘 ${esc(c.description || '')}</div>
                    <div class="small-text mb-8">📦 자료 ${c.material_count || 0}개</div>
                    <div class="progress-bar mb-8">
                        <div class="progress-fill" style="width:${progress}%"></div>
                    </div>
                    <div class="flex-between small-text">
                        <span>진행률 ${progress}%</span>
                        <span>${statusLabel}</span>
                    </div>
                </div>
                <div class="card-footer" style="padding:12px 20px;border-top:1px solid var(--border-subtle)">
                    <a href="learning.html?course_id=${c.id}" class="btn btn-primary btn-sm" style="text-decoration:none;width:100%;text-align:center">
                        📚 학습하기
                    </a>
                </div>
            </div>
        `;
    }).join('');
}

async function showCourseDetail(courseId) {
    try {
        const res = await apiGet(`/student/courses/${courseId}/materials`);
        const course = allCourses.find(c => String(c.id) === String(courseId));
        const materials = Array.isArray(res) ? res : (res?.data || res?.materials || []);
        const assignmentsRes = await apiGet(`/student/courses/${courseId}/assignments`).catch(() => null);
        const assignments = assignmentsRes ? (Array.isArray(assignmentsRes) ? assignmentsRes : (assignmentsRes?.data || assignmentsRes?.assignments || [])) : [];

        setText('detailTitle', course ? esc(course.name || course.title || '') : '강좌 상세');

        let html = '';
        if (course) {
            html += `
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">강사</div>
                    <div>${esc(course.teacher || '-')}</div>
                </div>
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">일정</div>
                    <div>${esc(course.schedule || '-')}</div>
                </div>
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">진행률</div>
                    <div class="progress-bar"><div class="progress-fill" style="width:${course.progress || 0}%"></div></div>
                </div>
            `;
        }

        html += `<h3 class="mb-8">📎 학습 자료</h3>`;
        if (materials.length === 0) {
            html += `<div class="small-text mb-16" style="color:var(--text-tertiary)">등록된 자료가 없습니다.</div>`;
        } else {
            html += `<ul class="mb-16">`;
            materials.forEach(m => {
                const mt = m.material_type || 'document';
                const url = m.file_url || m.url || '#';
                const isVideo = mt === 'video' || (url.match(/\.(mp4|webm|mov)$/i));
                const isImage = mt === 'image' || (url.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i));
                const fileSize = m.file_size ? (m.file_size > 1048576 ? (m.file_size / 1048576).toFixed(1) + 'MB' : (m.file_size > 1024 ? (m.file_size / 1024).toFixed(0) + 'KB' : m.file_size + 'B')) : '';
                const typeIcon = { document: '📄', video: '🎬', image: '🖼️', link: '🔗' }[mt] || '📄';

                html += `<li class="list-item" style="padding:var(--space-2) 0;border-bottom:1px solid var(--border-subtle)">`;
                if (isVideo && url !== '#') {
                    html += `<div style="margin-bottom:4px">
                        <video controls style="width:100%;max-height:280px;border-radius:8px;background:#000" preload="metadata">
                            <source src="${esc(url)}" type="video/mp4">
                            브라우저가 영상 재생을 지원하지 않습니다.
                        </video>
                    </div>`;
                } else if (isImage && url !== '#') {
                    html += `<div style="margin-bottom:4px">
                        <img src="${esc(url)}" alt="${esc(m.title)}" style="max-width:100%;max-height:200px;border-radius:6px" loading="lazy">
                    </div>`;
                }
                html += `<div style="display:flex;justify-content:space-between;align-items:center">
                    <a href="${esc(url)}" target="_blank" class="list-item-title" style="text-decoration:none">
                        ${typeIcon} ${esc(m.title || m.name || '자료')}
                    </a>
                    <span style="font-size:11px;color:var(--text-tertiary)">${fileSize}</span>
                </div>`;
                if (url === '#') {
                    html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">🔗 ${esc(m.embed_url || '')}</div>`;
                }
                html += `</li>`;
            });
            html += `</ul>`;
        }

        html += `<h3 class="mb-8">📝 과제</h3>`;
        if (assignments.length === 0) {
            html += `<div class="small-text" style="color:var(--text-tertiary)">등록된 과제가 없습니다.</div>`;
        } else {
            html += `<ul>`;
            assignments.forEach(a => {
                html += `<li class="list-item" style="padding:var(--space-2) 0">
                    <span class="list-item-title">${esc(a.title || a.name || '과제')}</span>
                    <span class="list-item-sub">${a.due_date ? '마감: ' + formatDate(a.due_date) : ''}</span>
                </li>`;
            });
            html += `</ul>`;
        }

        setHTML('detailContent', html);
        openModal('courseDetailModal');
    } catch(e) {
        console.error('Course detail error:', e);
        showAlert('강좌 상세 정보를 불러올 수 없습니다.', 'danger');
    }
}

// ============================================================
// 성적 조회
// ============================================================
async function loadGrades() {
    try {
        const semester = document.getElementById('filterSemester')?.value || '';
        const path = semester ? `/student/scores?semester=${encodeURIComponent(semester)}` : '/student/scores';
        const res = await apiGet(path);
        const scores = Array.isArray(res) ? res : (res?.data || res?.scores || []);

        // Stat cards
        const totalExams = scores.length;
        const avgScore = totalExams > 0 ? Math.round(scores.reduce((s, r) => s + (r.score || 0), 0) / totalExams) : 0;
        const highestScore = totalExams > 0 ? Math.max(...scores.map(r => r.score || 0)) : 0;
        const lowestScore = totalExams > 0 ? Math.min(...scores.map(r => r.score || 0)) : 0;

        setText('totalExams', totalExams);
        setText('overallAvg', avgScore + '점');
        setText('bestScore', highestScore + '점');
        setText('recentTrend', totalExams > 0 ? scores[0]?.grade || '-' : '-');

        // Table
        const columns = [
            { key: 'exam_name', render: v => esc(v || '-') },
            { key: 'course_name', render: v => esc(v || '-') },
            { key: 'score', render: v => v != null ? v + '점' : '-' },
            { key: 'max_score', render: v => v != null ? v : '-' },
            { key: 'grade', render: v => v ? gradeBadge(v) : '-' },
            { key: 'rank', render: v => v != null ? v + '등' : '-' },
            { key: 'date', render: v => formatDate(v) },
        ];
        renderTable('gradeBody', scores, columns);
    } catch(e) {
        console.error('Grades load error:', e);
        setHTML('gradeBody', '<tr><td colspan="7" style="text-align:center;color:var(--text-tertiary);padding:24px">성적 정보를 불러올 수 없습니다.</td></tr>');
    }
}
// ============================================================
// 학습 노트 (포트폴리오) — 일기/노트 스타일, 사진 최대 4장
// ============================================================
let portfolioItems = [];

async function loadPortfolio() {
    try {
        const res = await apiGet('/portfolio');
        portfolioItems = Array.isArray(res) ? res : (res?.data || res?.items || []);
        
        // Calculate weekly count
        updateWeeklyCount();
        
        // Load enrolled courses for dropdown
        loadCourseSelector();
        
        renderJournal('all');
    } catch(e) {
        console.error('Portfolio load error:', e);
        setHTML('journalContainer', '<div class="empty-state"><div class="empty-icon">📖</div><h3>불러오기 실패</h3><p>잠시 후 다시 시도해주세요.</p></div>');
    }

    // Setup subject tab listeners
    const tabs = document.querySelectorAll('#subjectTabs .filter-tab');
    tabs.forEach(tab => {
        tab.onclick = function() {
            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            renderJournal(this.dataset.subject);
        };
    });
}

function updateWeeklyCount() {
    const el = document.getElementById('weeklyPortfolioCount');
    if (!el) return;
    const now = new Date();
    const startOfWeek = new Date(now);
    startOfWeek.setDate(now.getDate() - now.getDay());
    startOfWeek.setHours(0, 0, 0, 0);
    const count = portfolioItems.filter(p => {
        const d = p.created_at ? new Date(p.created_at) : null;
        return d && d >= startOfWeek;
    }).length;
    el.textContent = count;
}

let _enrolledCourses = [];

async function loadCourseSelector() {
    const sel = document.getElementById('courseFilter');
    const subj = document.getElementById('portSubject');
    const weeklySel = document.getElementById('weeklyCourse');
    if (!sel && !subj && !weeklySel) return;
    try {
        const res = await apiGet('/student/courses');
        _enrolledCourses = Array.isArray(res) ? res : (res?.data || []);
        
        // Populate filter dropdown
        if (sel) {
            const currentVal = sel.value;
            sel.innerHTML = '<option value="all">전체 강좌</option>';
            _enrolledCourses.forEach(c => {
                sel.innerHTML += `<option value="${esc(c.name || c.subject || '')}">${esc(c.name || '')}</option>`;
            });
            if (currentVal) sel.value = currentVal;
        }
        
        // Populate subject/ course selector in modal (daily)
        if (subj) {
            const currentVal = subj.value;
            subj.innerHTML = '<option value="">강좌 선택</option>';
            _enrolledCourses.forEach(c => {
                subj.innerHTML += `<option value="${esc(c.name || c.subject || '')}">${esc(c.name || '')}</option>`;
            });
            if (currentVal) subj.value = currentVal;
        }

        // Populate weekly course selector
        if (weeklySel) {
            const currentVal = weeklySel.value;
            weeklySel.innerHTML = '<option value="">강좌를 선택하세요</option>';
            _enrolledCourses.forEach(c => {
                weeklySel.innerHTML += `<option value="${esc(c.name || c.subject || '')}">${esc(c.name || '')}</option>`;
            });
            if (currentVal) weeklySel.value = currentVal;
        }
    } catch(e) {
        console.error('Load courses error:', e);
    }
}

function filterByCourse() {
    const sel = document.getElementById('courseFilter');
    const course = sel ? sel.value : 'all';
    renderJournal(course === 'all' ? 'all' : course);
}

function renderContentBoxes(content) {
    // Parse content into [label]: value sections
    var sections = [];
    var lines = (content || '').split('\n');
    var currentLabel = '';
    var currentText = [];
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        var labelMatch = line.match(/^\[([^\]]+)\]/);
        if (labelMatch) {
            if (currentLabel) {
                sections.push({label: currentLabel, text: currentText.join('\n').trim()});
            }
            currentLabel = labelMatch[1];
            currentText = [];
        } else {
            currentText.push(line);
        }
    }
    if (currentLabel) {
        sections.push({label: currentLabel, text: currentText.join('\n').trim()});
    }
    // If no labels found, return plain text
    if (sections.length === 0) {
        var preview = (content || '').substring(0, 120);
        return '<div class="journal-card-content">' + esc(preview) + (content && content.length > 120 ? '...' : '') + '</div>';
    }
    // Build boxes — icon map for all known section types
    var iconMap = {
        '오늘 배운 내용': '📖', '새로 알게 된 점': '💡', '어려웠던 점': '🤔',
        '주차': '📅', '이번 주 배운 내용': '📝', '코드': '💻',
        '실행 결과': '⚙️', '알고리즘 설명': '🔍', '배운 점': '💭'
    };
    var styleMap = {
        '코드': 'code-box',
        '실행 결과': 'output-box',
        '알고리즘 설명': 'algo-box',
        '배운 점': 'reflection-box'
    };
    var html = '';
    for (var j = 0; j < sections.length; j++) {
        var sec = sections[j];
        var icon = iconMap[sec.label] || '📌';
        var extraClass = styleMap[sec.label] || '';
        var textPreview = sec.text.substring(0, 80);
        html += '<div class="content-box ' + extraClass + '">';
        html += '<div class="content-box-label">' + icon + ' ' + esc(sec.label) + '</div>';
        if (sec.label === '코드') {
            html += '<pre class="content-box-code"><code>' + esc(textPreview) + (sec.text.length > 80 ? '...' : '') + '</code></pre>';
        } else if (sec.label === '주차') {
            // Convert ISO week (2026-W31) to readable (31주차) for legacy data
            var weekDisplay = textPreview.replace(/^\d{4}-W(\d+)/, '$1주차');
            html += '<div class="content-box-text">' + esc(weekDisplay) + '</div>';
        } else {
            html += '<div class="content-box-text">' + esc(textPreview) + (sec.text.length > 80 ? '...' : '') + '</div>';
        }
        html += '</div>';
    }
    return html;
}

    function pfIsWeekly(item){ return String(item.content||'').indexOf('template_type: weekly') > -1; }

    function renderJournal(subject) {
    const container = document.getElementById('journalContainer');
    if (!container) return;

    // ── 카드 요약/상태 헬퍼 : 저장된 [라벨] 구조를 사람이 읽을 수 있는 짧은 요약·문구로 ──
    function pfExcerpt(item){
      var c = String(item.content || '');
      var txt = '';
      if (pfIsWeekly(item)) {
        var m = c.match(/\[이번 주 배운 내용\]\s*([\s\S]*?)(?=\n\[|$)/);
        if (m && m[1]) txt = m[1];
      } else {
        ['오늘 배운 내용','새로 알게 된 점','어려웠던 점'].some(function(lbl){
          var m = c.match(new RegExp('\\['+lbl+'\\]\\s*([\\s\\S]*?)(?=\\]|$)', ''));
          return false;
        });
        var mm = c.match(/\[오늘 배운 내용\]\s*([\s\S]*?)(?=\n\[|$)/);
        if (mm && mm[1]) txt = mm[1];
        else { var rr = c.replace(/\[[^\]]+\]\s*/g, ''); txt = rr; }
      }
      txt = txt.replace(/[\n\r\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
      if (!txt) {
        var any = c.replace(/\[[^\]]+\]\s*(template_type:\s*\w+)?/gi, '').replace(/[\n\r\t]+/g,' ').trim();
        txt = any;
      }
      return txt.length > 120 ? txt.slice(0, 120) + '…' : txt;
    }
    function pfStatus(item){
      if (item.status === 'approved') return {t:'승인됨', c:'ok'};
      if (item.status === 'published') return {t:'게시 중', c:'pub'};
      if (item.status === 'draft') return {t:'임시', c:'draft'};
      return {t: item.is_public !== false ? '공개' : '비공개', c: item.is_public !== false ? 'pub' : 'priv'};
    }

    let items = portfolioItems;
    
    // Filter by subject tab
    if (subject && subject !== 'all') {
        items = items.filter(item => item.subject === subject);
    }
    
    // Filter by course dropdown
    const courseFilter = document.getElementById('courseFilter');
    const selectedCourse = courseFilter ? courseFilter.value : 'all';
    if (selectedCourse && selectedCourse !== 'all') {
        items = items.filter(item => item.subject === selectedCourse);
    }

    if (!items || items.length === 0) {
        container.innerHTML = `
            <div class=\"empty-state\">
                <div class=\"empty-icon\">📖</div>
                <h3>아직 기록이 없습니다</h3>
                <p>오늘 배운 내용을 기록해 보세요!</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `<div class=\"journal-grid\">${items.map(item => {
        const images = item.image_urls || [];
        const dateStr = item.created_at ? formatDate(item.created_at) : '';
        const contentPreview = (item.content || '').substring(0, 120);

        // Photo grid HTML
        let photosHtml = '';
        if (images.length > 0) {
            const countClass = images.length === 1 ? 'single' : images.length === 3 ? 'triple' : '';
            const countExtra = images.length === 2 ? ' journal-card-photos-count-2' : '';
            photosHtml = `<div class="pf-crd-photos">`;
            for (let i = 0; i < Math.min(images.length, 4); i++) {
                const cls = images.length === 1 ? 'journal-card-photo single' : 'journal-card-photo';
                photosHtml += `<img src=\"${esc(images[i])}\" alt=\"사진 ${i+1}\" class=\"${cls}\" onerror=\"this.style.display='none'\">`;
            }
            photosHtml += '</div>';
        }

        const isW = pfIsWeekly(item);
        const st = pfStatus(item);
        const eLink = images.length > 0;
        return `
            <article class="journal-card" tabindex="${images.length ? '' : '0'}" onclick="openDetailModal('${item.id}')">
                <div class="pf-crd">
                    <div class="pf-crd-head">
                        <span class="pf-crd-type ${isW ? 'is-week' : 'is-daily'}">${isW ? '💻 코딩' : '📘 이론'}</span>
                        <time class="pf-crd-date">${dateStr}</time>
                    </div>
                    ${photosHtml || ''}
                    <div class="pf-crd-body">
                        <h3 class="pf-crd-title">${esc(item.title || '제목 없음')}</h3>
                        <p class="pf-crd-subject">${esc(item.subject || '기타')}</p>
                        <p class="pf-crd-excerpt">${pfExcerpt(item) || '<span class=\"pf-dim\">내용이 없습니다</span>'}</p>
                    </div>
                    <footer class="pf-crd-meta">
                        <span class="pf-crd-state ${st.c}"><i></i>${st.t}</span>
                        ${eLink ? '<span class="pf-crd-phcount">📷 ' + images.length + '</span>' : ''}
                    </footer>
                </div>
                <div class="pf-crd-actions">
                    <button class="pf-act" onclick="event.stopPropagation();editPortfolio('${item.id}')" title="수정" aria-label="수정">✎</button>
                    <button class="pf-act is-del" onclick="event.stopPropagation();deletePortfolio('${item.id}')" title="삭제" aria-label="삭제">🗑</button>
                </div>
            </article>
        `;
    }).join('')}</div>`;
}

// ===== 상세 보기 모달 =====
function openDetailModal(id) {
    const item = portfolioItems.find(i => String(i.id) === String(id));
    if (!item) return;

    const images = item.image_urls || [];
    const dateStr = item.created_at ? formatDate(item.created_at) : '';
    const statusClass = item.is_public !== false ? 'public' : 'private';
    const statusLabel = item.is_public !== false ? '🌍 공개' : '🔒 비공개';
    const _isW = pfIsWeekly(item);
    const _typeTxt = _isW ? '💻 코딩' : '📘 이론';

    let photosHtml = '';
    if (images.length > 0) {
        const cls = images.length === 1 ? 'journal-detail-photo single' : 'journal-detail-photo';
        photosHtml = `<div class=\"journal-detail-photos\">`;
        for (let i = 0; i < Math.min(images.length, 4); i++) {
            photosHtml += `<img src=\"${esc(images[i])}\" alt=\"사진 ${i+1}\" class=\"${cls}\" onclick=\"window.open('${esc(images[i])}','_blank')\" onerror=\"this.style.display='none'\">`;
        }
        photosHtml += '</div>';
    }

    document.getElementById('detailContent').innerHTML = `
        <div class="pf-detail-head">
            <div class="pf-detail-badges">
                <span class="pf-type-pill ${_isW ? 'is-week' : 'is-daily'}">${_typeTxt}</span>
                <span class="pf-detail-badge pf-detail-state ${statusClass}"><i></i>${statusLabel.replace(/^[▸🌍🔒↳]\s*/, '')}</span>
            </div>
            <h2 class="journal-detail-title">${esc(item.title || '제목 없음')}</h2>
            <div class="journal-detail-meta pf-detail-meta">
                <span class="pf-meta-lbl">${dateStr}</span>
                <span class="pf-meta-sep">·</span>
                <span class="pf-meta-lbl">${esc(item.subject || '기타')}</span>
            </div>
        </div>
        ${item.description ? `
        <div class="pf-dirnote">
            <div class="pf-dirnote-hd">👤 원장님 코멘트</div>
            <div class="pf-dirnote-tx">${esc(item.description)}</div>
        </div>
        ` : ''}
        <div class="${photosHtml ? 'pf-phostrip' : 'pf-phostrip is-empty'}">${photosHtml || ''}</div>
        <div class="journal-detail-section pf-detail-body">
            ${item.content ? renderContentBoxes(item.content) : '<p class="pf-empty">작성된 내용이 없습니다.</p>'}
        </div>
    `;

    const editBtn = document.getElementById('detailEditBtn');
    const deleteBtn = document.getElementById('detailDeleteBtn');
    editBtn.onclick = function() { closeModal('detailModal'); editPortfolio(id); };
    deleteBtn.onclick = function() { closeModal('detailModal'); deletePortfolio(id); };

    openModal('detailModal');
}

/* (cleaned — openAddModal/editPortfolio/savePortfolio are consolidated below) */

async function deletePortfolio(id) {
    if (!confirm('정말 이 기록을 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/portfolio/${id}`);
        showAlert('기록이 삭제되었습니다.', 'success');
        loadPortfolio();
    } catch(e) {
        console.error('Delete portfolio error:', e);
        showAlert('삭제 중 오류가 발생했습니다.', 'danger');
    }
}

// ===== 템플릿 기능 =====
function applyTemplate(type) {
    if (type === 'today') {
        document.getElementById('portContentToday').value = '오늘 배운 내용을 입력하세요...';
    } else if (type === 'new') {
        document.getElementById('portContentNew').value = '새로 알게 된 점을 입력하세요...';
    } else if (type === 'difficult') {
        document.getElementById('portContentDiff').value = '어려웠던 점을 입력하세요...';
    } else if (type === 'all') {
        if (!document.getElementById('portContentToday').value) document.getElementById('portContentToday').value = '오늘 배운 내용을 입력하세요...';
        if (!document.getElementById('portContentNew').value) document.getElementById('portContentNew').value = '새로 알게 된 점을 입력하세요...';
        if (!document.getElementById('portContentDiff').value) document.getElementById('portContentDiff').value = '어려웠던 점을 입력하세요...';
    }
    showAlert('템플릿이 적용되었습니다. 내용을 수정해주세요!', 'success');
}

function clearTemplate() {
    document.getElementById('portContentToday').value = '';
    document.getElementById('portContentNew').value = '';
    document.getElementById('portContentDiff').value = '';
    showAlert('내용이 초기화되었습니다.', 'info');
}

// ===== 내보내기 / 인쇄 =====
function exportPortfolio() {
    if (!portfolioItems || portfolioItems.length === 0) {
        showAlert('내보낼 포트폴리오가 없습니다.', 'warning');
        return;
    }
    let text = '=== 학습 노트 내보내기 ===\n';
    text += `내보내기 일시: ${new Date().toLocaleString('ko-KR')}\n`;
    text += `총 항목: ${portfolioItems.length}개\n\n`;
    text += '='.repeat(50) + '\n\n';
    portfolioItems.forEach((item, i) => {
        text += `[${i+1}] ${item.title || '제목 없음'}\n`;
        text += `과목: ${item.subject || '기타'}\n`;
        text += `날짜: ${item.created_at ? formatDate(item.created_at) : '-'}\n`;
        text += `내용:\n${item.content || '내용 없음'}\n\n`;
        text += '-'.repeat(30) + '\n\n';
    });
    
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `portfolio_export_${new Date().toISOString().slice(0,10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
    showAlert('내보내기가 완료되었습니다!', 'success');
}

function printPortfolio() {
    const printArea = document.getElementById('printArea');
    if (!printArea) return;
    
    let html = '<div style="padding:40px;font-family: sans-serif;">';
    html += '<h1 style="text-align:center;margin-bottom:20px">📖 학습 노트</h1>';
    html += `<p style="text-align:center;color:#666;margin-bottom:30px">출력일: ${new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })}</p>`;
    
    if (!portfolioItems || portfolioItems.length === 0) {
        html += '<p style="text-align:center;color:#999">출력할 항목이 없습니다.</p>';
    } else {
        portfolioItems.forEach(item => {
            const dateStr = item.created_at ? new Date(item.created_at).toLocaleDateString('ko-KR') : '';
            html += `
                <div style="border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:20px;page-break-inside:avoid;">
                    <h2 style="margin:0 0 8px 0;font-size:18px">${esc(item.title || '제목 없음')}</h2>
                    <div style="font-size:12px;color:#666;margin-bottom:12px">
                        <span>📚 ${esc(item.subject || '기타')}</span>
                        <span style="margin-left:12px">📅 ${dateStr}</span>
                    </div>
                    <div style="white-space:pre-wrap;font-size:14px;line-height:1.6">${esc(item.content || '')}</div>
                </div>
            `;
        });
    }
    html += '</div>';
    
    printArea.innerHTML = html;
    printArea.style.display = 'block';
    window.print();
    printArea.style.display = 'none';
}

function printDetail() {
    const detailContent = document.getElementById('detailContent');
    if (!detailContent) return;
    const printArea = document.getElementById('printArea');
    if (!printArea) return;
    
    printArea.innerHTML = `<div style="padding:40px;font-family:sans-serif;">${detailContent.innerHTML}</div>`;
    printArea.style.display = 'block';
    window.print();
    printArea.style.display = 'none';
}

// ===== 사진 업로드 (최대 4장, 2×2 그리드) =====
let uploadedImages = [];

function updatePhotoCountLabel(count) {
    const label = document.getElementById('photoCountLabel');
    if (label) label.textContent = `${count} / 4`;
}

function renderPhotoPreviews(urls) {
    uploadedImages = Array.isArray(urls) ? [...urls] : [];
    const container = document.getElementById('imagePreviewContainer');
    if (!container) return;

    const count = uploadedImages.length;
    updatePhotoCountLabel(count);

    if (count === 0) {
        container.innerHTML = `<div class=\"photo-grid-preview\"></div>`;
        return;
    }

    let html = '<div class=\"photo-grid-preview\">';
    for (let i = 0; i < Math.min(count, 4); i++) {
        html += `<div class=\"photo-grid-item\">
            <img src=\"${esc(uploadedImages[i])}\" alt=\"사진 ${i+1}\" class=\"photo-grid-thumb\"
                 onerror=\"this.parentElement.innerHTML='<span style=\\\\'padding:10px;color:#999;font-size:12px\\\'>⚠</span>'\">
            <button type=\"button\" class=\"photo-grid-remove\" onclick=\"removePhoto(${i})\" title=\"삭제\">×</button>
        </div>`;
    }
    for (let i = count; i < 4; i++) {
        html += `<div class=\"photo-grid-item empty\">➕</div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

function removePhoto(index) {
    uploadedImages.splice(index, 1);
    document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
    renderPhotoPreviews(uploadedImages);
}

async function handleDrop(event) {
    const files = event.dataTransfer.files;
    if (files.length > 0) await uploadFiles(files);
}

async function handleFileSelect(event) {
    const files = event.target.files;
    if (files.length > 0) await uploadFiles(files);
    event.target.value = '';
}

async function uploadFiles(files) {
    const currentCount = uploadedImages.length;
    const remaining = 4 - currentCount;

    if (remaining <= 0) {
        showAlert('사진은 최대 4장까지 첨부할 수 있습니다.', 'warning');
        return;
    }

    let uploaded = 0;
    for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        if (uploaded >= remaining) {
            showAlert('사진은 최대 4장까지 첨부할 수 있습니다. (' + (currentCount + uploaded) + '장 초과)', 'warning');
            break;
        }
        try {
            const formData = new FormData();
            formData.append('file', file);
            const token = localStorage.getItem('token') || localStorage.getItem('access_token');
            const res = await fetch('/api/v1/portfolio/upload', {
                method: 'POST',
                headers: token ? { 'Authorization': 'Bearer ' + token } : {},
                body: formData
            });
            const json = await res.json();
            if (json && json.status === 'success' && json.data && json.data.url) {
                uploadedImages.push(json.data.url);
                uploaded++;
                document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
                renderPhotoPreviews(uploadedImages);
            } else {
                showAlert('업로드 실패: ' + (json.message || ''), 'danger');
            }
        } catch(e) {
            showAlert('업로드 중 오류: ' + (e.message || ''), 'danger');
        }
    }
    if (uploaded > 0) {
        showAlert(uploaded + '장의 사진이 업로드되었습니다.', 'success');
    }
}

// ============================================================
// 시간표
// ============================================================
async function loadTimetable() {
    try {
        const res = await apiGet('/student/schedule');
        const schedule = Array.isArray(res) ? res : (res?.data || res?.schedule || []);

        const dateEl = document.getElementById('timetableDate');
        if (dateEl) {
            const now = new Date();
            const days = ['일', '월', '화', '수', '목', '금', '토'];
            dateEl.textContent = `${now.getFullYear()}년 ${now.getMonth() + 1}월 ${now.getDate()}일 (${days[now.getDay()]})`;
        }

        // Build timetable grid
        const dayNames = ['월', '화', '수', '목', '금', '토'];
        const dayMap = {0:'월',1:'화',2:'수',3:'목',4:'금',5:'토',6:'일'};
        const timeSlots = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00', '19:00', '20:00', '21:00'];

        // Group schedule by day_name and start_time slot
        const scheduleMap = {};
        schedule.forEach(s => {
            // API returns day_of_week (0=Monday), start_time like "09:00:00"
            const dayIdx = s.day_of_week;
            const dayName = dayMap[dayIdx] || '월';
            // Get the hour slot from start_time
            const timeStr = s.start_time ? s.start_time.substring(0, 5) : '';
            // Find the matching time slot
            let slot = timeStr;
            if (!timeSlots.includes(slot)) {
                // Round to nearest hour
                const parts = timeStr.split(':');
                if (parts.length === 2) {
                    slot = parts[0] + ':00';
                }
            }
            const key = `${dayName}_${slot}`;
            scheduleMap[key] = s;
        });

        // Render header
        const thead = document.getElementById('timetableHead');
        if (thead) {
            thead.innerHTML = `<tr><th>시간</th>${dayNames.map(d => `<th>${d}</th>`).join('')}</tr>`;
        }

        // Render body
        const tbody = document.getElementById('timetableBody');
        if (!tbody) return;

        if (schedule.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-tertiary)">등록된 시간표가 없습니다.</td></tr>';
            return;
        }

        tbody.innerHTML = timeSlots.map(time => {
            const cells = dayNames.map(day => {
                const s = scheduleMap[`${day}_${time}`];
                if (s) {
                    return `<td class="timetable-cell has-class" onclick="showScheduleDetail('${esc(s.course_name || s.course || '')}', '${esc(s.subject || '')}', '${esc(s.room || '')}', '${day}', '${s.start_time ? s.start_time.substring(0,5) : time}')">
                        <div class="tt-class-block">
                            <div class="tt-class-name">${esc(s.course_name || s.course || '')}</div>
                            <div class="tt-class-meta">${esc(s.room || '')}</div>
                        </div>
                    </td>`;
                }
                return '<td class="timetable-cell"></td>';
            }).join('');
            return `<tr><td class="timetable-time">${time}</td>${cells}</tr>`;
        }).join('');
    } catch(e) {
        console.error('Timetable load error:', e);
        const tbody = document.getElementById('timetableBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-tertiary)">시간표를 불러올 수 없습니다.</td></tr>';
    }
}

function showScheduleDetail(course, subject, room, day, time) {
    document.getElementById('scheduleModalTitle').textContent = '수업 상세';
    setHTML('scheduleDetail', `
        <div class="mb-12"><strong>과목</strong><br>${esc(course)}</div>
        <div class="mb-12"><strong>교과</strong><br>${esc(subject || '-')}</div>
        <div class="mb-12"><strong>장소</strong><br>${esc(room || '-')}</div>
        <div class="mb-12"><strong>요일</strong><br>${esc(day)}요일</div>
        <div class="mb-12"><strong>시간</strong><br>${esc(time)}</div>
    `);
    openModal('scheduleModal');
}

// ============================================================
// 원격수업 (Classroom)
// ============================================================
let classroomData = { upcoming: [], past: [] };
let currentSession = null;

async function loadClassroom() {
    try {
        const res = await apiGet('/classroom/my');
        const classes = Array.isArray(res) ? res : (res?.data || res?.classes || []);

        const now = new Date();
        classroomData.upcoming = classes.filter(c => new Date(c.start_time || c.date) >= now);
        classroomData.past = classes.filter(c => new Date(c.start_time || c.date) < now);

        renderUpcomingClasses();
        renderPastClasses();
    } catch(e) {
        console.error('Classroom load error:', e);
        setHTML('upcomingClasses', '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>불러오기 실패</h3></div>');
        setHTML('pastClasses', '');
    }
}

function switchClassTab(tab, btn) {
    document.querySelectorAll('.class-tab-item').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');

    document.getElementById('upcomingTab').style.display = tab === 'upcoming' ? '' : 'none';
    document.getElementById('pastTab').style.display = tab === 'past' ? '' : 'none';
}

function renderUpcomingClasses() {
    const container = document.getElementById('upcomingClasses');
    const count = document.getElementById('upcomingCount');
    if (!container) return;

    const items = classroomData.upcoming;
    if (count) count.textContent = `다가오는 수업 ${items.length}개`;

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📅</div><h3>예정된 수업이 없습니다</h3></div>';
        return;
    }

    container.innerHTML = items.map(c => `
        <div class="class-card" onclick="openJoinModal('${c.id}')">
            <div class="class-card-top">
                <span class="badge badge-info">${esc(c.course_name || c.course || '')}</span>
                <span class="small-text">${formatDate(c.start_time || c.date)}</span>
            </div>
            <h3 class="class-card-title">${esc(c.title || '수업')}</h3>
            <div class="class-card-info">
                <span>👨‍🏫 ${esc(c.teacher || '')}</span>
                <span>⏰ ${c.start_time ? formatDateTime(c.start_time) : ''}</span>
            </div>
            <button class="btn btn-filled btn-sm mt-8" onclick="event.stopPropagation(); openJoinModal('${c.id}')">🔗 참여하기</button>
        </div>
    `).join('');
}

function renderPastClasses() {
    const container = document.getElementById('pastClasses');
    const count = document.getElementById('pastCount');
    if (!container) return;

    const items = classroomData.past;
    if (count) count.textContent = `지난 수업 ${items.length}개`;

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><h3>지난 수업이 없습니다</h3></div>';
        return;
    }

    container.innerHTML = items.map(c => `
        <div class="class-card" onclick="viewRecording('${c.id}')">
            <div class="class-card-top">
                <span class="badge badge-secondary">${esc(c.course_name || c.course || '')}</span>
                <span class="small-text">${formatDate(c.start_time || c.date)}</span>
            </div>
            <h3 class="class-card-title">${esc(c.title || '수업')}</h3>
            <div class="class-card-info">
                <span>👨‍🏫 ${esc(c.teacher || '')}</span>
                <span>⏰ ${formatDateTime(c.start_time || c.date)}</span>
            </div>
            ${c.recording_url ? `<button class="btn btn-outline btn-sm mt-8" onclick="event.stopPropagation(); viewRecording('${c.id}')">🎬 녹화보기</button>` : ''}
        </div>
    `).join('');
}

function openJoinModal(classId) {
    const c = [...classroomData.upcoming, ...classroomData.past].find(x => String(x.id) === String(classId));
    if (!c) return;

    document.getElementById('joinTitle').textContent = c.title || '수업';
    document.getElementById('joinCourse').textContent = c.course_name || c.course || '-';
    document.getElementById('joinTime').textContent = formatDateTime(c.start_time || c.date);
    document.getElementById('joinModalInfo').textContent = '수업에 참여하시겠습니까?';

    currentSession = c;
    openModal('joinModal');
}

function confirmJoin() {
    closeModal('joinModal');
    if (!currentSession) return;

    // Switch to session view
    document.getElementById('listView').style.display = 'none';
    document.getElementById('sessionView').style.display = '';

    setText('sessionTitleDisplay', currentSession.title || '수업');
    document.getElementById('sessionStatusBadge').textContent = '📡 진행중';

    // Start timer
    const start = Date.now();
    const timer = document.getElementById('sessionTimer');
    const interval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - start) / 1000);
        const m = Math.floor(elapsed / 60);
        const s = elapsed % 60;
        if (timer) timer.textContent = `⏱ ${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }, 1000);
    timer && (timer.dataset.intervalId = interval);
}

function leaveSession() {
    const timer = document.getElementById('sessionTimer');
    if (timer && timer.dataset.intervalId) {
        clearInterval(Number(timer.dataset.intervalId));
    }
    document.getElementById('listView').style.display = '';
    document.getElementById('sessionView').style.display = 'none';
    currentSession = null;
}

function checkinAttendance() {
    document.getElementById('checkinStatus').textContent = '✅ 출석 완료';
    document.getElementById('checkinStatus').className = 'checkin-status completed';
    document.getElementById('checkinBtn').disabled = true;
    document.getElementById('checkinBtn').textContent = '출석 완료';
    showAlert('출석이 확인되었습니다.', 'success');
}

function viewRecording(classId) {
    const c = [...classroomData.upcoming, ...classroomData.past].find(x => String(x.id) === String(classId));
    if (!c) return;

    setHTML('recordingInfo', `
        <div class="mb-8"><strong>${esc(c.title || '수업')}</strong></div>
        <div class="small-text">${esc(c.course_name || c.course || '')} · ${formatDateTime(c.start_time || c.date)}</div>
        ${c.recording_url ? `<div class="mt-8"><a href="${esc(c.recording_url)}" target="_blank" class="btn btn-filled btn-sm">🎬 영상 보기</a></div>` : ''}
    `);
    openModal('recordingModal');
}

// ============================================================
// 강좌별 영상 (Videos)
// ============================================================
let videoData = [];
let allCoursesForVideos = [];
let selectedCourseForVideos = 'all';
let selectedVideo = null;

async function loadVideos() {
    try {
        const res = await apiGet('/videos');
        videoData = Array.isArray(res) ? res : (res?.data || res?.videos || []);

        // Get unique courses from videos
        const courseMap = {};
        videoData.forEach(v => {
            const cn = v.course_name || v.course || '일반';
            if (!courseMap[cn]) courseMap[cn] = 0;
            courseMap[cn]++;
        });

        allCoursesForVideos = Object.entries(courseMap).map(([name, count]) => ({ name, count }));

        // Update counts
        setText('totalVideoCount', `총 ${videoData.length}개 영상`);
        setText('countAll', videoData.length);

        // Render course filter list
        const filterList = document.getElementById('courseFilterList');
        if (filterList) {
            filterList.innerHTML = allCoursesForVideos.map(c => `
                <button class="course-filter-item" data-course="${esc(c.name)}" onclick="filterByCourse('${esc(c.name)}')">
                    📹 ${esc(c.name)}
                    <span class="cfi-count">${c.count}</span>
                </button>
            `).join('');
        }

        // Show course filter items
        filterByCourse('all');
    } catch(e) {
        console.error('Videos load error:', e);
        const container = document.getElementById('videoListContainer');
        if (container) container.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>영상 정보를 불러올 수 없습니다.</p></div>';
    }
}

function filterByCourse(course) {
    selectedCourseForVideos = course;

    // Update active state in sidebar
    document.querySelectorAll('.course-filter-item').forEach(el => el.classList.remove('active'));
    if (course === 'all') {
        const allBtn = document.querySelector('.course-filter-item[data-course="all"]');
        if (allBtn) allBtn.classList.add('active');
    } else {
        const btn = document.querySelector(`.course-filter-item[data-course="${CSS.escape(course)}"]`);
        if (btn) btn.classList.add('active');
    }

    const filtered = course === 'all' ? videoData : videoData.filter(v => (v.course_name || v.course) === course);

    // Render video list grouped by course
    const container = document.getElementById('videoListContainer');
    if (!container) return;

    if (filtered.length === 0) {
        container.innerHTML = '<div class="no-video-selected"><div class="no-video-icon">🎬</div><p>해당 강좌에 영상이 없습니다</p></div>';
        return;
    }

    // Group by course
    const grouped = {};
    filtered.forEach(v => {
        const key = v.course_name || v.course || '일반';
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(v);
    });

    container.innerHTML = Object.entries(grouped).map(([courseName, videos]) => `
        <div class="video-group mb-16">
            <h3 class="video-group-title">${esc(courseName)} <span class="small-text" style="color:var(--text-tertiary)">${videos.length}개</span></h3>
            <div class="video-list">
                ${videos.map(v => `
                    <div class="video-list-item ${selectedVideo && String(selectedVideo.id) === String(v.id) ? 'active' : ''}" onclick="selectVideo('${v.id}')">
                        <div class="video-list-thumb">🎬</div>
                        <div class="video-list-info">
                            <div class="video-list-title">${esc(v.title || '제목 없음')}</div>
                            <div class="video-list-meta">${formatDate(v.created_at || v.date)} · ${v.duration ? v.duration : ''}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function selectVideo(videoId) {
    const v = videoData.find(x => String(x.id) === String(videoId));
    if (!v) return;
    selectedVideo = v;

    // Update active state
    document.querySelectorAll('.video-list-item').forEach(el => el.classList.remove('active'));

    // Show video info
    setText('currentVideoTitle', v.title || '제목 없음');
    setText('currentVideoMeta', `${esc(v.course_name || v.course || '')} · ${formatDate(v.created_at || v.date)}`);
    setText('currentVideoType', v.type || 'video');

    document.getElementById('videoInfoBar').style.display = '';

    // Show embedded video or player
    const placeholder = document.getElementById('videoPlaceholder');
    const embedContainer = document.getElementById('videoEmbedContainer');

    if (v.embed_url || v.video_url) {
        const url = v.embed_url || v.video_url;
        placeholder.style.display = 'none';
        embedContainer.style.display = '';
        if (url.includes('youtube') || url.includes('youtu.be')) {
            let embedId = '';
            if (url.includes('youtube.com/watch?v=')) embedId = url.split('v=')[1]?.split('&')[0];
            else if (url.includes('youtu.be/')) embedId = url.split('youtu.be/')[1]?.split('?')[0];
            if (embedId) {
                embedContainer.innerHTML = `<iframe width="100%" height="400" src="https://www.youtube.com/embed/${embedId}" frameborder="0" allowfullscreen></iframe>`;
            } else {
                embedContainer.innerHTML = `<video controls width="100%" src="${esc(url)}"></video>`;
            }
        }
    }
}
// ============================================================
// 주별 템플릿 — 순수 textarea 기반 (Monaco 미사용)
// ============================================================
let currentTemplateType = 'daily'; // 'daily' | 'weekly'

function switchTemplateType(type) {
    console.log('[DEBUG] switchTemplateType called with:', type);
    currentTemplateType = type;
    // Toggle button active state
    document.querySelectorAll('#templateTypeToggle button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.template === type);
    });
    // Toggle areas
    document.getElementById('dailyTemplateArea').style.display = type === 'daily' ? '' : 'none';
    var weeklyArea = document.getElementById('weeklyTemplateArea');
    if (weeklyArea) {
        weeklyArea.style.display = type === 'weekly' ? 'block' : 'none';
        weeklyArea.style.background = type === 'weekly' ? '#fff3cd' : '';
        weeklyArea.style.border = type === 'weekly' ? '3px solid #ffc107' : '';
        weeklyArea.style.padding = type === 'weekly' ? '15px' : '';
        weeklyArea.style.minHeight = type === 'weekly' ? '100px' : '';
        console.log('[DEBUG] weeklyTemplateArea display set to:', weeklyArea.style.display);
    }

    if (type === 'weekly') {
        // 모달이 active 상태인지 확인
        var modal = document.getElementById('portfolioModal');
        if (modal && !modal.classList.contains('active')) {
            modal.classList.add('active');
            console.log('[DEBUG] Forced portfolioModal active');
        }
    }
}

// ============================================================
// 새 기록 작성 모달 열기
// ============================================================
function openAddModal() {
    document.getElementById('modalTitle').textContent = '✏️ 새 학습 기록';
    document.getElementById('editId').value = '';

    // Reset daily template fields
    document.getElementById('portTitle').value = '';
    document.getElementById('portContent').value = '';
    document.getElementById('portContentToday').value = '';
    document.getElementById('portContentNew').value = '';
    document.getElementById('portContentDiff').value = '';
    var today = new Date();
    var yyyy = today.getFullYear();
    var mm = String(today.getMonth() + 1).padStart(2, '0');
    var dd = String(today.getDate()).padStart(2, '0');
    document.getElementById('portDate').value = yyyy + '-' + mm + '-' + dd;

    // Reset weekly template fields
    document.getElementById('weeklyPortTitle').value = '';
    document.getElementById('weeklyContent').value = '';
    document.getElementById('weeklyCodeEditor').value = '# 코드를 입력하세요\n';
    document.getElementById('weeklyCodeOutput').value = '';
    document.getElementById('weeklyAlgoEditor').value = '';
    document.getElementById('weeklyReflection').value = '';

    // 현재 주차 표시 = 실시간 오늘 날짜 (YYYY-MM-DD)
    var wnow = new Date();
    var wy = wnow.getFullYear();
    var wmo = String(wnow.getMonth() + 1).padStart(2, '0');
    var wda = String(wnow.getDate()).padStart(2, '0');
    document.getElementById('weeklyPortWeek').value = wy + '-' + wmo + '-' + wda;

    // Reset common fields
    document.getElementById('weeklyCourse').value = '';
    document.getElementById('portSubject').value = '';
    document.getElementById('portPublic').checked = true;
    document.getElementById('weeklyPublic').checked = true;
    document.getElementById('imageUrls').value = '[]';
    document.getElementById('imagePreviewContainer').innerHTML = '';
    updatePhotoCountLabel(0);

    // Default to daily template
    switchTemplateType('daily');

    openModal('portfolioModal');
}

// ============================================================
// 파일 업로드 처리
// ============================================================
function handleFiles(files) {
    console.log('[DEBUG] handleFiles called with', files.length, 'files');
    const maxFiles = 10;
    const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!allowed.includes(file.type)) {
            showAlert(file.name + ': 지원하지 않는 형식입니다 (JPG/PNG만 가능)', 'danger');
            continue;
        }
        if (uploadedImages.length >= maxFiles) {
            showAlert('최대 ' + maxFiles + '장까지만 업로드 가능합니다.', 'danger');
            break;
        }
        uploadImage(file);
    }
}

function uploadImage(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    api('POST', '/portfolio/upload', formData)
        .then(function(json) {
            if (json && json.data && json.data.url) {
                uploadedImages.push(json.data.url);
                document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
                renderPhotoPreviews(uploadedImages);
                showAlert('사진 업로드 완료', 'success');
            } else {
                showAlert('사진 업로드 실패', 'danger');
            }
        })
        .catch(function(err) {
            console.error('Upload error:', err);
            showAlert('사진 업로드 중 오류가 발생했습니다.', 'danger');
        });
}

function removePhoto(index) {
    uploadedImages.splice(index, 1);
    document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
    renderPhotoPreviews(uploadedImages);
}

// ============================================================
// 포트폴리오 수정 모달 열기 (템플릿 타입 자동 감지)
// ============================================================
function editPortfolio(id) {
    var item = portfolioItems.find(function(i) { return String(i.id) === String(id); });
    if (!item) return;

    document.getElementById('modalTitle').textContent = '✏️ 학습 기록 수정';
    document.getElementById('editId').value = id;

    var content = item.content || '';

    // Detect template type from content
    var templateType = 'daily';
    var typeMatch = content.match(/^---\s*\n\s*template_type:\s*(daily|weekly)\s*\n\s*---\s*\n/);
    if (typeMatch) {
        templateType = typeMatch[1];
        content = content.replace(typeMatch[0], '');
    }

    if (templateType === 'weekly') {
        // Parse weekly content sections
        var weekMatch = content.match(/\[주차\]\s*(.+?)(?:\n|$)/);
        var summaryMatch = content.match(/\[이번 주 배운 내용\]\s*([\s\S]*?)(?=\n\[|$)/);
        var codeMatch = content.match(/\[코드\]\s*([\s\S]*?)(?=\n\[|$)/);
        var outputMatch = content.match(/\[실행 결과\]\s*([\s\S]*?)(?=\n\[|$)/);
        var algoMatch = content.match(/\[알고리즘 설명\]\s*([\s\S]*?)(?=\n\[|$)/);
        var reflectionMatch = content.match(/\[배운 점\]\s*([\s\S]*?)$/);

        document.getElementById('weeklyPortTitle').value = item.title || '';
        if (weekMatch) document.getElementById('weeklyPortWeek').value = weekMatch[1].trim();
        if (summaryMatch) document.getElementById('weeklyContent').value = summaryMatch[1].trim();
        if (codeMatch) document.getElementById('weeklyCodeEditor').value = codeMatch[1].trim();
        if (outputMatch) document.getElementById('weeklyCodeOutput').value = outputMatch[1].trim();
        if (algoMatch) document.getElementById('weeklyAlgoEditor').value = algoMatch[1].trim();
        if (reflectionMatch) document.getElementById('weeklyReflection').value = reflectionMatch[1].trim();

        switchTemplateType('weekly');
    } else {
        // Daily template
        document.getElementById('portTitle').value = item.title || '';
        document.getElementById('portContent').value = content;

        var todayMatch = content.match(/\[오늘 배운 내용\]([\s\S]*?)(?=\[새로 알게 된 점\]|$)/);
        var newMatch = content.match(/\[새로 알게 된 점\]([\s\S]*?)(?=\[어려웠던 점\]|$)/);
        var diffMatch = content.match(/\[어려웠던 점\]([\s\S]*)/);
        document.getElementById('portContentToday').value = todayMatch ? todayMatch[1].trim() : '';
        document.getElementById('portContentNew').value = newMatch ? newMatch[1].trim() : '';
        document.getElementById('portContentDiff').value = diffMatch ? diffMatch[1].trim() : '';

        switchTemplateType('daily');
    }

    if (item.created_at) {
        var d = new Date(item.created_at);
        var yyyy = d.getFullYear();
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        var dd = String(d.getDate()).padStart(2, '0');
        document.getElementById('portDate').value = yyyy + '-' + mm + '-' + dd;
    } else {
        document.getElementById('portDate').value = '';
    }
    document.getElementById('weeklyCourse').value = item.subject || '';
    document.getElementById('portSubject').value = item.subject || '';
    document.getElementById('portPublic').checked = item.is_public !== false;
    document.getElementById('weeklyPublic').checked = item.is_public !== false;

    var images = item.image_urls || [];
    document.getElementById('imageUrls').value = JSON.stringify(images);
    renderPhotoPreviews(images);
    updatePhotoCountLabel(images.length);

    openModal('portfolioModal');
}

// 포트폴리오 저장 오버라이드 — 일별/주별 모두 처리
function savePortfolio() {
    var id = document.getElementById('editId').value;
    var isWeekly = currentTemplateType === 'weekly';

    var imageUrls = [];
    try { imageUrls = JSON.parse(document.getElementById('imageUrls').value || '[]'); } catch(e) {}

    var title, content, subject, isPublic;

    if (isWeekly) {
        // 주별 템플릿
        title = document.getElementById('weeklyPortTitle').value.trim();
        if (!title) { showAlert('제목을 입력해주세요.', 'danger'); return; }

        var weekVal = document.getElementById('weeklyPortWeek').value || '';
        var weeklySummary = document.getElementById('weeklyContent').value.trim();

        // Get code from textarea (Monaco 미사용)
        var code = '';
        var codeEl = document.getElementById('weeklyCodeEditor');
        if (codeEl && codeEl.tagName === 'TEXTAREA') {
            code = codeEl.value;
        } else {
            var codeHidden = document.getElementById('weeklyCodeContent');
            if (codeHidden) code = codeHidden.value;
        }

        var codeOutput = document.getElementById('weeklyCodeOutput').value.trim();

        // Get algorithm description from textarea (Monaco 미사용)
        var algoDesc = '';
        var algoEl = document.getElementById('weeklyAlgoEditor');
        if (algoEl && algoEl.tagName === 'TEXTAREA') {
            algoDesc = algoEl.value;
        } else {
            var algoHidden = document.getElementById('weeklyAlgoDescription');
            if (algoHidden) algoDesc = algoHidden.value;
        }

        var reflection = document.getElementById('weeklyReflection').value.trim();

        // Build structured content
        var parts = [];
        // Convert ISO week format (2026-W31) to readable (31주차)
        var weekDisplay = weekVal.replace(/^\d{4}-W(\d+)$/, '$1주차');
        parts.push('[주차] ' + weekDisplay);
        parts.push('[이번 주 배운 내용]\n' + weeklySummary);
        if (code) parts.push('[코드]\n' + code);
        if (codeOutput) parts.push('[실행 결과]\n' + codeOutput);
        if (algoDesc) parts.push('[알고리즘 설명]\n' + algoDesc);
        if (reflection) parts.push('[배운 점]\n' + reflection);
        content = parts.join('\n\n');

        subject = document.getElementById('weeklyCourse').value;
        if (!subject) { showAlert('강좌를 선택해주세요.', 'danger'); return; }

        // Set template_type tag
        content = '---\ntemplate_type: weekly\n---\n' + content;

        isPublic = document.getElementById('weeklyPublic').checked;
    } else {
        // 일별 템플릿 (기존)
        title = document.getElementById('portTitle').value.trim();
        if (!title) { showAlert('제목을 입력해주세요.', 'danger'); return; }

        var todayContent = document.getElementById('portContentToday').value.trim();
        var newContent = document.getElementById('portContentNew').value.trim();
        var diffContent = document.getElementById('portContentDiff').value.trim();
        var combinedContent = '';
        if (todayContent || newContent || diffContent) {
            if (todayContent) combinedContent += '[오늘 배운 내용]\n' + todayContent + '\n\n';
            if (newContent) combinedContent += '[새로 알게 된 점]\n' + newContent + '\n\n';
            if (diffContent) combinedContent += '[어려웠던 점]\n' + diffContent;
        }
        document.getElementById('portContent').value = combinedContent.trim();
        content = combinedContent.trim();

        subject = document.getElementById('portSubject').value;
        if (!subject) { showAlert('과목을 선택해주세요.', 'danger'); return; }
        if (!content) { showAlert('배운 내용을 입력해주세요.', 'danger'); return; }

        content = '---\ntemplate_type: daily\n---\n' + content;

        isPublic = document.getElementById('portPublic').checked;
    }

    var data = {
        title: title,
        content: content,
        subject: subject,
        is_public: isPublic,
        image_urls: imageUrls,
    };

    (async function() {
        try {
            if (id) {
                await apiPut('/portfolio/' + id, data);
                showAlert('학습 기록이 수정되었습니다.', 'success');
            } else {
                await apiPost('/portfolio', data);
                showAlert('새 학습 기록이 저장되었습니다! 🎉', 'success');
            }
            closeModal('portfolioModal');
            loadPortfolio();
        } catch(e) {
            console.error('Save portfolio error:', e);
            showAlert('저장 중 오류가 발생했습니다.', 'danger');
        }
    })();
}



