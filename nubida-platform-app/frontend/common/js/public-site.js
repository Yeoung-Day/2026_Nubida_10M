/* 누비다플랫폼 — 공개사이트 공통 동적 렌더
   GET /api/v1/public/site-content 결과로 네비/푸터/상담정보/페이지 본문을 교체한다.
   API 실패 시 HTML에 이미 마크업된 정적(기본) 콘텐츠를 그대로 유지한다.
   - 네비      : <div id="navCenter"> 내부를 시드 nav로 교체
   - 푸터 링크 : <div id="footerLinks"> 내부를 시드 footer_links로 교체
   - 상담정보  : [data-c-*] 속성을 가진 요소에 텍스트 주입
   - 페이지본문: <body data-site-page="company|policy|partnership|contact"> 일 때
                 [data-page-title]/[data-page-eyebrow]/#pageSections 에 렌더
*/
(function () {
  'use strict';

  function fillLinks(container, items, linkClass) {
    if (!container || !Array.isArray(items) || !items.length) return;
    var path = location.pathname;
    container.innerHTML = '';
    items.forEach(function (it) {
      var kids = Array.isArray(it.children) ? it.children.filter(function (c) { return c && c.title; }) : null;
      if (kids && kids.length) {
        // ── 하위 메뉴가 있으면 드롭다운으로 렌더 ──
        var dd = document.createElement('div');
        dd.className = 'nav-dropdown';

        var tg = document.createElement('a');
        tg.href = '#';
        tg.className = 'nav-link nav-dropdown-toggle';
        tg.setAttribute('aria-haspopup', 'true');
        tg.setAttribute('aria-expanded', 'false');
        tg.appendChild(document.createTextNode(it.title || ''));
        var caret = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        caret.setAttribute('class', 'nav-caret');
        caret.setAttribute('viewBox', '0 0 24 24');
        caret.setAttribute('fill', 'none');
        caret.setAttribute('stroke', 'currentColor');
        caret.setAttribute('stroke-width', '3');
        caret.setAttribute('stroke-linecap', 'round');
        caret.setAttribute('stroke-linejoin', 'round');
        var poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        poly.setAttribute('points', '6 9 12 15 18 9');
        caret.appendChild(poly);
        tg.appendChild(caret);
        dd.appendChild(tg);

        var menu = document.createElement('div');
        menu.className = 'nav-dropdown-menu';
        menu.setAttribute('role', 'menu');
        kids.forEach(function (kid, idx) {
          if (kid.sep) {
            var sep = document.createElement('div');
            sep.className = 'nav-dropdown-sep';
            menu.appendChild(sep);
            return;
          }
          var a = document.createElement('a');
          a.href = kid.url || '#';
          a.className = 'nav-dropdown-item';
          a.setAttribute('role', 'menuitem');
          if (/^https?:\/\//.test(kid.url || '')) {
            a.target = '_blank';
            a.rel = 'noopener';
          }
          if (kid.icon) {
            var ic = document.createElement('span');
            ic.className = 'nav-dropdown-icon ' + (kid.icon_bg ? 'bg-' + kid.icon_bg : '');
            ic.textContent = kid.icon;
            a.appendChild(ic);
          }
          var tx = document.createElement('span');
          tx.className = 'nav-dropdown-text';
          var t1 = document.createElement('span');
          t1.className = 'nav-dropdown-title';
          t1.textContent = kid.title || '';
          tx.appendChild(t1);
          if (kid.desc) {
            var t2 = document.createElement('span');
            t2.className = 'nav-dropdown-desc';
            t2.textContent = kid.desc;
            tx.appendChild(t2);
          }
          a.appendChild(tx);
          menu.appendChild(a);
        });
        dd.appendChild(menu);
        container.appendChild(dd);
        return;
      }

      var a = document.createElement('a');
      a.href = it.url || '#';
      a.textContent = it.title || '';
      var cls = linkClass || '';
      if (cls && path === it.url) cls += ' active'; // 현재 페이지 하이라이트
      if (cls) a.className = cls;
      container.appendChild(a);
    });

    // 드롭다운 토글 동작 (위임 — body에 1회만 바인딩)
    if (!window.__navDropdownBound) {
      window.__navDropdownBound = true;
      function closeAll(except) {
        var all = document.querySelectorAll('.nav-dropdown.open');
        for (var i = 0; i < all.length; i++) {
          if (all[i] !== except) {
            all[i].classList.remove('open');
            var tgEl = all[i].querySelector('.nav-dropdown-toggle');
            if (tgEl) tgEl.setAttribute('aria-expanded', 'false');
          }
        }
      }
      document.addEventListener('click', function (e) {
        var tgEl = e.target.closest ? e.target.closest('.nav-dropdown-toggle') : null;
        if (tgEl) {
          e.preventDefault();
          e.stopPropagation();
          var host = tgEl.parentNode;
          var willOpen = !host.classList.contains('open');
          closeAll(host);
          host.classList.toggle('open', willOpen);
          tgEl.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
          return;
        }
        var inMenu = e.target.closest ? e.target.closest('.nav-dropdown-menu') : null;
        if (!inMenu) closeAll(null);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeAll(null);
      });
    }
  }

  function fillText(sel, val) {
    if (val == null || val === '') return;
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.textContent = val;
      if (el.tagName === 'A') {
        if (el.getAttribute('data-c-phone') !== null) el.setAttribute('href', 'tel:' + val);
        if (el.getAttribute('data-c-email') !== null) el.setAttribute('href', 'mailto:' + val);
      }
    }
  }

  async function main() {
    var SITE = null;
    try {
      var res = await fetch('/api/v1/public/site-content', { cache: 'no-store' });
      var j = await res.json();
      if (res.ok && j && j.data) SITE = j.data;
    } catch (e) { SITE = null; }
    if (!SITE) return; // 정적 기본 유지

    // 1) 네비 / 푸터 링크
    fillLinks(document.getElementById('navCenter'), SITE.nav, 'nav-link');
    fillLinks(document.getElementById('footerLinks'), SITE.footer_links, '');

    // 2) 상담정보 (푸터 위젯/문의 모달 공용)
    var c = SITE.contact || {};
    fillText('[data-c-phone]', c.phone);
    fillText('[data-c-email]', c.email);
    fillText('[data-c-address]', c.address);
    fillText('[data-c-hours]', c.hours);
    fillText('[data-c-modal-title]', c.modal_title);
    fillText('[data-c-modal-sub]', c.modal_sub);
    fillText('[data-c-modal-note]', c.modal_note);

    // 3) 페이지 본문 (body[data-site-page])
    var pageKey = document.body.getAttribute('data-site-page');
    var pg = (pageKey && SITE.pages && SITE.pages[pageKey]) ? SITE.pages[pageKey] : null;
    if (!pg) return;
    fillText('[data-page-title]', pg.title);
    fillText('[data-page-eyebrow]', pg.eyebrow);

    // 3-1) 페이지 히어로 이미지 교체 (DB hero_image 우선)
    if (pg.hero_image) {
      var shots = document.querySelectorAll('.hero-shot');
      for (var hi = 0; hi < shots.length; hi++) {
        shots[hi].src = pg.hero_image;
        if (pg.hero_alt) shots[hi].alt = pg.hero_alt;
      }
    }

    // 3-2) 본문 블록 렌더 (위지윅 blocks — 공용 site-blocks.js)
    var box = document.getElementById('pageSections');
    if (box && Array.isArray(pg.blocks) && pg.blocks.length && window.SiteBlocks) {
      window.SiteBlocks.renderInto(box, pg.blocks);
    }
    // 3-3) 회사소개 페이지 전용 — 브랜드 로고 다운로드 섹션 (항상 마지막에 노출)
    if (pageKey === 'company' && box && window.SiteBlocks && window.SiteBlocks.buildNode) {
      if (!document.getElementById('brandAssets')) {
        var brandNode = window.SiteBlocks.buildNode({ id: 'brand', type: 'brand' });
        if (brandNode) box.appendChild(brandNode);
      }
    }
    // 페이지 고유 로직(policy 탭 등)이 렌더 후 다시 적용할 수 있도록 알림
    document.dispatchEvent(new CustomEvent('nubida-site-rendered'));
  }

  // ===== 모바일 네비 햄버거 토글 (공개 페이지 공통) =====
  function initMobileNav() {
    var burger = document.getElementById('navBurger');
    if (!burger) return;
    var nav = burger.closest('.nav');
    if (!nav) return;
    function setOpen(open) {
      nav.classList.toggle('menu-open', open);
      burger.classList.toggle('active', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    burger.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!nav.classList.contains('menu-open'));
    });
    // 링크 클릭/외부 클릭/Esc 시 닫기 (navCenter는 fillLinks로 교체되므로 위임)
    document.addEventListener('click', function (e) {
      if (nav.contains(e.target)) {
        if (e.target.closest && e.target.closest('.nav-center a, .nav-center .nav-btn')) setOpen(false);
        return;
      }
      setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setOpen(false);
    });
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  ready(main);
  ready(initMobileNav);
})();
