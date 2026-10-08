/**
 * ============================================================================
 *  누비다 블루투스카 — 동작 전송 기본틀 (초간단 버전)
 * ============================================================================
 *
 *  ★ 이 파일은 "새로 짜는" 코드입니다. 기존 ml-studio.js 는 건드리지 않습니다.
 *
 *  ── 사용법 (딱 3단계) ──────────────────────────────────────────────────
 *   1. 아래 ACTIONS 표에서 숫자만 고친다
 *   2. HTML 에 이 파일을 넣는다:
 *        <script src="/common/js/btcar.js?v=1"></script>
 *   3. 화면에서 이렇게 호출한다:
 *        놀람(1)  → 누비다.보내기(1)
 *        놀람(1)  → 누비다.보내기('놀람')      ← 이름으로도 가능
 *
 *  ── 동작을 추가하고 싶으면? ────────────────────────────────────────────
 *   ACTIONS 표에 한 줄만 추가하면 끝. 다른 코드는 손 안 대도 됩니다.
 *      { no: 5, name: '놀람', cmd: '5NubidaAi', servo: 3, min: 60, max: 150 },
 *
 * ============================================================================
 */


/* ==========================================================================
   ① 표 — 여기만 고치면 됩니다
   ==========================================================================

   no    : AI 결과 번호 (카메라/음성 분류 결과가 이 번호로 나옵니다)
   name  : 사람이 읽는 이름 (로그·화면 표시용)
   cmd   : 아두이노에 보낼 명령 (아두이노 ACTIONS[] 의 문자열과 반드시 동일)
   servo : 서보 신호 핀 번호 (참고용 — 실제 동작은 아두이노가 결정)
   min/max : 각도 범위 (참고용)

   ⚠️ cmd 는 아두이노 펌웨어의 ACTIONS[] 에 있는 문자열과 **똑같아야** 합니다.
      틀리면 아두이노가 [무시] 로 버립니다.
   ========================================================================== */

var ACTIONS = [
    //  no   name        cmd            servo  min  max
    {   no: 1,  name: '삐졌어',   cmd: '1NubidaAi',  servo: 9,  min: 90, max: 160 },
    {   no: 2,  name: '도리도리', cmd: '2NubidaAi',  servo: 9,  min: 60, max: 120 },
    {   no: 3,  name: '안녕',     cmd: '3NubidaAi',  servo: 7,  min: 90, max: 160 },
    {   no: 4,  name: '박수',     cmd: '4NubidaAi',  servo: 5,  min: 90, max: 160 },
];


/* ==========================================================================
   ② 설정 — 잘 안 바꿔도 되는 값
   ========================================================================== */

var CONFIG = {
    apiBase: '/api/v1',          // 서버 주소
    cmdPath: '/ml/bt-command',   // 난독화 명령을 받아오는 API
    repeatBlockMs: 1000,         // 같은 동작 1초 내 재전송 금지
    txTimeoutMs: 3000,           // 전송 응답 없으면 강제 해제
};


/* ==========================================================================
   ③ 내부 상태 — 건드리지 마세요
   ========================================================================== */

var _ble = null;               // BLE 연결 객체
var _lastNo = -1;              // 마지막으로 보낸 번호
var _lastAt = 0;               // 마지막 전송 시각
var _sending = false;          // 전송 중 깃발
var _watchdog = null;          // 응답 없을 때 강제 해제용


/* ==========================================================================
   ④ 로그 — 화면에 상태를 보여줍니다
   ========================================================================== */

function _로그(msg, isError) {
    try { console.log('[btcar]', msg); } catch (e) {}
    var box = document.getElementById('btcarLog');
    if (!box) return;
    var line = document.createElement('div');
    line.textContent = msg;
    line.style.color = isError ? '#dc2626' : '#334155';
    box.appendChild(line);
    while (box.childElementCount > 100) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
}


/* ==========================================================================
   ⑤ 표에서 찾기 — 번호든 이름이든 받아줍니다
   ========================================================================== */

/* 번호로 찾기: 찾기(1) → { no:1, name:'삐졌어', ... } */
function 찾기(번호또는이름) {
    for (var i = 0; i < ACTIONS.length; i++) {
        if (ACTIONS[i].no === 번호또는이름) return ACTIONS[i];
        if (ACTIONS[i].name === 번호또는이름) return ACTIONS[i];
        if (ACTIONS[i].cmd === 번호또는이름) return ACTIONS[i];
    }
    return null;
}


/* ==========================================================================
   ⑥ 연결 / 해제 — 버튼에 그대로 연결하세요
   ========================================================================== */

/* 아두이노 연결:  <button onclick="누비다.연결()"> */
async function 연결() {
    if (_ble) { _로그('이미 연결되어 있어요: ' + _ble.name); return true; }

    if (!window.NubidaBLE || !window.NubidaBLE.supported) {
        _로그('이 브라우저는 블루투스를 지원하지 않아요 (Chrome/Edge 사용)', true);
        return false;
    }

    try {
        _ble = await window.NubidaBLE.connect({
            onLine: function (line) { _로그('📥 아두이노: ' + line); },
            onDisconnect: function () {
                _ble = null;
                _로그('📡 연결이 끊어졌어요. 다시 연결해 주세요.', true);
            },
            onDiag: function (msg) { _로그('🔎 ' + msg); }
        });
        _로그('✅ 연결 성공: ' + _ble.name);
        return true;
    } catch (e) {
        _ble = null;
        _로그('연결 실패/취소: ' + (e && e.message), true);
        return false;
    }
}

