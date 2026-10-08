/* ============================================================
   누비다플랫폼 — 학생 첫 접속 사용가이드 (스텝별 투어)
   - 최초 로그인 시 자동 표시 (onboarding_done=false)
   - 이후에도 topnav "❓ 가이드" 버튼으로 재생 가능
   - 스텝마다 대상 화면 스크롤 + 라이트업(하이라이트)
   - 마지막 "완료" 시 PATCH /auth/me/onboarding 호출
   ============================================================ */
(function() {
  'use strict';

  var GUIDE_PARAM = 'guide';   // URL 파라미터: ?guide=N

  /* ============================================================
     투어 스텝 정의 — 대표님 2차 수정 반영 (2026-08-07)
     page     : 이동할 학생 페이지 (pages/student/ 하위)
     selector : 하이라이트할 대상 요소 (없으면 모달만 표시)
     nav      : 진입 경로 안내 (② 전 스텝 공통)
     flow     : 단계별 한 흐름 안내 (③④ 상세화)
     sample   : 채워진 예시/샘플 화면 (① 데이터 없음 해소)
     ============================================================ */
  var STEPS = [
    {
      n: 1, icon: '👋', title: '누비다플랫폼에 오신 걸 환영합니다! 🎉',
      desc: '학생 전용 학습 공간입니다. 이 가이드를 따라 강좌 학습부터 포트폴리오, 알림, 문의까지 모든 기능을 빠르게 알아보세요.',
      page: 'dashboard.html', selector: '.stats-grid',
      nav: { icon: '🏠', label: '사이드바 [내 대시보드]', path: '로그인 후 가장 먼저 보이는 화면이에요' },
      sample: {
        label: '💡 지금은 데이터가 없지만, 이렇게 채워져요',
        html:
          '<div class="sg-samp-grid">' +
            '<div class="sg-samp-stat"><b>3</b><span>수강 중 강좌</span></div>' +
            '<div class="sg-samp-stat"><b>45%</b><span>평균 진행률</span></div>' +
            '<div class="sg-samp-stat"><b>1,200P</b><span>보유 포인트</span></div>' +
          '</div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#EEF0FE">📖</div>' +
          '<div class="sg-samp-info"><b>파이썬 기초</b><div class="sg-samp-bar"><i style="width:45%"></i></div><span>진행률 45%</span></div></div>'
      }
    },
    {
      n: 2, icon: '📚', title: '📚 강좌 / 학습 — 완료까지 한 흐름',
      desc: '수강 강좌를 선택해 영상·자료·코드를 학습하고, 완료 처리와 완료 후 상태까지 전 과정을 알아볼게요.',
      page: 'courses.html', selector: '#coursesGrid',
      nav: { icon: '📖', label: '사이드바 [수강 강좌] · 모바일 ☰ → 수강 강좌', path: 'courses.html' },
      flow: [
        '강좌 선택 — 수강 강좌 목록에서 강좌 카드를 클릭하면 학습 페이지로 이동해요',
        '학습 — 강좌 안의 영상·자료·파일·코드 콘텐츠를 순서대로 열어 학습해요',
        '진행률 — 콘텐츠를 학습할수록 진행률 바가 채워져요 (몇 % 수강했는지 표시)',
        '완료 처리 — 모든 콘텐츠를 끝내면 "학습 완료" 처리되고 완료 뱃지 ✅가 표시돼요',
        '완료 후 — 완료된 강좌는 수료 표시가 되고, 다음 강좌 학습·성적·출석에 연동돼요'
      ],
      sample: {
        label: '💡 수강 강좌 목록은 이렇게 채워져요',
        html:
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#E8F5E9">🐍</div>' +
          '<div class="sg-samp-info"><b>파이썬 기초</b><div class="sg-samp-bar"><i style="width:45%"></i></div><span>진행률 45%</span></div></div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#FFF3E0">🌐</div>' +
          '<div class="sg-samp-info"><b>웹 개발 입문</b><div class="sg-samp-bar full"><i style="width:100%"></i></div><span>학습 완료 ✅</span></div></div>'
      }
    },
    {
      n: 3, icon: '🎨', title: '🎨 포트폴리오 — 작성부터 승인·전시까지',
      desc: '나의 학습 기록을 포트폴리오로 만들고, 제출·승인·전시되기까지 전 과정을 알아볼게요.',
      page: 'portfolio.html', selector: '#journalContainer',
      nav: { icon: '🎨', label: '사이드바 [포트폴리오] · 모바일 ☰ → 포트폴리오', path: 'portfolio.html' },
      flow: [
        '작성 — 포트폴리오 화면에서 "✏️ 새 기록"을 눌러 제목·내용을 작성해요',
        '업로드 — 학습 자료·이미지·작품 파일을 첨부해요',
        '저장/제출 — 임시저장(나만 보기) 또는 제출/발행(담당자 확인 요청)을 선택해요',
        '승인·피드백 — 원장/본사 담당자가 확인 후 승인하거나 수정 의견을 전달해요',
        '전시 — 승인된 포트폴리오는 발표/전시 자료로 노출돼요',
        '재제출 — 피드백이 오면 내용을 수정한 뒤 다시 제출할 수 있어요'
      ],
      sample: {
        label: '💡 포트폴리오 목록은 이렇게 채워져요',
        html:
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#F3E5F5">🖼️</div>' +
          '<div class="sg-samp-info"><b>나의 첫 학습 기록</b><span class="sg-badge ok">승인됨</span><small>전시 중 · 2026.08.05</small></div></div>' +
          '<div class="sg-samp-course"><div class="sg-samp-thumb" style="background:#E3F2FD">📝</div>' +
          '<div class="sg-samp-info"><b>포트폴리오 연습</b><span class="sg-badge wait">피드백 대기</span><small>수정 후 재제출 가능</small></div></div>'
      }
    },
    {
      n: 4, icon: '🔔', title: '🔔 알림',
      desc: '공지사항·성적·출석 등 중요한 소식이 알림으로 도착해요. 상단 🔔 아이콘과 사이드바 알림 메뉴에서 언제든 확인할 수 있습니다.',
      page: 'notifications.html', selector: '.card',
      nav: { icon: '🔔', label: '상단 🔔 아이콘 (알림 센터) · 사이드바 [알림]', path: 'notifications.html' },
      sample: {
        label: '💡 알림 목록은 이렇게 채워져요',
        html:
          '<div class="sg-samp-noti"><span>📢</span><div><b>개강 안내</b><small>새 강좌가 개설되었어요 · 2시간 전</small></div></div>' +
          '<div class="sg-samp-noti"><span>📊</span><div><b>성적 반영</b><small>1학기 성적이 반영되었어요 · 어제</small></div></div>' +
          '<div class="sg-samp-noti"><span>✅</span><div><b>출석 완료</b><small>오늘 출석이 처리되었어요 · 오전 9:00</small></div></div>'
      }
    },
    {
      n: 5, icon: '💬', title: '💬 문의 (Q&A)',
      desc: '궁금한 점이 있으면 Q&A에 질문을 작성해 보세요. 제목·내용을 입력하고 "📤 질문 보내기"를 누르면 본사에서 빠르게 답변드립니다.',
      page: 'inquiries.html', selector: '#inquiryForm',
      nav: { icon: '❓', label: '사이드바 [Q&A] · 모바일 ☰ → Q&A', path: 'inquiries.html' },
      sample: {
        label: '💡 문의와 답변은 이렇게 표시돼요',
        html:
          '<div class="sg-samp-noti"><span>💬</span><div><b>강좌 수강 기간은 어떻게 되나요?</b><span class="sg-badge ok">답변 완료</span><small>📝 본사: 수강 기간은 6개월입니다.</small></div></div>' +
          '<div class="sg-samp-noti"><span>❓</span><div><b>포트폴리오 제출 방법이 궁금해요</b><span class="sg-badge wait">답변 대기</span></div></div>'
      }
    },
    {
      n: 6, icon: '⚙️', title: '⚙️ 프로필 설정',
      desc: '이름·이메일·연락처 등 개인정보와 비밀번호, 알림 설정을 관리할 수 있어요. 가이드가 끝났습니다. 즐거운 학습 되세요! 🎉',
      page: 'settings.html', selector: '.card',
      nav: { icon: '⚙️', label: '사이드바 [설정] · 모바일 ☰ → 설정', path: 'settings.html' },
      sample: {
        label: '💡 설정 화면은 이렇게 채워져요',
        html:
          '<div class="sg-samp-noti"><span>👤</span><div><b>내 프로필</b><small>이름 · 이메일 · 연락처 수정</small></div></div>' +
          '<div class="sg-samp-noti"><span>🔒</span><div><b>비밀번호 변경</b><small>주기적인 변경을 권장해요</small></div></div>' +
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

  function isStudentPage() {
    return window.location.pathname.indexOf('/pages/student/') !== -1;
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

    // ── 네비게이션 경로 배너 (② 전 스텝 공통) ──
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

    // ── 단계별 한 흐름 안내 (③④ 상세화) ──
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

    // ── 채워진 예시/샘플 화면 (① 데이터 없음 해소) ──
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
  function injectGuideUI() {
    if (document.getElementById('sgGuideBtn')) return;

    // 1) top-nav-right (데스크톱/태블릿)
    var right = document.querySelector('.top-nav-right');
    if (right) {
      var btn = document.createElement('button');
      btn.id = 'sgGuideBtn';
      btn.className = 'sg-guide-btn';
      btn.type = 'button';
      btn.title = '사용 가이드 다시 보기';
      btn.innerHTML = '<span class="sg-btn-ico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.4 9.2a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.2-2.6 3.9"/><path d="M12 17.3h.01"/></svg></span> <span>가이드</span>';
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        gotoPage(0);
      });
      right.insertBefore(btn, right.firstChild);
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
     자동 표시 — 학생 대시보드 진입 시 onboarding_done=false 면 투어 시작
     ============================================================ */
  function maybeAutoStart() {
    if (!isStudentPage()) return;
    var user = getCurrentUser();
    if (!user) return;
    if (user.role !== 'student') return;              // 타 역할 무영향
    if (getGuideParam() > 0) return;                  // 이미 투어 중 (URL 파라미터)
    if (currentPageFile() !== 'dashboard.html') return; // 대시보드 진입 시에만
    if (user.onboarding_done === true) return;        // 완료한 사용자는 미표시
    if (user.onboarding_done === false || user.onboarding_done == null) {
      isOnboarding = true;
      timer = setTimeout(function() { showTour(0); }, 600); // 로딩 후 자연스럽게
    }
  }

  /* ============================================================
     초기화 — nav.js에서 role=student일 때 주입됨
     ============================================================ */
  function init() {
    if (!isStudentPage()) return;
    var user = getCurrentUser();
    if (!user || user.role !== 'student') return;

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
