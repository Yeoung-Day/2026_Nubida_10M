/* ============================================================
   누비다플랫폼 v10.0 — 네비게이션 시스템 (Top Navbar)
   - Top navbar dropdown menus
   - 모바일/태블릿 터치 최적화
   - 모든 환경에서 링크 동작 보장
   ============================================================ */
(function() {
  'use strict';

  /* ---- 드롭다운 토글 (Top Navbar) ---- */
  window.toggleDropdown = function(e, menuId) {
    e.preventDefault();
    e.stopPropagation();
    var menu = document.getElementById(menuId);
    if (!menu) return;

    // Close all other dropdowns
    document.querySelectorAll('.top-navbar-dropdown-menu.open').forEach(function(m) {
      if (m.id !== menuId) m.classList.remove('open');
    });

    menu.classList.toggle('open');
  };

  // Close dropdowns when clicking outside
  document.addEventListener('click', function(e) {
    document.querySelectorAll('.top-navbar-dropdown-menu.open').forEach(function(menu) {
      if (!menu.parentElement.contains(e.target)) {
        menu.classList.remove('open');
      }
    });
  });

  // Close dropdowns on Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.top-navbar-dropdown-menu.open').forEach(function(menu) {
        menu.classList.remove('open');
      });
    }
  });

  /* ---- 네비게이션 초기화 ---- */
  function initNav() {
    setupNavLinks();
    handleLogoutBtn();
  }

  /* ---- 네비게이션 링크: top-nav-item + 기존 .nav-item ---- */
  function setupNavLinks() {
    var links = document.querySelectorAll('.top-nav-item, .sidebar-nav a.nav-item');
    if (!links.length) return;

    Array.prototype.forEach.call(links, function(link) {
      // 중복 바인딩 방지
      if (link.getAttribute('data-nav-bound') === 'true') return;
      link.setAttribute('data-nav-bound', 'true');

      link.addEventListener('click', function(e) {
        var href = this.getAttribute('href');
        if (!href || href === '#' || href === '') {
          e.preventDefault();
          return;
        }

        // active 상태 업데이트
        Array.prototype.forEach.call(links, function(l) {
          l.classList.remove('active');
        });
        this.classList.add('active');

        // 이벤트는 preventDefault 하지 않음 → 브라우저 기본 동작 유지
      });
    });
  }

  /* ---- 로그아웃 버튼 ---- */
  function handleLogoutBtn() {
    var btn = document.querySelector('.logout-btn');
    if (!btn) return;
    if (btn.getAttribute('data-logout-bound') === 'true') return;
    btn.setAttribute('data-logout-bound', 'true');

    btn.addEventListener('click', function(e) {
      var fn = window.handleLogout;
      if (typeof fn === 'function') {
        fn();
      } else {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/pages/login.html';
      }
    });
  }

  /* ---- DOM 준비 후 실행 ---- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNav);
  } else {
    initNav();
  }

  /* ---- 알림 벨 + SSE ---- */
  var notifBadgeInterval = null;
  var notifSSE = null;

  function setupNotificationBell() {
    var rightArea = document.querySelector('.page-header-right, .top-nav-right');
    if (!rightArea) return;

    // 벨 아이콘 삽입 (중복 방지)
    if (rightArea.querySelector('.notif-bell-wrap')) return;

    var bellWrap = document.createElement('div');
    bellWrap.className = 'notif-bell-wrap';
    bellWrap.style.cssText = 'position:relative;display:inline-flex;align-items:center;cursor:pointer;margin-right:8px;';
    bellWrap.innerHTML = '<a href="/pages/common/notifications.html" style="text-decoration:none;font-size:18px;line-height:1" title="알림">🔔<span class="notif-badge" style="position:absolute;top:-4px;right:-8px;background:#E53935;color:white;font-size:10px;font-weight:700;min-width:16px;height:16px;border-radius:8px;display:flex;align-items:center;justify-content:center;padding:0 4px;box-shadow:0 1px 3px rgba(0,0,0,0.3);display:none">0</span></a>';
    rightArea.insertBefore(bellWrap, rightArea.firstChild);

    // 읽지 않은 알림 개수 조회
    updateNotifBadge();
    if (notifBadgeInterval) clearInterval(notifBadgeInterval);
    notifBadgeInterval = setInterval(updateNotifBadge, 30000);

    // SSE 실시간 업데이트
    connectNotifSSE();
  }

  async function updateNotifBadge() {
    var token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (!token) return;
    try {
      var res = await fetch('/api/v1/sse/unread-count', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      var json = await res.json();
      var count = json.data?.unread_count || 0;
      var badge = document.querySelector('.notif-badge');
      if (badge) {
        if (count > 0) {
          badge.style.display = 'flex';
          badge.textContent = count > 99 ? '99+' : count;
        } else {
          badge.style.display = 'none';
        }
      }
    } catch(e) { /* 무시 */ }
  }

  function connectNotifSSE() {
    var token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (!token || !window.EventSource) return;
    if (notifSSE) { notifSSE.close(); }

    notifSSE = new EventSource('/api/v1/sse/stream?token=' + encodeURIComponent(token));
    notifSSE.addEventListener('message', function(e) {
      try {
        var data = JSON.parse(e.data);
        if (data.type === 'notification') {
          // 벨 애니메이션 효과 + badge 갱신
          var bell = document.querySelector('.notif-bell-wrap a');
          if (bell) {
            bell.style.transform = 'scale(1.2)';
            setTimeout(function() { bell.style.transform = 'scale(1)'; }, 200);
          }
          updateNotifBadge();
        }
      } catch(e) {}
    });
    notifSSE.addEventListener('error', function() {
      // 자동 재연결 (EventSource 내장)
    });
  }

  /* ---- 사이드바 알림 링크 동적 추가 ---- */
  function addNotifSidebarLink() {
    var nav = document.querySelector('.sidebar-nav');
    if (!nav) return;
    if (nav.querySelector('[data-notif-link]')) return;

    // 소통 section 뒤에 추가
    var sections = nav.querySelectorAll('.nav-section');
    var lastSection = sections[sections.length - 1];
    if (!lastSection) return;

    var link = document.createElement('a');
    link.className = 'nav-item';
    link.setAttribute('data-notif-link', 'true');
    link.setAttribute('href', '/pages/common/notifications.html');
    link.innerHTML = '<span class="icon">🔔</span><span class="nav-label">알림 센터</span>';

    lastSection.parentNode.insertBefore(link, lastSection.nextSibling);
  }

  /* initNav 확장 */
  var origInitNav = initNav;
  initNav = function() {
    origInitNav();
    addNotifSidebarLink();
    setupNotificationBell();
  };

  /* ---- 엑셀 다운로드 헬퍼 ---- */
  window.exportExcel = function(type) {
    var token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (!token) { alert('로그인이 필요합니다.'); return; }

    var urls = {
      'users': '/api/v1/excel/users',
      'payments': '/api/v1/excel/payments',
      'statistics': '/api/v1/excel/statistics',
      'reports': '/api/v1/excel/reports',
    };
    var url = urls[type];
    if (!url) return;

    var a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', '');
    // Trigger download with auth header via fetch
    fetch(url, { headers: { 'Authorization': 'Bearer ' + token } })
      .then(function(r) {
        if (!r.ok) throw new Error('다운로드 실패');
        return r.blob();
      })
      .then(function(blob) {
        var objUrl = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = objUrl;
        link.download = type + '_' + new Date().toISOString().slice(0,10) + '.xlsx';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(objUrl);
      })
      .catch(function(e) { alert('엑셀 다운로드 실패: ' + e.message); });
  };
})();