/* 연결 해제:  <button onclick="누비다.해제()"> */
async function 해제() {
    try { if (_ble) await _ble.disconnect(); } catch (e) {}
    _ble = null;
    _sending = false;
    if (_watchdog) { clearTimeout(_watchdog); _watchdog = null; }
    _로그('연결을 해제했어요.');
}

/* 연결됐나? */
function 연결됨() { return _ble !== null; }


/* ==========================================================================
   ⑦ ★★ 핵심 — 보내기 (카메라·음성·버튼 전부 이 함수 하나만 씁니다)
   ==========================================================================
       누비다.보내기(1)          ← 번호로
       누비다.보내기('삐졌어')    ← 이름으로
   ========================================================================== */

async function 보내기(번호또는이름) {

    // ── 1. 표에서 동작 찾기 ──
    var 동작 = 찾기(번호또는이름);
    if (!동작) {
        _로그('❌ 표에 없는 동작이에요: ' + 번호또는이름, true);
        return false;
    }

    // ── 2. 연결 확인 ──
    if (!_ble) {
        _로그('⏸ 전송 보류 — 아두이노가 연결되지 않았어요', true);
        return false;
    }

    // ── 3. 전송 중이면 건너뜀 ──
    if (_sending) {
        _로그('⏸ 전송 중이에요 — 잠시 후 다시', true);
        return false;
    }

    // ── 4. 같은 동작 반복 차단 (1초) ──
    var 지금 = Date.now();
    if (동작.no === _lastNo && (지금 - _lastAt) < CONFIG.repeatBlockMs) {
        return false;   // 조용히 생략 (정상 동작이므로 로그 안 남김)
    }
    _lastNo = 동작.no;
    _lastAt = 지금;
    _sending = true;

    // ── 5. 응답 없으면 강제 해제 (안전장치) ──
    if (_watchdog) clearTimeout(_watchdog);
    _watchdog = setTimeout(function () {
        if (_sending) {
            _sending = false;
            _로그('⚠️ 응답 없음 — 전송 잠금을 풀었어요', true);
        }
    }, CONFIG.txTimeoutMs);

    // ── 6. 서버에서 난독화된 명령 받아서 전송 ──
    try {
        var 응답 = await _api호출(동작.no);
        if (!응답 || !응답.frame) throw new Error('명령 생성 실패');

        await _ble.writeLine(응답.frame);
        _로그('📤 ' + 동작.name + ' 전송 완료 (' + 동작.cmd + ')');
        return true;

    } catch (e) {
        _로그('❌ 전송 실패: ' + ((e && e.message) || e), true);
        return false;

    } finally {
        _sending = false;
        if (_watchdog) { clearTimeout(_watchdog); _watchdog = null; }
    }
}


/* ==========================================================================
   ⑧ 서버 통신 — 난독화는 서버가 합니다 (웹에는 평문 없음)
   ========================================================================== */

async function _api호출(번호) {
    var 토큰 = null;
    try { 토큰 = localStorage.getItem('access_token') || localStorage.getItem('token'); } catch (e) {}

    var 헤더 = { 'Content-Type': 'application/json' };
    if (토큰) 헤더['Authorization'] = 'Bearer ' + 토큰;

    var 응답 = await fetch(CONFIG.apiBase + CONFIG.cmdPath, {
        method: 'POST',
        headers: 헤더,
        body: JSON.stringify({ class_no: 번호 })
    });

    if (!응답.ok) throw new Error('HTTP ' + 응답.status);
    var 자료 = await 응답.json();
    return (자료 && 자료.data) ? 자료.data : 자료;
}


/* ==========================================================================
   ⑨ 카메라 / 음성 연동 — 기존 결과를 받아서 보내기만 하면 됩니다
   ==========================================================================
      기존 ml-studio.js 가 분류 결과를 내놓을 때 이 함수를 부르게 하세요:

          btcarOnResult(번호, 확률);     // 확률은 0~1

      그러면 확률이 기준 이상일 때만 자동으로 보냅니다.
   ========================================================================== */

var 결과설정 = {
    최소확률: 0.7,     // 이 확률 이상일 때만 전송
    최소격차: 0.3,     // 2등과 이만큼 차이날 때만 전송
};

var _마지막결과 = { no: -1, prob: 0 };

/**
 * @param {number} 번호      클래스 번호 (1부터)
 * @param {number} 확률      확신도 0~1
 * @param {number} [격차]    2등과의 차이 0~1 (없으면 자동 통과)
 */
function btcarOnResult(번호, 확률, 격차) {
    if (확률 < 결과설정.최소확률) {
        _로그('🔇 보류 — 확률 ' + Math.round(확률 * 100) + '% (기준 ' +
              Math.round(결과설정.최소확률 * 100) + '%)', false);
        return;
    }
    if (격차 !== undefined && 격차 < 결과설정.최소격차) {
        _로그('🔇 보류 — 2등과 차이 ' + Math.round(격차 * 100) + '%p', false);
        return;
    }

    var 동작 = 찾기(번호);
    if (동작) _로그('🔒 확정: ' + 동작.name + ' ' + Math.round(확률 * 100) + '%');

    보내기(번호);   // ★ 여기서 전송 (중복 차단은 보내기() 안에서 처리)
}


/* ==========================================================================
   ⑩ 내보내기 — 화면에서 "누비다." 로 시작하면 다 됩니다
   ========================================================================== */

window.누비다 = {
    연결: 연결,
    해제: 해제,
    연결됨: 연결됨,
    보내기: 보내기,
    찾기: 찾기,
    표: ACTIONS,          // 표를 화면에서 직접 볼 수 있게
    설정: CONFIG,
    결과설정: 결과설정
};

/* 영어 이름도 제공 (한글 타이핑이 불편할 때) */
window.btcar = window.누비다;
