(function () {
  'use strict';
  // 누비다 AI STUDIO 로딩 진단 도구
  // 사용법: 개발자도구 Console 에 붙여넣고 Enter

  const log = [];
  const t0 = performance.now();
  const mark = (name, extra) => {
    const t = Math.round(performance.now() - t0);
    log.push({ t, name, extra: extra || '' });
    console.log(`[진단 ${t}ms] ${name}`, extra || '');
  };

  // ── 1. 환경 정보 ──────────────────────────────
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  const env = {
    userAgent: navigator.userAgent,
    downlinkMbps: conn ? conn.downlink : 'unknown',
    effectiveType: conn ? conn.effectiveType : 'unknown',
    rtt: conn ? conn.rtt : 'unknown',
    saveData: conn ? conn.saveData : 'unknown',
    deviceMemory: navigator.deviceMemory || 'unknown',
    hardwareConcurrency: navigator.hardwareConcurrency,
    swControlled: !!navigator.serviceWorker.controller
  };
  console.log('=== 환경 정보 ===');
  console.table(env);

  // ── 2. 핵심 파일별 다운로드 측정 ──────────────
  const files = [
    '/static/sherpa/sherpa-onnx-wasm-main-tts.wasm',
    '/static/models/ko-kss/model.onnx',
    '/static/models/ko-kss/tokens.txt',
    '/static/models/ko-kss/espeak-ng-data/phontab',
    '/static/models/ko-kss/espeak-ng-data/phondata',
    '/static/models/ko-kss/espeak-ng-data/en_dict'
  ];

  const measure = (url) => new Promise((resolve) => {
    const t = performance.now();
    fetch(url + '?probe=' + Date.now(), { cache: 'no-store' })
      .then(async (res) => {
        const ttfb = Math.round(performance.now() - t);
        const buf = await res.arrayBuffer();
        const total = Math.round(performance.now() - t);
        resolve({
          file: url.split('/').pop(),
          kb: Math.round(buf.byteLength / 1024),
          ttfbMs: ttfb,
          totalMs: total,
          mbps: total > ttfb ? Math.round((buf.byteLength * 8 / 1e6) / ((total - ttfb) / 1000)) : 'cached',
          cf: res.headers.get('cf-cache-status'),
          enc: res.headers.get('content-encoding') || 'none',
          status: res.status
        });
      })
      .catch(e => resolve({ file: url.split('/').pop(), error: e.message }));
  });

  // 직렬 측정 (실제 로딩과 동일 조건)
  (async () => {
    console.log('=== 파일별 다운로드 측정 시작 (캐시 우회) ===');
    const results = [];
    for (const f of files) {
      const r = await measure(f);
      results.push(r);
      console.log(`${r.file}: ${r.totalMs}ms (TTFB ${r.ttfbMs}ms, ${r.mbps}Mbps, cf=${r.cf}, ${r.enc})`);
    }
    console.table(results);

    const heavy = results.filter(r => r.totalMs > 1000);
    console.log('=== 병목 파일 (>1초) ===');
    console.table(heavy);

    // ── 3. 현재 로딩 진행률 ────────────────────
    const statusEl = document.getElementById('load-status');
    const progressEl = document.getElementById('load-progress');
    const loadingEl = document.getElementById('loading');
    console.log('=== 현재 로딩 상태 ===');
    console.log('상태:', statusEl ? statusEl.innerText : '없음');
    console.log('진행바:', progressEl ? progressEl.style.width : '없음');
    console.log('로딩창 표시:', loadingEl ? loadingEl.style.display : '없음');

    // ── 4. 서비스워커 캐시 현황 ────────────────
    try {
      const keys = await caches.keys();
      console.log('캐시 이름:', keys);
      for (const k of keys) {
        const c = await caches.open(k);
        const reqs = await c.keys();
        console.log(`  ${k}: ${reqs.length}개 항목`);
        const hasModel = reqs.some(r => r.url.includes('model.onnx'));
        console.log(`  → model.onnx 캐시됨: ${hasModel}`);
      }
    } catch (e) { console.log('캐시 조회 실패:', e.message); }

    // ── 5. 결론 요약 ────────────────────────────
    const totalMs = Math.round(performance.now() - t0);
    console.log('');
    console.log('════════════════════════════════');
    console.log('  진단 요약');
    console.log('════════════════════════════════');
    console.log('회선 다운링크:', env.downlinkMbps, 'Mbps / 타입:', env.effectiveType, '/ RTT:', env.rtt, 'ms');
    console.log('가장 느린 파일:', heavy.length ? heavy.map(h => `${h.file} ${h.totalMs}ms`).join(', ') : '없음');
    console.log('전체 진단 소요:', totalMs, 'ms');
    console.log('════════════════════════════════');
    console.log('이 결과를 복사해서 윤비스님께 보내주세요.');
    window.__진단결과 = { env, results, heavy, totalMs };
    return window.__진단결과;
  })();
})();
