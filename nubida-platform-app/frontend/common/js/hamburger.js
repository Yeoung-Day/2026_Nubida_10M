/* ============================================================
   누비다플랫폼 v10.0 — Navigation helpers (deprecated - kept for compat)
   ============================================================ */
(function() {
  'use strict';

  /* Push Notification JS 동적 로드 (모든 페이지 공통) */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadPushScript);
  } else {
    loadPushScript();
  }

  function loadPushScript() {
    if (document.querySelector('script[src*="push.js"]')) return;
    var s = document.createElement('script');
    s.src = '/common/js/push.js?v=20260804c';
    s.async = true;
    document.body.appendChild(s);
  }
  /* 공지 팝업은 nav.js에서 공통 로드 (모든 페이지 적용) — 여기서는 중복 방지 가드만 */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadPopupScript);
  } else {
    loadPopupScript();
  }

  function loadPopupScript() {
    if (document.querySelector('script[src*="popup.js"]')) return;
    var s = document.createElement('script');
    s.src = '/common/js/popup.js?v=20260804c';
    s.async = true;
    document.body.appendChild(s);
  }
})();
