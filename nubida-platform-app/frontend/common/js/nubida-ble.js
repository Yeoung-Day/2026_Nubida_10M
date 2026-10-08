/**
 * 누비다머신 BLE 연결 모듈 (NubidaBLE v2)
 * ========================================
 * 기존 Web Serial(USB 케이블) 연결 방식을 BLE(무선)로 대체한다.
 * 아두이노 + BLE 모듈(HM-10/HM-11/AT-09 계열 또는 Nordic UART 펌웨어)과
 * UART 브리지 통신한다. 난독화(NubidaBT) 프레임은 문자열 그대로 writeLine().
 *
 * ▸ v2 (2026-09-08) — 모바일 앱(Capacitor) 네이티브 BLE 지원
 *   - iOS는 Web Bluetooth를 지원하지 않으므로, 누비다 하이브리드 앱에서는
 *     @capacitor-community/bluetooth-le 네이티브 플러그인으로 연결한다.
 *   - 실행 환경을 자동 감지(window.Capacitor.isNativePlatform)하여 분기:
 *       · 네이티브 앱  → Capacitor BLE 플러그인 (시스템 장치 선택 다이얼로그)
 *       · 웹 브라우저  → 기존 Web Bluetooth (Chrome/Edge 데스크톱·Android)
 *   - ml-arduino.js 등 상위 모듈은 v1과 동일한 인터페이스
 *     (supported / connect → { name, isConnected, writeLine, write, disconnect })
 *     를 그대로 사용하므로 수정이 필요 없다.
 *
 * ▸ 지원 BLE 서비스 (자동 감지)
 *   1. HM-10 계열  : Service 0xFFE0 / Characteristic 0xFFE1 (write+notify 겸용)
 *   2. Nordic UART : Service 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
 *                    TX(쓰기) 6E400002 / RX(알림) 6E400003
 *
 * ▸ 특성
 *   - write 특성은 속성(writeWithoutResponse 우선)에 맞춰 청크(20B) 단위 전송
 *   - 수신은 notify 구독 → 줄바꿈('\n') 단위로 onLine 콜백
 *   - 장치 연결이 끊기면 자동 정리 후 onDisconnect
 */
