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
