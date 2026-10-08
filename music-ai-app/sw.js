const CACHE_NAME = 'nubida-ai-v18'; // 260921: HTML 문서 캐시 제외(접속코드 잠금화면 누락 수정)

// ─────────────────────────────────────────────────────────────
// [설계 260914] 대용량 음성모델(약 240MB) 처리 방식
//   변경 전(v10): install 에서 240MB 를 전부 받아야 설치 완료
//                 -> 첫 방문이 수십초~수분 걸리고, 실패하면 캐시도 안 됨
//   변경 후(v12): install 은 가벼운 파일만 (즉시 완료)
//                 대용량은 "처음 요청될 때" 받아서 캐시에 저장 (런타임 캐싱)
//                 -> 첫 방문은 그대로 1회 다운로드, 두 번째 방문부터 0MB
// ─────────────────────────────────────────────────────────────

// install 단계에서 미리 받아둘 가벼운 파일들 (대용량 제외)
// ── [260921] '/' 와 '/index.html' 은 절대 사전캐시하지 않는다 ──
//    이유: 접속코드 잠금이 켜져 있으면 서버는 같은 URL 로 lock.html 을
//          돌려준다. 이 응답을 캐시해두면 "캐시 우선" 전략 때문에
//          잠금화면/스튜디오가 서로 뒤바뀌어 보인다.
//          (첫 방문=옛 화면, 새로고침=새 화면 증상의 원인)
const PRECACHE_ASSETS = [
  '/static/css/style.css',
  '/static/js/ui_controller.js',
  '/static/js/engine.js'
];

// 런타임에 캐시할 대용량 자원 판별 (음성 엔진 / 모델)
// 주의: 이들은 용량이 커서 install 이 아닌 fetch 시점에 캐시한다.
const HEAVY_PATTERN = /\/static\/(sherpa\/|models\/)/;

// ── install: 가벼운 파일만 캐싱하고 즉시 활성화 ──────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW v16] 기본 자원 캐시 구축 시작');
      return Promise.allSettled(
        PRECACHE_ASSETS.map(url =>
          cache.add(url).catch(err => console.log('[SW] 캐시 실패(무시):', url, err))
        )
      );
    })
  );
  self.skipWaiting(); // 새 SW 즉시 활성화
});

// ── activate: 옛 버전 캐시 정리 ──────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[SW v16] 옛 캐시 삭제:', key);
            return caches.delete(key);
          }
          return null;
        })
      )
    ).then(() => self.clients.claim()) // 열린 탭 즉시 제어
  );
});

// ── fetch: 요청별 전략 ───────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // GET 이 아니면 개입하지 않음 (POST 등)
  if (req.method !== 'GET') return;

  let url;
  try {
    url = new URL(req.url);
  } catch (e) {
    return;
  }

  // 같은 출처가 아니면 개입하지 않음
  if (url.origin !== self.location.origin) return;

  // API 는 항상 네트워크 (캐시 금지)
  if (url.pathname.startsWith('/api/')) return;

  // ── [수정 260914] Range 요청은 SW 가 개입하지 않는다 ──────────
  //   이유: 캐시에 저장된 200(전체) 응답을 그대로 돌려주면
  //         브라우저의 Range 요청이 무시되고 60MB 전체가 전송됨.
  //         -> ui_controller.js 의 4분할 병렬 다운로드가 무력화됨.
  //   Range 요청은 브라우저가 오리진/Cloudflare 와 직접 처리하도록 통과시킨다.
  if (req.headers.get('range')) return;

  // ── 전략 A: 대용량 음성모델 = 캐시 우선, 없으면 받아서 저장 ──
  // 한 번 받으면 이후 방문은 디스크 캐시에서 즉시 로드 (0MB)
  if (HEAVY_PATTERN.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((hit) => {
        if (hit) {
          console.log('[SW] 캐시 HIT:', url.pathname.split('/').pop());
          return hit;
        }
        return fetch(req).then((res) => {
          // 정상 응답만 캐시 (206 Partial / opaque 제외)
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE_NAME)
              .then(c => c.put(req, copy))
              .catch(e => console.log('[SW] 저장 실패(무시):', e.message));
          }
          return res;
        });
      })
    );
    return;
  }

  // ── [260921] 전략 0: HTML 문서(내비게이션) = 항상 네트워크 우선 ──
  //   이유: '/' 와 '/index.html' 의 응답은 잠금 상태에 따라 달라진다.
  //         (잠금 ON → lock.html, 잠금 OFF → 스튜디오 index.html)
  //         이걸 캐시하면 첫 방문에 옛 화면이 떠버린다.
  //   → 내비게이션 요청은 캐시를 쓰지 않고 네트워크로 받아온다.
  //     오프라인일 때만 캐시로 폴백한다.
  const isDocNav = req.mode === 'navigate'
    || (req.headers.get('accept') || '').includes('text/html');
  if (isDocNav) {
    event.respondWith(
      fetch(req)
        .then((res) => res) // 캐시에 저장하지 않음
        .catch(() => caches.match(req)) // 오프라인 폴백
    );
    return;
  }

  // ── 전략 B: 그 외 정적자원 = 캐시 우선 + 백그라운드 갱신 ──────
  event.respondWith(
    caches.match(req).then((hit) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE_NAME)
              .then(c => c.put(req, copy))
              .catch(() => {});
          }
          return res;
        })
        .catch(() => hit); // 네트워크 실패 시 캐시라도 반환
      return hit || network; // 캐시 있으면 즉시 반환(성능), 없으면 네트워크
    })
  );
});
