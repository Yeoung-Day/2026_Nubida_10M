/* ============================================================
   누비다플랫폼 — 원장(director) 첫 접속 사용가이드 (스텝별 투어)
   - student-guide.js와 동일 엔진 구조 (2026-08-07, 대표님 6단계 확정 — 진도/보고 스텝 제거)
   - 최초 로그인 시 자동 표시 (onboarding_done=false)
   - 이후에도 topnav "❓ 가이드" 버튼으로 재생 가능
   - 스텝마다 대상 화면 스크롤 + 라이트업(하이라이트)
   - 마지막 "완료" 시 PATCH /auth/me/onboarding 호출
   - 학생 가이드 수정사항 동일 적용: 예시/샘플 화면 + 진입 경로 + 완료 후 흐름
   ============================================================ */
(function() {
  'use strict';

  var GUIDE_PARAM = 'guide';   // URL 파라미터: ?guide=N

  /* ============================================================
     투어 스텝 정의 — 대표님 확정 6단계 (2026-08-07, 진도/보고 제거)
     page     : 이동할 원장 페이지 (pages/director/ 하위)
     selector : 하이라이트할 대상 요소 (없으면 모달만 표시)
     nav      : 진입 경로 안내 (전 스텝 공통)
     flow     : 단계별 한 흐름 안내 (진입→사용→저장→완료 후 상태)
     sample   : 채워진 예시/샘플 화면 (초기 데이터 없음 해소)
     ============================================================ */
  var STEPS = [
    {
      n: 1, icon: '👋', title: '누비다플랫폼 원장 포털에 오신 걸 환영합니다! 🎉',
      desc: '원장 전용 업무 공간입니다. 학급·수강생 관리부터 출결, 포트폴리오 승인, 보고까지 모든 업무를 이 가이드로 빠르게 익혀보세요.',
      page: 'dashboard.html', selector: '.stats-grid',
      nav: { icon: '📊', label: '상단 [대시보드] · 사이드바 [대시보드]', path: '로그인 후 가장 먼저 보이는 화면이에요' },
      sample: {
        label: '💡 지금은 데이터가 없지만, 이렇게 채워져요',
        html:
          '<div class="sg-samp-grid">' +
            '<div class="sg-samp-stat"><b>3</b><span>운영 중 학급</span></div>' +
            '<div class="sg-samp-stat"><b>24</b><span>수강생</span></div>' +
            '<div class="sg-samp-stat"><b>120만원</b><span>이번 달 매출</span></div>' +
          '</div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#EEF0FE">🏫</div>' +
          '<div class="sg-samp-info"><b>1반 (파이썬 기초)</b><span>수강생 8명 · 출석률 92%</span></div></div>'
      }
    },
    {
      n: 2, icon: '🏫', title: '🏫 학급 / 수강생 관리',
      desc: '학급을 만들고 수강생을 등록·배정·이동시키는 전 과정을 알아볼게요.',
      page: 'classes.html', selector: '.class-card, .class-grid, #classList',
      nav: { icon: '🏫', label: '사이드바 [학급 관리] · 상단 [학급▾ → 학급 관리]', path: 'classes.html · 학생 등록은 [학생 관리]' },
      flow: [
        '학급 생성 — 학급 관리에서 새 학급을 만들고 이름·강좌를 연결해요',
        '수강생 등록 — 학생 관리(👤)에서 수강생을 등록하거나 가입 신청을 승인해요',
        '학급 배정 — 학급을 선택하고 수강생을 추가해 편성해요',
        '반 이동 — 학생을 다른 학급으로 이동할 수 있어요 (계정·학습 기록은 유지)',
        '완료 후 — 학급별 학생 목록이 출결·성적·진도에 자동 연동돼요'
      ],
      sample: {
        label: '💡 학급 목록은 이렇게 채워져요',
        html:
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#E8F5E9">🏫</div>' +
          '<div class="sg-samp-info"><b>1반 · 파이썬 기초</b><span>수강생 8명 · 담당 김선생님</span></div></div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#FFF3E0">🏫</div>' +
          '<div class="sg-samp-info"><b>2반 · 웹 개발</b><span>수강생 6명 · 담당 이선생님</span></div></div>'
      }
    },
    {
      n: 3, icon: '📅', title: '📅 출결 관리',
      desc: '출결부를 만들고 학생 출석을 체크·저장하고, 저장 후 어떻게 반영되는지 알아볼게요.',
      page: 'attendance.html', selector: '.attendance-table, #attendanceList, .card',
      nav: { icon: '📅', label: '사이드바 [출결 관리] · 상단 [학급▾ → 출결 관리]', path: 'attendance.html' },
      flow: [
        '출결부 생성 — 학급과 날짜를 선택해 출결부를 만들어요',
        '출석 체크 — 학생별로 출석·결석·지각·조퇴를 체크해요',
        '저장 — 저장 버튼으로 기록을 확정해요',
        '완료 후 — 학생 화면에 출석 상태가 반영되고 출석률 통계가 갱신돼요'
      ],
      sample: {
        label: '💡 출결부는 이렇게 채워져요',
        html:
          '<div class="sg-samp-noti"><span>✅</span><div><b>김수강 · 출석</b><small>오전 9:00 체크</small></div></div>' +
          '<div class="sg-samp-noti"><span>⏰</span><div><b>이학생 · 지각</b><small>오전 9:15 체크</small></div></div>' +
          '<div class="sg-samp-noti"><span>❌</span><div><b>박결석 · 결석</b><small>사유 미입력</small></div></div>'
      }
    },
    {
      n: 4, icon: '🎨', title: '🎨 포트폴리오 관리 (승인·피드백)',
      desc: '학생이 제출한 포트폴리오를 확인하고 승인·피드백하는 전 과정을 알아볼게요.',
      page: 'portfolio.html', selector: '#portfolioList, .portfolio-grid, .card',
      nav: { icon: '🎨', label: '상단 [보고▾ → 포트폴리오] · 사이드바 [포트폴리오]', path: 'portfolio.html' },
      flow: [
        '확인 — 학생이 제출/발행한 포트폴리오 목록을 확인해요',
        '검토 — 내용과 첨부 자료(이미지·작품)를 검토해요',
        '승인/피드백 — 승인하거나 수정 의견을 학생에게 전달해요',
        '완료 후 — 승인된 포트폴리오는 전시/발표 자료로 노출되고 학생에게 결과가 통보돼요'
      ],
      sample: {
        label: '💡 포트폴리오 관리 화면은 이렇게 채워져요',
        html:
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#F3E5F5">🖼️</div>' +
          '<div class="sg-samp-info"><b>나의 첫 학습 기록</b><span class="sg-badge wait">승인 대기</span><small>김수강 · 2026.08.05 제출</small></div></div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#E8F5E9">✅</div>' +
          '<div class="sg-samp-info"><b>파이썬 프로젝트</b><span class="sg-badge ok">승인됨</span><small>전시 중 · 2026.07.30</small></div></div>'
      }
    },
    {
      n: 5, icon: '✅', title: '✅ 승인 관리',
      desc: '회원가입·기능 사용 등 대기 중인 승인 요청을 처리하는 방법을 알아볼게요.',
      page: 'approvals.html', selector: '.approval-list, #approvalList, .card',
      nav: { icon: '✅', label: '상단 [승인] · 사이드바 [승인 관리]', path: 'approvals.html' },
      flow: [
        '확인 — 대기 중인 승인 요청(회원가입 등) 목록을 확인해요',
        '처리 — 승인 또는 반려를 선택해요',
        '완료 후 — 승인된 계정은 로그인할 수 있고, 반려 시 사유가 안내돼요'
      ],
      sample: {
        label: '💡 승인 요청 목록은 이렇게 채워져요',
        html:
          '<div class="sg-samp-noti"><span>👤</span><div><b>김수강 · 회원가입</b><span class="sg-badge wait">승인 대기</span><small>2026.08.06 신청</small></div></div>' +
          '<div class="sg-samp-noti"><span>✅</span><div><b>이학생 · 가입 승인됨</b><span class="sg-badge ok">처리 완료</span><small>2026.08.05</small></div></div>'
      }
    },
    {
      n: 6, icon: '⚙️', title: '⚙️ 설정',
      desc: '계정 정보와 학원 설정을 관리할 수 있어요. 가이드가 끝났습니다. 원활한 학원 운영 되세요! 🎉',
      page: 'settings.html', selector: '.card',
      nav: { icon: '⚙️', label: '상단 [설정] · 사이드바 [설정]', path: 'settings.html' },
      sample: {
        label: '💡 설정 화면은 이렇게 채워져요',
        html:
          '<div class="sg-samp-noti"><span>👤</span><div><b>내 계정</b><small>이름 · 연락처 · 비밀번호 관리</small></div></div>' +
          '<div class="sg-samp-noti"><span>🏫</span><div><b>학원 정보</b><small>학원명 · 운영 시간 · 안내 문구</small></div></div>' +
          '<div class="sg-samp-noti"><span>🔔</span><div><b>알림 설정</b><small>받을 알림을 선택해요</small></div></div>'
      }
    }
  ];

  var currentIdx = 0;       // 0-based 스텝 인덱스
  var tourActive = false;   // 투어 표시 중 여부
  var isOnboarding = false; // 최초 온보딩 자동 표시 여부
  var timer = null;

  /* ============================================================
     유틸
     ============================================================ */
  function getCurrentUser() {
    try { return JSON.parse(localStorage.getItem('user')); }
    catch (e) { return null; }
  }

  function isDirectorPage() {
    return window.location.pathname.indexOf('/pages/director/') !== -1;
  }

  function currentPageFile() {
    return window.location.pathname.split('/').pop();
  }

  function getGuideParam() {
    var m = window.location.search.match(/[?&]guide=(\d+)/);
    return m ? parseInt(m[1], 10) : 0;
  }

  function gotoPage(stepIdx) {
    var step = STEPS[stepIdx];
    if (!step) return;
    window.location.href = step.page + '?' + GUIDE_PARAM + '=' + step.n;
  }

  /* ============================================================
     투어 DOM 생성/제거
     ============================================================ */
  function removeTour() {
    tourActive = false;
    ['sg-overlay', 'sg-highlight', 'sg-modal'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.parentNode.removeChild(el);
    });
    if (timer) { clearTimeout(timer); timer = null; }
    document.body.classList.remove('sg-tour-open');
  }

  function showTour(stepIdx) {
    var step = STEPS[stepIdx];
    if (!step) return;

    // 현재 페이지가 스텝 대상 페이지인지 — 아니면 이동
    if (step.page !== currentPageFile()) {
      gotoPage(stepIdx);
      return;
    }

    currentIdx = stepIdx;
    tourActive = true;
    removeTour();
    tourActive = true;   // removeTour가 false로 리셋하므로 재설정
    document.body.classList.add('sg-tour-open');

    // 대상 요소 탐색 (없으면 모달만)
    var target = null;
    if (step.selector === '.card') {
      target = document.querySelector('.card'); // settings: 첫 번째 카드
    } else {
      target = document.querySelector(step.selector);
    }

    // ── 라이트업 하이라이트 ──
    if (target) {
      var hl = document.createElement('div');
      hl.id = 'sg-highlight';
      hl.className = 'sg-highlight';
      document.body.appendChild(hl);
      positionHighlight(hl, target);
      try { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { target.scrollIntoView(); }
      // 비동기 데이터 로딩/스크롤 애니메이션 후 위치 재계산 (여러 타이밍)
      [250, 600, 1200, 2000].forEach(function(delay) {
        setTimeout(function() {
          if (tourActive && document.getElementById('sg-highlight')) {
            var t2 = step.selector === '.card' ? document.querySelector('.card') : document.querySelector(step.selector);
            if (t2) positionHighlight(document.getElementById('sg-highlight'), t2);
          }
        }, delay);
      });
    } else {
      // 대상 요소 없음 → 페이지 상단으로 스크롤
      try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
    }

    // ── 오버레이 (하이라이트 바깥 영역 클릭 차단용) ──
    var overlay = document.createElement('div');
    overlay.id = 'sg-overlay';
    overlay.className = 'sg-overlay';
    overlay.addEventListener('click', function(e) {
      e.stopPropagation();
    });
    document.body.appendChild(overlay);

    // ── 가이드 모달 ──
    var total = STEPS.length;
    var isFirst = stepIdx === 0;
    var isLast = stepIdx === total - 1;

    var dots = '';
    for (var i = 0; i < total; i++) {
      dots += '<span class="sg-dot' + (i === stepIdx ? ' active' : '') + '"></span>';
    }

    // ── 네비게이션 경로 배너 (전 스텝 공통) ──
    var navHtml = '';
    if (step.nav) {
      navHtml =
        '<div class="sg-nav">' +
          '<span class="sg-nav-ic">🧭</span>' +
          '<div class="sg-nav-tx">' +
            '<span class="sg-nav-label">진입 경로</span>' +
            '<b>' + step.nav.icon + ' ' + step.nav.label + '</b>' +
            (step.nav.path ? '<small>' + step.nav.path + '</small>' : '') +
          '</div>' +
        '</div>';
    }

    // ── 단계별 한 흐름 안내 ──
    var flowHtml = '';
    if (step.flow && step.flow.length) {
      var flowItems = '';
      for (var fi = 0; fi < step.flow.length; fi++) {
        flowItems += '<li>' + step.flow[fi] + '</li>';
      }
      flowHtml =
        '<div class="sg-flow">' +
          '<div class="sg-flow-title">📋 한눈에 보는 흐름</div>' +
          '<ol>' + flowItems + '</ol>' +
        '</div>';
    }

    // ── 채워진 예시/샘플 화면 ──
    var sampleHtml = '';
    if (step.sample) {
      sampleHtml =
        '<div class="sg-sample">' +
          '<div class="sg-sample-label">' + step.sample.label + '</div>' +
          '<div class="sg-sample-box">' + step.sample.html + '</div>' +
        '</div>';
    }

    var modal = document.createElement('div');
    modal.id = 'sg-modal';
    modal.className = 'sg-modal';
    modal.innerHTML =
      '<button class="sg-close" id="sgClose" title="닫기">✕</button>' +
      '<div class="sg-progress"><div class="sg-progress-bar" style="width:' + Math.round(((stepIdx + 1) / total) * 100) + '%"></div></div>' +
      '<div class="sg-scroll">' +
        navHtml +
        '<div class="sg-body">' +
          '<div class="sg-icon">' + step.icon + '</div>' +
          '<div class="sg-content">' +
            '<div class="sg-step-label">STEP ' + step.n + ' / ' + total + '</div>' +
            '<h3 class="sg-title">' + step.title + '</h3>' +
            '<p class="sg-desc">' + step.desc + '</p>' +
          '</div>' +
        '</div>' +
        flowHtml +
        sampleHtml +
      '</div>' +
      '<div class="sg-dots">' + dots + '</div>' +
      '<div class="sg-actions">' +
        (isFirst ? '' : '<button class="sg-btn sg-btn-ghost" id="sgPrev">← 이전</button>') +
        '<button class="sg-btn sg-btn-ghost" id="sgSkip">건너뛰기</button>' +
        (isLast
          ? '<button class="sg-btn sg-btn-primary" id="sgNext">완료 🎉</button>'
          : '<button class="sg-btn sg-btn-primary" id="sgNext">다음 →</button>') +
      '</div>';

    document.body.appendChild(modal);
    modal.classList.add('sg-show');

    // ── 버튼 바인딩 ──
    document.getElementById('sgClose').addEventListener('click', closeTour);
    document.getElementById('sgSkip').addEventListener('click', skipTour);
    var prevBtn = document.getElementById('sgPrev');
    if (prevBtn) prevBtn.addEventListener('click', function() { gotoPage(currentIdx - 1); });
    var nextBtn = document.getElementById('sgNext');
    nextBtn.addEventListener('click', function() {
      if (isLast) {
        completeTour();
      } else {
        gotoPage(currentIdx + 1);
      }
    });

    // ── 키보드 (Esc = 닫기, → = 다음) ──
    document.addEventListener('keydown', sgKeyHandler);
  }

  function sgKeyHandler(e) {
    if (!tourActive) return;
    if (e.key === 'Escape') { closeTour(); }
    else if (e.key === 'ArrowRight') {
      var last = currentIdx === STEPS.length - 1;
      if (last) completeTour(); else gotoPage(currentIdx + 1);
    }
    else if (e.key === 'ArrowLeft' && currentIdx > 0) { gotoPage(currentIdx - 1); }
  }

  /* ============================================================
     하이라이트 위치 계산
     ============================================================ */
  function positionHighlight(hl, target) {
    var rect = target.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) {
      hl.style.display = 'none';
      return;
    }
    var pad = 6;
    var scrollY = window.scrollY || window.pageYOffset;
    var scrollX = window.scrollX || window.pageXOffset;
    hl.style.top = (rect.top + scrollY - pad) + 'px';
    hl.style.left = (rect.left + scrollX - pad) + 'px';
    hl.style.width = (rect.width + pad * 2) + 'px';
    hl.style.height = (rect.height + pad * 2) + 'px';
    hl.style.display = 'block';
    // 하이라이트 박스는 클릭 통과
    hl.style.pointerEvents = 'none';
  }

  /* ============================================================
     완료/건너뛰기/닫기
     ============================================================ */
  function completeTour() {
    document.removeEventListener('keydown', sgKeyHandler);
    removeTour();
    var user = getCurrentUser();
    if (user) { user.onboarding_done = true; localStorage.setItem('user', JSON.stringify(user)); }
    // 서버 저장 (실패해도 진행 — 다음 접속 때 다시 표시됨)
    try {
      apiPatch('/auth/me/onboarding', { onboarding_done: true }).catch(function() {});
    } catch (e) {}
    window.location.href = 'dashboard.html';
  }

  function skipTour() {
    document.removeEventListener('keydown', sgKeyHandler);
    removeTour();
    window.location.href = 'dashboard.html';
  }

  function closeTour() {
    document.removeEventListener('keydown', sgKeyHandler);
    removeTour();
    window.location.href = 'dashboard.html';
  }

  /* ============================================================
     가이드 UI 주입 (topnav ❓ 버튼 + 사이드바 항목)
     ============================================================ */
  function bindGuideBtn(btn) {
    if (!btn) return;
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      gotoPage(0);
    });
  }

  function injectGuideUI() {
    // 1) 상단 내비게이션 (원장 페이지는 .top-nav-right, topnav-director.html은 .top-navbar-right)
    var right = document.querySelector('.top-nav-right') || document.querySelector('.top-navbar-right');
    if (right) {
      var existing = document.getElementById('sgGuideBtn');
      if (existing) {
        bindGuideBtn(existing);
      } else {
        var btn = document.createElement('button');
        btn.id = 'sgGuideBtn';
        btn.className = 'sg-guide-btn';
        btn.type = 'button';
        btn.title = '사용 가이드 다시 보기';
        btn.innerHTML = '<span class="sg-btn-ico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.4 9.2a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.2-2.6 3.9"/><path d="M12 17.3h.01"/></svg></span> <span>가이드</span>';
        bindGuideBtn(btn);
        right.insertBefore(btn, right.firstChild);
      }
    }

    // 2) 사이드바 메뉴 (모바일 햄버거 포함)
    var nav = document.querySelector('.sidebar-nav');
    if (nav && !nav.querySelector('[data-sg-guide-link]')) {
      var link = document.createElement('a');
      link.className = 'nav-item';
      link.setAttribute('data-sg-guide-link', 'true');
      link.href = '#';
      link.innerHTML = '<span class="icon"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.4 9.2a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.2-2.6 3.9"/><path d="M12 17.3h.01"/></svg></span><span class="nav-label">사용 가이드</span>';
      link.addEventListener('click', function(e) {
        e.preventDefault();
        // 모바일 사이드바 닫기
        var sidebar = document.getElementById('sidebar');
        if (sidebar) { sidebar.classList.remove('open'); }
        var overlay = document.getElementById('sidebarOverlay');
        if (overlay) overlay.classList.remove('visible');
        gotoPage(0);
      });
      nav.appendChild(link);
    }
  }

  /* ============================================================
     자동 표시 — 원장 대시보드 진입 시 onboarding_done=false 면 투어 시작
     ============================================================ */
  function maybeAutoStart() {
    if (!isDirectorPage()) return;
    var user = getCurrentUser();
    if (!user) return;
    if (user.role !== 'director') return;             // 타 역할 무영향
    if (getGuideParam() > 0) return;                  // 이미 투어 중 (URL 파라미터)
    if (currentPageFile() !== 'dashboard.html') return; // 대시보드 진입 시에만
    if (user.onboarding_done === true) return;        // 완료한 사용자는 미표시
    if (user.onboarding_done === false || user.onboarding_done == null) {
      isOnboarding = true;
      timer = setTimeout(function() { showTour(0); }, 600); // 로딩 후 자연스럽게
    }
  }

  /* ============================================================
     초기화 — nav.js에서 role=director일 때 주입됨
     ============================================================ */
  function init() {
    if (!isDirectorPage()) return;
    var user = getCurrentUser();
    if (!user || user.role !== 'director') return;

    // 가이드 버튼/메뉴 주입
    injectGuideUI();

    // URL ?guide=N → 해당 스텝 표시 (재접속 가이드)
    var g = getGuideParam();
    if (g > 0 && g <= STEPS.length) {
      showTour(g - 1);
      return;
    }

    // 자동 표시 — auth.js refreshCurrentUser 완료 후 실행 (localStorage.user 최신화 보장)
    if (typeof onAuthReady === 'function') {
      onAuthReady(maybeAutoStart);
    } else {
      maybeAutoStart();
    }
  }

  // 스크롤/리사이즈 시 하이라이트 재배치
  var hlTimer = null;
  function reposition() {
    if (!tourActive) return;
    var hl = document.getElementById('sg-highlight');
    if (!hl) return;
    var step = STEPS[currentIdx];
    if (!step) return;
    var target = step.selector === '.card' ? document.querySelector('.card') : document.querySelector(step.selector);
    if (target) positionHighlight(hl, target);
  }
  window.addEventListener('resize', function() {
    if (hlTimer) clearTimeout(hlTimer);
    hlTimer = setTimeout(reposition, 150);
  });

  // 페이지 이동(뷰포트 전환) 후 재배치
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
