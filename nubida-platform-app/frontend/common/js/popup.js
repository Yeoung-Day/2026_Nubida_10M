/* ============================================================
   누비다플랫폼 — 공지 팝업 (전체 화면 공지)
   - GET /api/v1/platform/notices/popup (인증 사용자)
   - GET /api/v1/platform/notices/popup-public (비로그인)
   - images 컬럼(JSON 배열) + content 내 이미지 URL 모두 렌더
   - 기간 설정 + 특정 사용자 지정 + 오늘 하루 보지 않기
   ============================================================ */
(function() {
  'use strict';

  // ── 중복 실행 방지 (head 직접 로드 + nav.js 주입 이중 경로 대응) ──
  if (window.__nubidaPopupLoaded) return;
  window.__nubidaPopupLoaded = true;

  // ── 팝업 CSS 동적 주입 ──
  function injectCss() {
    if (document.getElementById('nubida-popup-css')) return;
    var link = document.createElement('link');
    link.id = 'nubida-popup-css';
    link.rel = 'stylesheet';
    link.href = '/common/css/components/popup.css?v=20260910c';
    document.head.appendChild(link);
  }

  // ── 오늘 날짜 키 (YYYY-MM-DD) ──
  function todayKey() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  // ── HTML 이스케이프 ──
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ── 활성 팝업 조회 → 순차 표시 ──
  function loadPopup() {
    injectCss();
    var token = localStorage.getItem('token') || localStorage.getItem('access_token');

    var url = token ? '/api/v1/platform/notices/popup'
                    : '/api/v1/platform/notices/popup-public';
    var opts = token ? { headers: { 'Authorization': 'Bearer ' + token } } : {};

    fetch(url, opts)
      .then(function(r) {
        // 토큰이 만료/무효(401/403)면 공개 팝업으로 재시도 (로그아웃·계정삭제 대응)
        if (token && (r.status === 401 || r.status === 403)) {
          return fetch('/api/v1/platform/notices/popup-public')
            .then(function(r2) { return r2.json().catch(function() { return {}; }); });
        }
        return r.json().catch(function() { return {}; });
      })
      .then(function(json) {
        var list = (json && json.data) || [];
        var tKey = todayKey();
        var queue = [];
        for (var i = 0; i < list.length; i++) {
          var key = 'np_hidden_' + list[i].id + '_' + tKey;
          if (localStorage.getItem(key)) continue;
          queue.push(list[i]);
        }
        if (queue.length === 0) return;
        showQueue(queue, tKey);
      })
      .catch(function() { /* 팝업 실패는 무시 */ });
  }

  // ── images 컬럼(JSON 배열 문자열) → URL 배열 ──
  function parseImages(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw.filter(Boolean);
    try {
      var arr = JSON.parse(raw);
      if (Array.isArray(arr)) return arr.filter(Boolean);
    } catch (e) { /* 단일 URL 문자열일 수 있음 */ }
    var s = String(raw).trim();
    return s ? [s] : [];
  }

  var IMG_RE = /^(https?:\/\/\S+|\/uploads\/\S+|\/static\/\S+|\/common\/\S+|\/assets\/\S+|data:image\/\S+)$/i;

  // ── 본문 + 이미지 렌더 ──
  // 1) images 컬럼 이미지를 먼저 상단에 배치
  // 2) content 내 이미지 URL 라인도 <img> 로 변환
  function renderBody(el, raw, images) {
    var html = '';

    var imgs = parseImages(images);
    for (var k = 0; k < imgs.length; k++) {
      html += '<figure class="np-figure"><img src="' + esc(imgs[k]) + '" alt="" loading="lazy"></figure>';
    }

    var text = String(raw == null ? '' : raw);
    var parts = text.split(/\r?\n/);
    var buffer = [];

    function flushText() {
      if (!buffer.length) return;
      var joined = buffer.join('\n').trim();
      if (joined) html += '<p class="np-p">' + esc(joined).replace(/\n/g, '<br>') + '</p>';
      buffer = [];
    }

    for (var i = 0; i < parts.length; i++) {
      var line = parts[i].trim();
      if (line && IMG_RE.test(line)) {
        flushText();
        html += '<figure class="np-figure"><img src="' + esc(line) + '" alt="" loading="lazy"></figure>';
      } else {
        buffer.push(parts[i]);
      }
    }
    flushText();

    if (!html) html = '<p class="np-p np-empty">내용이 없습니다.</p>';
    el.innerHTML = html;
  }

  function showQueue(queue, tKey) {
    if (!queue || queue.length === 0) return;
    var n = queue.shift();

    var overlay = document.createElement('div');
    overlay.className = 'np-overlay';
    overlay.innerHTML =
      '<div class="np-modal" role="dialog" aria-modal="true" aria-labelledby="npTitle">' +
        '<div class="np-head">' +
          '<div class="np-head-text">' +
            '<span class="np-eyebrow">NOTICE</span>' +
            '<h3 class="np-title" id="npTitle"></h3>' +
          '</div>' +
        '</div>' +
        '<div class="np-body"></div>' +
        '<div class="np-foot">' +
          '<span class="np-author"></span>' +
          '<div class="np-actions">' +
            '<button class="np-hide-today">오늘 하루 보지 않기</button>' +
            '<button class="np-confirm">확인</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    overlay.querySelector('.np-title').textContent = n.title || '공지사항';
    renderBody(overlay.querySelector('.np-body'), n.content, n.images);

    var author = (n.author ? n.author + ' · ' : '') +
      (n.created_at ? new Date(n.created_at).toLocaleDateString('ko-KR') : '');
    overlay.querySelector('.np-author').textContent = author;

    function close() {
      overlay.classList.remove('show');
      setTimeout(function() {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        showQueue(queue, tKey); // 다음 팝업 표시
      }, 250);
    }

    overlay.querySelector('.np-hide-today').addEventListener('click', function() {
      localStorage.setItem('np_hidden_' + n.id + '_' + tKey, '1');
      close();
    });
    overlay.querySelector('.np-confirm').addEventListener('click', close);
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) close();
    });
    document.addEventListener('keydown', function onEsc(e) {
      if (e.key === 'Escape') { document.removeEventListener('keydown', onEsc); close(); }
    });

    document.body.appendChild(overlay);
    requestAnimationFrame(function() {
      requestAnimationFrame(function() { overlay.classList.add('show'); });
    });
  }

  // ── 실행 ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadPopup);
  } else {
    loadPopup();
  }
})();