window.NubidaBLE = (function () {
    'use strict';

    /* HM-10 (0xFFE0/0xFFE1 — 16비트 UUID) */
    var HM10_SVC = 0xFFE0;
    var HM10_CHAR = 0xFFE1;
    /* Nordic UART */
    var NRF_SVC = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
    var NRF_TX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
    var NRF_RX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
    /* 네이티브(Capacitor) 필터용 128비트 전체 UUID */
    var HM10_SVC_128 = '0000ffe0-0000-1000-8000-00805f9b34fb';
    var HM10_CHAR_128 = '0000ffe1-0000-1000-8000-00805f9b34fb';
    var NRF_SVC_128 = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
    var NRF_TX_128 = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
    var NRF_RX_128 = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
    /* BLE 기본 MTU(23) 기준 페이로드 20바이트 — 플랫폼에 따라 확장 MTU 협상 전 최소 보장치 */
    var CHUNK = 20;
    /* ★ [2026-09-14] 청크 사이 전송 갭(ms).
     *   난독화 프레임('x'+20hex+'\n' = 22B)은 20B 청크 2개로 나뉘어 전송되는데,
     *   AT-09/HM-10 클론은 갭 없이 붙여 보내면 두 번째 조각(2B)을 흘려
     *   프레임이 홀수 길이가 되고 복호화에 실패한다([무시] 알 수 없는 명령).
     *   클래식 모듈과 BLE 양쪽 모두에서 안정성이 확인된 30ms 를 준다. */
    var CHUNK_GAP_MS = 30;
    function sleepMs(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    /**
     * Capacitor 네이티브 셸 여부 감지
     * (mobile-config.js의 IS_NATIVE와 동일 로직 — 단독 로드 페이지도 대비)
     */
    function isNative() {
        try {
            if (window.Capacitor && window.Capacitor.isNativePlatform) {
                return window.Capacitor.isNativePlatform();
            }
            var o = window.location.origin || '';
            return o.indexOf('capacitor://') === 0 || o === 'https://localhost' || o === 'http://localhost';
        } catch (e) { return false; }
    }

    /* 네이티브 BLE 플러그인 참조 (vendor/bluetooth-le-plugin.js 전역 번들) */
    function getBleClient() {
        try {
            if (window.CapacitorBLE && window.CapacitorBLE.BleClient) return window.CapacitorBLE.BleClient;
            if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.BluetoothLe) {
                return window.Capacitor.Plugins.BluetoothLe;
            }
        } catch (e) {}
        return null;
    }

    /* UUID 소문자 정규화 + 16비트 꼬리 매칭 */
    function uuidTail(u, tail) {
        var s = String(u || '').toLowerCase();
        return s === tail ||
            s === ('0000' + tail + '-0000-1000-8000-00805f9b34fb') ||
            s.indexOf('0000' + tail) === 0;
    }

    /* ─────────────────────────────────────────────
     * 네이티브 경로 — Capacitor BLE 플러그인
     * ───────────────────────────────────────────── */
    async function nativeConnect(opts) {
        opts = opts || {};
        var client = getBleClient();
        if (!client) {
            throw new Error('BLE 플러그인을 불러오지 못했어요.\n앱을 최신 버전으로 업데이트해 주세요.');
        }

        // Android 12+ 블루투스 권한 / iOS Bluetooth 권한 요청
        await client.initialize();

        // iOS 장치 선택 다이얼로그 문구 한국어화 (Android는 시스템 다이얼로그)
        try {
            await client.setDisplayStrings({
                scanning: '주변 누비다머신을 찾는 중...',
                cancel: '취소',
                availableDevices: '연결할 누비다머신을 선택하세요',
                noDeviceFound: '주변에 누비다머신이 없어요.\n보드 전원과 BLE 모듈을 확인해 주세요.'
            });
        } catch (e) { /* 구버전 플러그인 — 무시 */ }

        // 시스템 장치 선택 다이얼로그 (웹 Web Bluetooth의 requestDevice와 동일 UX)
        var device = await client.requestDevice({
            services: [HM10_SVC_128, NRF_SVC_128]
        });
        var deviceId = device.deviceId;
        var cleaned = false, notifyStarted = false;

        // 연결 (해제 시 자동 콜백)
        await client.connect(deviceId, function () {
            cleanup();
            if (opts.onDisconnect && !cleaned) opts.onDisconnect();
        });

        // 서비스·특성 자동 감지 (HM-10 FFE0/FFE1 우선 → Nordic UART)
        var svcUuid = null, writeUuid = null, notifyUuid = null, writeWoResp = false;
        var services = null;
        try { services = await client.getServices(deviceId); } catch (e) { services = null; }
        if (!services || !services.length) {
            try { await client.discoverServices(deviceId); } catch (e) {}
            try { services = await client.getServices(deviceId); } catch (e) { services = null; }
        }
        if (services) {
            for (var i = 0; i < services.length && !writeUuid; i++) {
                var s = services[i];
                var chars = (s && s.characteristics) || [];
                for (var j = 0; j < chars.length; j++) {
                    var c = chars[j];
                    if (uuidTail(s.uuid, 'ffe0')) {           // HM-10 서비스
                        if (uuidTail(c.uuid, 'ffe1')) {
                            svcUuid = s.uuid;
                            writeUuid = c.uuid;
                            notifyUuid = c.uuid;              // FFE1 하나가 write+notify 겸용
                            writeWoResp = !!(c.properties && c.properties.writeWithoutResponse);
                            break;
                        }
                    } else if (uuidTail(s.uuid, '6e400001')) { // Nordic UART 서비스
                        if (uuidTail(c.uuid, '6e400002')) {
                            writeUuid = c.uuid;
                            writeWoResp = !!(c.properties && c.properties.writeWithoutResponse);
                            svcUuid = s.uuid;
                        } else if (uuidTail(c.uuid, '6e400003')) {
                            notifyUuid = c.uuid;
                            if (!svcUuid) svcUuid = s.uuid;
                        }
                    }
                }
            }
        }
        if (!writeUuid) {
            try { await client.disconnect(deviceId); } catch (e) {}
            throw new Error('BLE UART 서비스(FFE0/Nordic)를 찾지 못했어요.\n누비다머신 BLE 모듈인지 확인해 주세요.');
        }

        // ★ [2026-09-21] 앱(네이티브) 진단 로그 — 웹 경로에는 onDiag 가 있었으나
        //   네이티브 경로에는 없어서, 앱에서는 "연결은 되는데 값을 못 받는다"의
        //   원인(어느 특성을 잡았는지 / notify 구독이 됐는지)을 전혀 볼 수 없었다.
        //   사용자 요청 "앱에서 블루투스 연결하고 값을 받으려 하면 통신이 안 되는 것 같아"
        //   → 앱에서도 동일한 진단을 화면에 노출한다.
        if (opts.onDiag) {
            try {
                var _svcList = [];
                if (services) {
                    for (var _i = 0; _i < services.length; _i++) {
                        var _s = services[_i];
                        var _cs = (_s && _s.characteristics) || [];
                        var _parts = [];
                        for (var _j = 0; _j < _cs.length; _j++) {
                            var _c = _cs[_j];
                            var _p = _c.properties || {};
                            _parts.push(uuidTail(_c.uuid, _c.uuid) + '[w:' + (_p.write ? 'Y' : 'n')
                                + ' wnr:' + (_p.writeWithoutResponse ? 'Y' : 'n')
                                + ' n:' + (_p.notify ? 'Y' : 'n') + ']');
                        }
                        _svcList.push(uuidTail(_s.uuid, _s.uuid) + ' → ' + _parts.join(' '));
                    }
                }
                opts.onDiag('앱(네이티브) 서비스 ' + (services ? services.length : 0) + '개: '
                    + _svcList.join(' | '));
                opts.onDiag('앱(네이티브) 선택된 특성 — write:' + writeUuid
                    + ' / notify:' + notifyUuid + ' / writeWithoutResponse:' + (writeWoResp ? 'Y' : 'n'));
            } catch (_e) { /* 진단 실패는 무시 */ }
        }

        function cleanup() {
            if (cleaned) return;
            cleaned = true;
            buf = '';
        }
        var buf = '';

        // ── 수신 (notify → 줄 단위) ──
        try {
            await client.startNotifications(deviceId, svcUuid, notifyUuid, function (value) {
                try {
                    var dv = value;
                    if (dv && dv.byteLength === undefined && value && value.value) dv = value.value; // {value: DataView} 폴백
                    if (!dv) return;
                    var bytes = new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
                    buf += new TextDecoder().decode(bytes);
                    var idx;
                    while ((idx = buf.indexOf('\n')) !== -1) {
                        var line = buf.slice(0, idx).trim();
                        buf = buf.slice(idx + 1);
                        if (line && opts.onLine) opts.onLine(line);
                    }
                } catch (e) { /* 수신 파싱 오류 무시 */ }
            });
            notifyStarted = true;
            if (opts.onDiag) { try { opts.onDiag('앱(네이티브) notify 구독 성공 — 아두이노 수신 준비 완료'); } catch (_e3) {} }
        } catch (e) {
            // notify 미지원 모듈 — 송신만 가능(무시)
            // ★ [2026-09-21] 앱에서 "값을 못 받는다"의 가장 흔한 원인이므로 조용히 삼키지 않는다.
            if (opts.onDiag) {
                try {
                    opts.onDiag('⚠️ 앱(네이티브) notify 구독 실패 — 아두이노에서 값을 받을 수 없어요: '
                        + ((e && e.message) || e));
                } catch (_e4) {}
            }
        }

        /** 청크(Uint8Array) → DataView */
        function toDataView(bytes) {
            return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        }

        /** 문자열을 줄바꿈과 함께 전송 (라인 단위 프로토콜, 20B 청크) */
        async function writeLine(str) {
            if (cleaned) throw new Error('BLE 연결이 끊어졌어요.');
            var data = new TextEncoder().encode(String(str) + '\n');
            for (var k = 0; k < data.length; k += CHUNK) {
                var chunk = data.subarray(k, Math.min(k + CHUNK, data.length));
                if (writeWoResp) {
                    await client.writeWithoutResponse(deviceId, svcUuid, writeUuid, toDataView(chunk));
                } else {
                    await client.write(deviceId, svcUuid, writeUuid, toDataView(chunk));
                }
                if (k + CHUNK < data.length) await sleepMs(CHUNK_GAP_MS);   // ★ 청크 갭
            }
        }

        /** 개행 없는 원시 전송 (특수 프로토콜용) */
        async function write(str) {
            if (cleaned) throw new Error('BLE 연결이 끊어졌어요.');
            var data = new TextEncoder().encode(String(str));
            for (var k = 0; k < data.length; k += CHUNK) {
                var chunk = data.subarray(k, Math.min(k + CHUNK, data.length));
                if (writeWoResp) {
                    await client.writeWithoutResponse(deviceId, svcUuid, writeUuid, toDataView(chunk));
                } else {
                    await client.write(deviceId, svcUuid, writeUuid, toDataView(chunk));
                }
                if (k + CHUNK < data.length) await sleepMs(CHUNK_GAP_MS);   // ★ 청크 갭
            }
        }

        async function disconnect() {
            cleanup();
            try { if (notifyStarted) await client.stopNotifications(deviceId, svcUuid, notifyUuid); } catch (e) {}
            try { await client.disconnect(deviceId); } catch (e) {}
        }

        return {
            name: device.name || '누비다머신',
            isConnected: function () { return !cleaned; },
            writeLine: writeLine,
            write: write,
            disconnect: disconnect
        };
    }

    /**
     * 장치 이름 정규화 — 사용자가 모듈 이름을 "1번","2번" 등으로 바꿔 쓰는 경우 대응
     * (본사 지침: 여러 모듈을 번호로 구분. HM-10/HC-06 등 기본 이름도 유지)
     */
    function nameMatches(str) {
        var s = String(str || '').toUpperCase();
        if (!s) return false;
        // 기본 모듈명
        if (/^(HM|AT|JDY|NUBIDA|HC)/.test(s)) return true;
        // 숫자 + 번/호  (예: "1번", "2호", "3")
        if (/^\d+\s*(번|호)?$/.test(s)) return true;
        return false;
    }

    /**
     * 안드로이드(갤럭시) 대응 장치 검색 — filters 실패 시 acceptAllDevices 로 자동 재시도
     *
     * 🔴 안드로이드는 filters(services) 를 엄격 적용한다.
     *    HM-10 클론/AT-09 등은 광고 패킷에 서비스 UUID(FFE0)를 싣지 않아
     *    filters 만 쓰면 "장치 목록이 비어" 스캔이 안 되는 것처럼 보인다.
     *    → 필터 실패(NotFoundError) 시 acceptAllDevices:true 로 전체 검색한다.
     *    (사용자 취소는 폴백하지 않고 그대로 전달)
     */
    async function requestDeviceWithFallback() {
        var base = {
            optionalServices: [HM10_SVC, HM10_CHAR, NRF_SVC, NRF_TX, NRF_RX]
        };
        try {
            return await navigator.bluetooth.requestDevice(Object.assign({}, base, {
                filters: [
                    { services: [HM10_SVC] },           // HM-10 / AT-09 / JDY-08
                    { services: [NRF_SVC] },            // Nordic UART
                    { namePrefix: 'HM' },
                    { namePrefix: 'AT' },
                    { namePrefix: 'JDY' },
                    { namePrefix: 'Nubida' },
                    { namePrefix: 'NUBIDA' },
                    { namePrefix: 'HC' },
                    // 번호로 이름을 바꾼 경우(1번/2번/3호 …) — 숫자로 시작하는 접두어
                    { namePrefix: '1' }, { namePrefix: '2' }, { namePrefix: '3' },
                    { namePrefix: '4' }, { namePrefix: '5' }, { namePrefix: '6' },
                    { namePrefix: '7' }, { namePrefix: '8' }, { namePrefix: '9' }
                ]
            }));
        } catch (e) {
            var nm = (e && e.name) || '';
            var ms = (e && e.message) || '';
            // 사용자가 직접 취소한 경우 → 폴백하지 않음
            if (nm === 'NotFoundError' && /cancel|취소|user/i.test(ms)) throw e;
            if (/cancel|취소/i.test(ms)) throw e;
            // 필터로 못 찾은 경우 → 전체 장치 검색으로 재시도
            return await navigator.bluetooth.requestDevice(Object.assign({}, base, {
                acceptAllDevices: true
            }));
        }
    }

    /* ─────────────────────────────────────────────
     * 웹 경로 — Web Bluetooth (기존 v1 로직 유지)
     * ───────────────────────────────────────────── */
    async function webConnect(opts) {
        opts = opts || {};
        if (!('bluetooth' in navigator)) {
            throw new Error('이 브라우저는 Web Bluetooth를 지원하지 않아요.\nChrome 또는 Edge 브라우저(데스크톱/Android)를 사용해 주세요.');
        }
        var device = await requestDeviceWithFallback();

        var server = await device.gatt.connect();
        var svc = null, writeChar = null, notifyChar = null, isNrf = false;
        var extraWrites = [];   // 폴백 스캔에서 찾은 추가 write 후보 특성

        // HM-10 서비스 우선 탐색 → 없으면 Nordic UART
        try { svc = await server.getPrimaryService(HM10_SVC); } catch (e) { svc = null; }
        if (!svc) {
            try { svc = await server.getPrimaryService(NRF_SVC); isNrf = true; } catch (e) { svc = null; }
        }
        if (!svc) {
            // ── 최후 폴백: 전체 서비스 스캔 ────────────────────────────
            //  클론 모듈은 FFE0 대신 다른 서비스 UUID 를 쓸 수 있다.
            //  write 가능 + notify 가능한 특성을 자동 채택한다.
            try {
                var all = await server.getPrimaryServices();
                for (var si = 0; si < all.length; si++) {
                    var s2 = all[si];
                    var cs = await s2.getCharacteristics();
                    var wc = null, nc = null;
                    for (var ci2 = 0; ci2 < cs.length; ci2++) {
                        var p = cs[ci2].properties || {};
                        if (!wc && (p.write || p.writeWithoutResponse)) wc = cs[ci2];
                        if (!nc && p.notify) nc = cs[ci2];
                        // write 가능성이 있는 특성은 모두 후보로 수집
                        if (p.write || p.writeWithoutResponse) extraWrites.push(cs[ci2]);
                    }
                    if (wc) { svc = s2; writeChar = wc; notifyChar = nc || wc; break; }
                }
            } catch (e2) {}
        } else if (!isNrf) {
            // ★ FFE0 서비스 발견 시: FFE1 외에 다른 write 특성이 있을 수 있다.
            //   (properties 광고가 거짓인 클론 대응 — 후보를 모두 수집)
            try {
                var svcChars = await svc.getCharacteristics();
                for (var k = 0; k < svcChars.length; k++) {
                    var pk = svcChars[k].properties || {};
                    if (pk.write || pk.writeWithoutResponse) extraWrites.push(svcChars[k]);
                }
            } catch (e3) {}
        }
        if (!svc) {
            try { if (device.gatt.connected) device.gatt.disconnect(); } catch (e) {}
            throw new Error('BLE UART 서비스(FFE0/Nordic)를 찾지 못했어요.\n' +
                '· 누비다머신 BLE 모듈(HM-10/AT-09/JDY-08)인지 확인해 주세요.\n' +
                '· HC-05/HC-06(클래식)은 BLE 가 아니므로 🔌 USB 시리얼 버튼을 사용하세요.');
        }

        if (isNrf) {
            writeChar = await svc.getCharacteristic(NRF_TX);
            notifyChar = await svc.getCharacteristic(NRF_RX);
        } else if (!writeChar) {
            writeChar = await svc.getCharacteristic(HM10_CHAR);
            notifyChar = writeChar; // HM-10: FFE1 하나가 write+notify 겸용
        }

        var buf = '', cleaned = false;

        // ────────────────────────────────────────────────────────────
        //  write 특성 "후보 배열" + 실전 검증 (AT-09 클론 대응)
        // ────────────────────────────────────────────────────────────
        //  🔴 문제: 클론 모듈은 properties.write = true 로 "광고"만 하고
        //          실제 write 는 NotSupportedError 로 실패한다.
        //  ✅ 해결: 광고를 믿지 않고, 후보 특성 × write방식 조합을
        //          실제로 시도해서 "성공한 조합"을 확정(캐시)한다.
        var writeCandidates = [];   // write 가능성이 있는 특성 목록
        var confirmed = null;       // { ch, mode } — 실제 성공이 확인된 조합
        var lastTxError = null;     // 마지막 송신 실패 원인

        // ★ [2026-09-13 교착 방지] 조합 탐색이 한 번 실패하면 다시 시도하지 않는다.
        //   AT-09 클론은 write 실패 시 GATT 타임아웃(수 초)까지 매달리는데,
        //   음성 분류 루프 안에서 이게 반복되면 분류 자체가 멈춘다.
        var probeFailed = false;
        var WRITE_TIMEOUT_MS = 1500;   // 개별 write 시도 상한(ms)

        // Promise 에 타임아웃을 씌운다 — GATT 가 영구 대기하는 것을 막는다.
        function withTimeout(promise, ms, msg) {
            return new Promise(function (resolve, reject) {
                var done = false;
                var t = setTimeout(function () {
                    if (done) return;
                    done = true;
                    reject(new Error(msg || 'timeout'));
                }, ms);
                Promise.resolve(promise).then(function (v) {
                    if (done) return;
                    done = true; clearTimeout(t); resolve(v);
                }, function (e) {
                    if (done) return;
                    done = true; clearTimeout(t); reject(e);
                });
            });
        }

        function addCandidate(ch) {
            if (!ch) return;
            for (var i = 0; i < writeCandidates.length; i++) {
                if (writeCandidates[i] === ch) return;    // 중복 방지
            }
            writeCandidates.push(ch);
        }

        // 확정된 특성부터, 없으면 후보 전체를 등록
        if (writeChar) addCandidate(writeChar);
        // 폴백 스캔에서 수집한 추가 후보들도 등록 (광고가 거짓인 클론 대응)
        for (var ei = 0; ei < extraWrites.length; ei++) addCandidate(extraWrites[ei]);

        // ── 진단: 발견된 서비스/특성 정보를 화면 로그로 전달 ──
        //    "왜 전송이 안 되는가"를 사용자가 직접 볼 수 있게 한다.
        if (opts.onDiag) {
            var chInfo = [];
            for (var di = 0; di < writeCandidates.length; di++) {
                var dp = writeCandidates[di].properties || {};
                // 특성 UUID 축약 표기 (마지막 4자리)
                var uu = (writeCandidates[di].uuid || '').replace(/-/g, '');
                var short = uu.length > 8 ? ('…' + uu.slice(-4)) : uu;
                chInfo.push(short +
                    '[w:' + (dp.write ? 'Y' : 'n') +
                    ' wnr:' + (dp.writeWithoutResponse ? 'Y' : 'n') +
                    ' n:' + (dp.notify ? 'Y' : 'n') + ']');
            }
            opts.onDiag(
                '서비스: ' + ((svc && svc.uuid) || '-').replace(/-/g, '').slice(0, 8) +
                (isNrf ? ' (Nordic)' : ' (FFE0계열)') +
                ' / 쓰기후보 ' + writeCandidates.length + '개: ' + (chInfo.join(' ') || '없음')
            );
        }

        /**
         * 후보 특성 × write방식(response/noResponse) 조합을 실제로 시도한다.
         * 성공한 조합을 confirmed 에 캐시하고, 이후에는 그것만 사용한다.
         */
        async function writeChunk(chunk) {
            // 1) 이미 성공 조합이 확정됐으면 그대로 사용
            if (confirmed) {
                if (confirmed.mode === 'response') {
                    await confirmed.ch.writeValueWithResponse(chunk);
                } else {
                    await confirmed.ch.writeValueWithoutResponse(chunk);
                }
                return;
            }

            // 2) 후보가 없으면 (폴백 스캔 실패) writeChar 를 후보로
            if (!writeCandidates.length && writeChar) addCandidate(writeChar);
            if (!writeCandidates.length) {
                throw new Error('BLE 쓰기 특성을 찾지 못했어요. (모듈이 UART 서비스를 제공하지 않음)');
            }

            // 3) 후보 × 방식 전수 시도 — 실제로 되는 조합을 찾는다
            //  ★ [2026-09-13 교착 방지] 전수 시도는 "첫 전송(조합 탐색)" 때만 하고,
            //    한 번 실패하면 그 뒤로는 재탐색하지 않는다. AT-09 클론은 실패 시
            //    GATT 타임아웃(수 초)까지 매달리는데, 이걸 매 전송마다 반복하면
            //    음성 분류 루프가 통째로 멈춘다.
            if (probeFailed) throw new Error('BLE 쓰기 조합 탐색 실패 — 재탐색 생략(교착 방지)');
            var errs = [];
            for (var i = 0; i < writeCandidates.length; i++) {
                var ch = writeCandidates[i];
                var modes = ['response', 'noResponse'];
                for (var m = 0; m < modes.length; m++) {
                    var mode = modes[m];
                    // properties 광고가 명백히 불가한 조합은 건너뛴다
                    var p = ch.properties || {};
                    if (mode === 'response' && p.write === false) continue;
                    if (mode === 'noResponse' && p.writeWithoutResponse === false) continue;
                    try {
                        await withTimeout(
                            (mode === 'response')
                                ? ch.writeValueWithResponse(chunk)
                                : ch.writeValueWithoutResponse(chunk),
                            WRITE_TIMEOUT_MS,
                            'BLE 쓰기 타임아웃(' + mode + ')'
                        );
                        // ★ 성공! 이 조합을 확정하고 캐시
                        confirmed = { ch: ch, mode: mode };
                        return;
                    } catch (e) {
                        errs.push((e && e.name ? e.name : 'Error') + '(' + mode + ')');
                        lastTxError = e;
                    }
                }
            }

            // 4) 모든 조합 실패 → 마지막 에러를 구체적으로 던진다
            //  ★ 재탐색 금지 플래그를 세운다 — 다음 전송부터는 즉시 실패(교착 방지).
            probeFailed = true;
            var msg = (lastTxError && lastTxError.message) || '알 수 없는 오류';
            var nm = (lastTxError && lastTxError.name) || '';
            throw new Error(
                nm + ': ' + msg + '\n' +
                '· 시도한 특성 ' + writeCandidates.length + '개 / 조합: ' + errs.join(', ')
            );
        }
        try {
            await notifyChar.startNotifications();
            notifyChar.addEventListener('characteristicvaluechanged', function (ev) {
                try {
                    var v = ev.target.value; // DataView
                    var bytes = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
                    buf += new TextDecoder().decode(bytes);
                    var idx;
                    while ((idx = buf.indexOf('\n')) !== -1) {
                        var line = buf.slice(0, idx).trim();
                        buf = buf.slice(idx + 1);
                        if (line && opts.onLine) opts.onLine(line);
                    }
                } catch (e) { /* 수신 파싱 오류 무시 */ }
            });
        } catch (e) { /* notify 미지원 모듈 — 송신만 가능(무시) */ }

        function cleanup() {
            if (cleaned) return;
            cleaned = true;
            try { if (notifyChar) notifyChar.removeEventListener('characteristicvaluechanged', null); } catch (e) {}
            buf = '';
        }

        device.addEventListener('gattserverdisconnected', function () {
            cleanup();
            if (opts.onDisconnect) opts.onDisconnect();
        });

        async function writeLine(str) {
            if (!device.gatt.connected) throw new Error('BLE 연결이 끊어졌어요.');
            var data = new TextEncoder().encode(String(str) + '\n');
            for (var i = 0; i < data.length; i += CHUNK) {
                var chunk = data.subarray(i, Math.min(i + CHUNK, data.length));
                await writeChunk(chunk);
                if (i + CHUNK < data.length) await sleepMs(CHUNK_GAP_MS);   // ★ 청크 갭
            }
        }

        /** 개행 없는 원시 전송 (특수 프로토콜용) */
        async function write(str) {
            if (!device.gatt.connected) throw new Error('BLE 연결이 끊어졌어요.');
            var data = new TextEncoder().encode(String(str));
            for (var i = 0; i < data.length; i += CHUNK) {
                var chunk = data.subarray(i, Math.min(i + CHUNK, data.length));
                await writeChunk(chunk);
                if (i + CHUNK < data.length) await sleepMs(CHUNK_GAP_MS);   // ★ 청크 갭
            }
        }

        async function disconnect() {
            cleanup();
            try { if (notifyChar) await notifyChar.stopNotifications(); } catch (e) {}
            try { if (device.gatt.connected) device.gatt.disconnect(); } catch (e) {}
        }

        return {
            name: device.name || 'BLE 장치',
            isConnected: function () { return !!(device.gatt && device.gatt.connected); },
            writeLine: writeLine,
            write: write,
            disconnect: disconnect
        };
    }

    // ── Web Serial (클래식 SPP: HC-05/HC-06) 폴백 ──────────────────
    //  Web Bluetooth 는 BLE 전용이라 HC-05/HC-06(블루투스 클래식)에는 연결할 수 없다.
    //  대신 PC에 페어링하면 COM 포트로 잡히므로 Web Serial(navigator.serial)로 연결한다.
    //  → BLE 모듈(HM-10/AT-09/JDY-08)과 클래식 모듈(HC-05/HC-06)을 모두 지원.
    function serialSupported() {
        return ('serial' in navigator) && window.isSecureContext;
    }

    async function serialConnect(handlers) {
        // ── 진단: 이미 승인된 포트 / Web Serial 가용성 ──────────────
        var diag = { granted: 0, hasApi: ('serial' in navigator), secure: !!window.isSecureContext };
        try {
            if (navigator.serial.getPorts) {
                var known = await navigator.serial.getPorts();
                diag.granted = known.length;
            }
        } catch (e) {}

        var port;
        try {
            // USB 직렬(CH340 등)만 표시된다. 블루투스 SPP 가상 COM 포트는 목록에 뜨지 않는다.
            port = await navigator.serial.requestPort();
        } catch (e) {
            var m = (e && e.message) || '';
            if (/cancel|취소|No port selected|not found/i.test(m)) throw e;   // 사용자 취소는 그대로 전달
            throw new Error(
                '시리얼 포트를 열 수 없어요.\n' +
                '· 아두이노를 USB 케이블로 PC에 연결했는지 확인해 주세요.\n' +
                '· HC-06/HC-05(블루투스)는 페어링해도 Web Serial 목록에 나오지 않습니다.\n' +
                '· (진단) Web Serial API: ' + (diag.hasApi ? '있음' : '없음') + ' / 보안컨텍스트: ' + (diag.secure ? '예' : '아니오')
            );
        }

        // baudRate — 사용자가 고른 값을 우선 사용(코드의 Serial.begin() 과 일치해야 함)
        var baud = 9600;
        try {
            var sel = document.getElementById('baudRateSelector') || document.getElementById('baudSelect');
            if (sel && sel.value) baud = parseInt(sel.value, 10) || 9600;
        } catch (e) {}
        if (handlers && handlers.baudRate) baud = parseInt(handlers.baudRate, 10) || baud;

        try {
            await port.open({ baudRate: baud, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none', bufferSize: 256 });
        } catch (e) {
            var em = (e && e.message) || '';
            throw new Error(
                '포트는 선택됐지만 열지 못했어요 (baud ' + baud + ').\n' +
                '· USB 직렬 드라이버(CH340 등)가 설치돼 있는지 확인\n' +
                '· 다른 프로그램(시리얼 모니터/IDE)이 포트를 점유 중이면 닫아 주세요.\n' +
                '· 원인: ' + em
            );
        }

        var writer = port.writable.getWriter();
        var reader = port.readable.getReader();
        var enc = new TextEncoder();
        var dec = new TextDecoder();
        var buf = '';
        var closed = false;
        var onLine = (handlers && handlers.onLine) || function () {};
        var onDisconnect = (handlers && handlers.onDisconnect) || function () {};

        (function readLoop() {
            reader.read().then(function (r) {
                if (r.done) { closed = true; if (onDisconnect) onDisconnect(); return; }
                buf += dec.decode(r.value, { stream: true });
                var idx;
                while ((idx = buf.indexOf('\n')) !== -1) {
                    var line = buf.slice(0, idx).replace(/\r$/, '');
                    buf = buf.slice(idx + 1);
                    if (line.length) { try { onLine(line); } catch (e) {} }
                }
                if (!closed) readLoop();
            }).catch(function () { closed = true; if (onDisconnect) onDisconnect(); });
        })();

        return {
            name: (port.getInfo && port.getInfo().usbVendorId ? 'USB 시리얼' : '시리얼 포트'),
            isConnected: function () { return !closed; },
            writeLine: async function (str) {
                if (closed) return false;
                await writer.write(enc.encode(String(str) + '\n'));
                return true;
            },
            write: async function (str) {
                if (closed) return false;
                await writer.write(enc.encode(String(str)));
                return true;
            },
            disconnect: async function () {
                closed = true;
                try { await reader.cancel(); } catch (e) {}
                try { writer.releaseLock(); } catch (e) {}
                try { await port.close(); } catch (e) {}
            }
        };
    }

    var IS_NATIVE = isNative();

    /* ─────────────────────────────────────────────
     * 네이티브 클래식 SPP 경로 (Android 앱 전용)
     *  HC-05 / HC-06 / AT-06 등 블루투스 클래식 모듈은
     *  Web Bluetooth(BLE) 로 연결할 수 없다.
     *  Android 앱(Capacitor)에 내장된 NubidaClassic 플러그인을 통해
     *  RFCOMM 소켓으로 연결한다. (플러그인 없으면 미지원)
     * ───────────────────────────────────────────── */
    function getClassicClient() {
        try {
            if (window.NubidaClassic && window.NubidaClassic.connect) return window.NubidaClassic;
            if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NubidaClassic) {
                return window.Capacitor.Plugins.NubidaClassic;
            }
        } catch (e) {}
        return null;
    }

    function classicSupported() {
        return !!getClassicClient();
    }

    async function nativeClassicConnect(handlers) {
        var client = getClassicClient();
        if (!client) {
            throw new Error('클래식 블루투스(HC-05/06/AT-06) 플러그인을 불러오지 못했어요.\n앱을 최신 버전으로 업데이트해 주세요.');
        }
        handlers = handlers || {};
        var onLine = handlers.onLine || function () {};
        var onDisconnect = handlers.onDisconnect || function () {};

        // 장치 목록 조회 → 사용자가 선택 (플러그인이 네이티브 다이얼로그 제공 시 생략 가능)
        var res = await client.connect({
            namePrefix: handlers.namePrefix || '',
            onData: function (d) {
                try { onLine((d && d.line) || String(d)); } catch (e) {}
            }
        });
        var closed = false;
        return {
            name: (res && res.name) || '클래식 블루투스',
            isConnected: function () { return !closed; },
            writeLine: async function (str) {
                if (closed) return false;
                await client.write({ data: String(str) + '\n' });
                return true;
            },
            write: async function (str) {
                if (closed) return false;
                await client.write({ data: String(str) });
                return true;
            },
            disconnect: async function () {
                closed = true;
                try { await client.disconnect(); } catch (e) {}
                if (onDisconnect) onDisconnect();
            }
        };
    }

    if (IS_NATIVE) {
        return {
            supported: !!getBleClient() || classicSupported(),
            bleSupported: !!getBleClient(),
            classicSupported: classicSupported(),
            // 안드로이드 앱에서도 시리얼/USB 경로를 쓰고 싶을 때 true (Chrome WebView 미지원이라 보통 false)
            serialSupported: false,
            connect: nativeConnect,
            classicConnect: nativeClassicConnect
        };
    }

    return {
        // BLE(HM-10 등) 또는 시리얼(HC-05/06) 중 하나라도 가능하면 true
        supported: ('bluetooth' in navigator) || serialSupported(),
        bleSupported: ('bluetooth' in navigator),
        serialSupported: serialSupported(),
        classicSupported: false,
        connect: webConnect,
        serialConnect: serialConnect
    };
})();
