/* ============================================================
   누비다플랫폼 v10.0 — 네비게이션 시스템 (Top Navbar)
   - Top navbar dropdown menus
   - 모바일/태블릿 터치 최적화
   - 모든 환경에서 링크 동작 보장
   ============================================================ */
(function() {
  'use strict';

  /* ============================================================
     공통 스크립트 동적 로드 (모든 페이지)
     - nav.js는 전 페이지에 로드되므로 push/popup 주입을 여기서 수행
     - hamburger.js는 일부 페이지에만 존재 → 여기로 이관
     ============================================================ */
  function injectScript(src, isCritical) {
    if (document.querySelector('script[src*="' + src + '"]')) return;
    var s = document.createElement('script');
    s.src = src;
    // 중요 스크립트(popup.js)는 동기 로드 — 비동기 타이밍으로 팝업이 누락되지 않도록 보장
    s.async = !isCritical;
    s.onerror = function() {
      // 로드 실패 시 1회 재시도 (네트워크 지연/캐시 실패 대응)
      if (!s.getAttribute('data-retried')) {
        s.setAttribute('data-retried', '1');
        var retry = document.createElement('script');
        retry.src = src;
        retry.async = !isCritical;
        document.body.appendChild(retry);
      }
    };
    document.body.appendChild(s);
  }

  function loadCommonScripts() {
    injectScript('/common/js/push.js?v=20260814a', false);
    // 네이티브 앱(Capacitor) 푸시 — 브라우저에서는 내부에서 조용히 무시됨
    injectScript('/common/js/native-push.js?v=20260911a', false);
    injectScript('/common/js/popup.js?v=20260814a', true);
    loadStudentGuide();
    loadDirectorGuide();
    loadBranchGuide();
  }

  /* ---- 학생 첫 접속 사용가이드 (role=student 전용) ---- */
  function loadStudentGuide() {
    var user = null;
    try { user = JSON.parse(localStorage.getItem('user')); } catch (e) { user = null; }
    if (!user || user.role !== 'student') return;

    // CSS 주입 (중복 방지)
    if (!document.querySelector('link[href*="student-guide.css"]')) {
      var css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = '/common/css/components/student-guide.css?v=20260913z';
      document.head.appendChild(css);
    }
    // JS 주입
    injectScript('/common/js/student-guide.js?v=20260913z', false);
  }

  /* ---- 원장 첫 접속 사용가이드 (role=director 전용) ---- */
  function loadDirectorGuide() {
    var user = null;
    try { user = JSON.parse(localStorage.getItem('user')); } catch (e) { user = null; }
    if (!user || user.role !== 'director') return;

    // CSS 주입 (중복 방지 — 학생/원장 공용 파일)
    if (!document.querySelector('link[href*="student-guide.css"]')) {
      var css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = '/common/css/components/student-guide.css?v=20260913z';
      document.head.appendChild(css);
    }
    // JS 주입
    injectScript('/common/js/director-guide.js?v=20260913z', false);
  }

  /* ---- 에듀케어 첫 접속 사용가이드 (role=branch_admin 전용) ---- */
  function loadBranchGuide() {
    var user = null;
    try { user = JSON.parse(localStorage.getItem('user')); } catch (e) { user = null; }
    if (!user || user.role !== 'branch_admin') return;

    // CSS 주입 (중복 방지 — 학생/원장/에듀케어 공용 파일)
    if (!document.querySelector('link[href*="student-guide.css"]')) {
      var css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = '/common/css/components/student-guide.css?v=20260913z';
      document.head.appendChild(css);
    }
    // JS 주입
    injectScript('/common/js/branch-guide.js?v=20260913z', false);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadCommonScripts);
  } else {
    loadCommonScripts();
  }

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
    setupHamburger();
    handleLogoutBtn();
    setupCardTables();
  }

  /* ---- 모바일 카드형 테이블: thead → td data-label 자동 주입 + 배지/강조 ---- */
  function setupCardTables() {
    // 상태값 → 배지 클래스 매핑
    function statusClass(val) {
      var v = String(val || '').trim();
      if (!v) return '';
      if (/(활성|승인|완료|공개|운영중|정상|납부|성공|성공적)/.test(v)) return 'card-badge badge-green';
      if (/(정지|거절|취소|비공개|중지|실패|미납|탈퇴|블랙)/.test(v)) return 'card-badge badge-red';
      if (/(대기|보류|심사|대기중|미승인|진행중|운영 예정)/.test(v)) return 'card-badge badge-amber';
      if (/(학생|학부모|원장|강사|관리자|에듀케어)/.test(v)) return 'card-badge badge-blue';
      return 'card-badge badge-gray';
    }
    function labelTable(table) {
      var thead = table.querySelector('thead tr');
      if (!thead) return;
      var headers = [];
      thead.querySelectorAll('th').forEach(function(th) {
        headers.push(th.textContent.trim());
      });
      table.querySelectorAll('tbody tr').forEach(function(tr) {
        if (tr.querySelectorAll('td').length !== headers.length) return;
        tr.querySelectorAll('td').forEach(function(td, i) {
          if (!td.hasAttribute('data-label') && headers[i]) {
            td.setAttribute('data-label', headers[i]);
          }
          // 상태/역할/등급/구분 값 → 배지 스타일
          var lbl = td.getAttribute('data-label') || '';
          if (/(상태|역할|등급|구분|타입|처리상태|결제상태)/.test(lbl) && !td.querySelector('.card-badge')) {
            var raw = td.textContent.trim();
            var cls = statusClass(raw);
            if (cls) {
              var badge = document.createElement('span');
              badge.className = cls;
              badge.textContent = raw;
              // 기존 텍스트 노드 제거 후 배지 삽입
              td.querySelectorAll('*').forEach(function(n) { n.remove(); });
              td.textContent = '';
              td.appendChild(badge);
            }
          }
          // 금액/매출/금액 관련 → 강조
          if (/(금액|매출|금액|포인트|잔액)/.test(lbl) && !td.querySelector('.card-amount')) {
            var amt = td.textContent.trim();
            if (/[\d,]+원|\d+/.test(amt)) {
              var span = document.createElement('span');
              span.className = 'card-amount';
              span.textContent = amt;
              td.textContent = '';
              td.appendChild(span);
            }
          }
        });
      });
    }
    document.querySelectorAll('table[data-card-view]').forEach(labelTable);
    // 동적 렌더링 대응 (tbody 변경 감지)
    var observer = new MutationObserver(function(mutations) {
      mutations.forEach(function(m) {
        if (m.type === 'childList' && m.target.tagName === 'TBODY') {
          var table = m.target.closest ? m.target.closest('table') : null;
          if (table && table.hasAttribute('data-card-view')) labelTable(table);
        }
      });
    });
    document.querySelectorAll('table[data-card-view]').forEach(function(t) {
      var tb = t.querySelector('tbody');
      if (tb) observer.observe(tb, { childList: true, subtree: true });
    });
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

  /* ---- 모바일 햄버거 메뉴 토글 (Sidebar Drawer) ---- */
  function setupHamburger() {
    var btn = document.getElementById('hamburgerBtn');
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');
    if (!btn || !sidebar) return;
    if (btn.getAttribute('data-hamburger-bound') === 'true') return;
    btn.setAttribute('data-hamburger-bound', 'true');

    function isMobile() {
      return window.matchMedia('(max-width: 768px)').matches;
    }
    function toggleSidebar(e) {
      e.preventDefault();
      e.stopPropagation();
      var isOpen = sidebar.classList.toggle('open');
      if (overlay) overlay.classList.toggle('visible', isOpen);
      document.body.classList.toggle('sidebar-open', isOpen);
      btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    function closeSidebar() {
      sidebar.classList.remove('open');
      if (overlay) overlay.classList.remove('visible');
      document.body.classList.remove('sidebar-open');
      btn.setAttribute('aria-expanded', 'false');
    }

    btn.addEventListener('click', toggleSidebar);
    if (overlay) overlay.addEventListener('click', closeSidebar);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && sidebar.classList.contains('open')) closeSidebar();
    });

    // Top Navbar 레이아웃 (sidebar 없음) 지원: 햄버거 → center 메뉴 드롭다운
    var topCenter = document.querySelector('.top-navbar-center');
    if (topCenter && !document.querySelector('.app-layout .sidebar')) {
      btn.classList.add('topnav-hamburger');
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var nav = document.querySelector('.top-navbar');
        if (!nav) return;
        var open = nav.classList.toggle('center-open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        document.body.classList.toggle('sidebar-open', open);
      });
      document.addEventListener('click', function(e) {
        var nav = document.querySelector('.top-navbar');
        if (nav && nav.classList.contains('center-open') && !nav.contains(e.target)) {
          nav.classList.remove('center-open');
          document.body.classList.remove('sidebar-open');
          btn.setAttribute('aria-expanded', 'false');
        }
      });
    }
    // 모바일에서 메뉴 링크 선택 시 자동 닫기
    sidebar.querySelectorAll('a').forEach(function(link) {
      link.addEventListener('click', function() {
        if (isMobile()) closeSidebar();
      });
    });
    // 리사이즈 시 데스크톱 전환 → 닫힘 상태 정리
    window.addEventListener('resize', function() {
      if (!isMobile() && sidebar.classList.contains('open')) closeSidebar();
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
          // 페이지 커스텀 이벤트 — 각 페이지에서 수신해 자동 갱신 (예: 강좌 자료 변경)
          try {
            window.dispatchEvent(new CustomEvent('app:notification', { detail: data.data || {} }));
          } catch (ce) {}
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

  /* ============================================================
     누비다머신 잠금 → 네비 링크 숨김 가드 (09/09 미러 수정)
     문제: auth.js를 로드하지 않는 페이지(courses, portfolio 등)는
     잠금 가드(applyMachineLock)가 실행되지 않아, 누비다머신이
     잠긴 상태인데도 해당 페이지의 누비다머신 링크가 그대로 보였다.
     → 모든 페이지가 공통 로드하는 nav.js에서 처리하여 커버한다.
     - auth.js가 로드된 페이지(window.applyMachineLock 존재):
       이미 auth.js가 처리하므로 여기선 무해한 멱등 실행만.
     - auth.js가 없는 페이지: 자체로 숨김 + /auth/me 한 번 호출해
       최신 잠금(서버)까지 반영.
     ============================================================ */
  (function() {
    function hasAuthMachineApply() {
      try { return typeof window.applyMachineLock === 'function'; } catch (e) { return false; }
    }
    function applyNavMachineLock() {
      var user = null;
      try { user = JSON.parse(localStorage.getItem('user') || 'null'); } catch (e) { user = null; }
      var locked = !!(user && user.role === 'student' && user.nubida_machine_locked);
      var links = document.querySelectorAll('a[href*="ml-studio.html"], a[href*="ml-arduino.html"]');
      var i, a;
      if (locked) {
        for (i = 0; i < links.length; i++) {
          a = links[i];
          if (a.style.display !== 'none') { a.style.display = 'none'; a.setAttribute('data-ml-hidden', '1'); }
        }
      } else {
        for (i = 0; i < links.length; i++) {
          a = links[i];
          if (a.getAttribute('data-ml-hidden') === '1') { a.style.display = ''; a.removeAttribute('data-ml-hidden'); }
        }
      }
      return locked;
    }
    // 1차 즉시 적용(저장된 user 기준) — auth.js가 처리했어도 멱등
    if (!hasAuthMachineApply()) { applyNavMachineLock(); }
    // auth.js가 없는 페이지: 최신(서버) 잠금을 1회 반영 후 재적용
    if (!hasAuthMachineApply()) {
      var t = localStorage.getItem('token') || localStorage.getItem('access_token');
      if (t) {
        fetch('/api/v1/auth/me', { headers: { 'Authorization': 'Bearer ' + t } })
          .then(function(r) { return r.json(); })
          .then(function(j) {
            if (j && j.data) { try { localStorage.setItem('user', JSON.stringify(j.data)); } catch (e) {} }
            applyNavMachineLock();
          })
          .catch(function() { /* 무시 */ });
      }
    }
  })();
})();
