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
    s.src = '/common/js/push.js?v=20260610a';
    s.async = true;
    document.body.appendChild(s);
  }
})();
