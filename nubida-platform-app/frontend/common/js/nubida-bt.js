/**
 * 누비다머신 명령 난독화 모듈 (NubidaBT v1)
 * ===========================================
 * 블루투스/시리얼(Web Serial)로 나가는 명령이 "{n}{접두어}" 평문 그대로
 * 노출되지 않도록 XOR 스트림 프레임으로 변환한다.
 *
 * ▸ 와이어 형식 (줄바꿈 제외, ASCII hex만 출력):
 *     'x' + HEX(seed ^ KEY) + HEX(b0 ^ seed) + HEX(b1 ^ seed) + ...
 *     - seed : 전송마다 1~255 랜덤  →  같은 명령도 매번 다른 문자열
 *     - bN   : "{클래스번호}{접두어}" 원문의 UTF-8 바이트
 *     - KEY  : 수신 펌웨어와 공유하는 고정 키 (0x2F)
 *
 * ▸ 수신측(아두이노 펌웨어) 복호화:
 *     seed = HEX(1~2자리) ^ KEY → 이후 각 HEX 2자리를 seed와 XOR → 원문
 *     → 기존 규약(클래스 번호 해석)을 그대로 수행.
 *
 * ▸ 보안 특성
 *     - 와이어 캡처만으로는 클래스 번호/접두어 의미를 유추할 수 없다.
 *       (평문 '1NubidaAi', 'NubidaAi', 'ACTION' 등 ASCII 패턴이 전혀 등장하지 않음)
 *     - 전송마다 seed가 바뀌므로 같은 명령의 반복 전송도 매번 다른 값.
 *     - 'x' 마커는 기존 프로토콜(ACTION:, 평문 숫자 등)과 충돌하지 않음.
 *
 * ▸ KEY 변경 시: 본 파일 + 샘플 수신 펌웨어(nubida_machine_receiver.ino)의
 *   NB_KEY를 동일하게 맞춰 함께 배포해야 한다.
 */
window.NubidaBT = (function () {
    'use strict';

    var KEY = 0x2F; // 펌웨어 NB_KEY와 동일해야 함

    function toHex(b) {
        var h = b.toString(16);
        return h.length < 2 ? '0' + h : h;
    }

    function fromHex(h) {
        var v = parseInt(h, 16);
        return isNaN(v) ? 0 : v;
    }

    /**
     * 평문 "{n}{접두어}" (예: '1NubidaAi') → 난독화 프레임 문자열
     * @param {string} plain
     * @returns {string} 예: 'x3d8f1a7c...'
     */
    function encode(plain) {
        var bytes = new TextEncoder().encode(String(plain));
        var seed = 1 + Math.floor(Math.random() * 255); // 1~255 (0이면 원문 노출)
        var out = 'x' + toHex(seed ^ KEY);
        for (var i = 0; i < bytes.length; i++) {
            out += toHex(bytes[i] ^ seed);
        }
        return out;
    }

    /**
     * 난독화 프레임 → 평문 복원 (디버그/테스트/펌웨어 로직 검증용)
     * 전송부에서는 사용하지 않는다. UTF-8 바이트를 Uint8Array로 복원 후
     * TextDecoder로 디코딩하므로 한글 접두어도 안전하다.
     * @param {string} frame 'x...' 로 시작하는 난독화 프레임
     * @returns {string} 원문 (형식 오류 시 '')
     */
    function decode(frame) {
        if (typeof frame !== 'string' || frame.charAt(0) !== 'x') return '';
        var hex = frame.slice(1);
        if (hex.length < 4 || hex.length % 2 !== 0) return '';
        var seed = fromHex(hex.substr(0, 2)) ^ KEY;
        if (seed === 0) return '';
        var bytes = new Uint8Array((hex.length - 2) / 2);
        for (var i = 2; i < hex.length; i += 2) {
            bytes[(i - 2) / 2] = fromHex(hex.substr(i, 2)) ^ seed;
        }
        return new TextDecoder().decode(bytes);
    }

    /**
     * 난독화 프레임 여부 (수신 로그 분류 등에 사용)
     */
    function isFrame(s) {
        return typeof s === 'string' && s.length >= 5 &&
               s.charAt(0) === 'x' && ((s.length - 1) % 2 === 0);
    }

    return {
        KEY: KEY,
        encode: encode,
        decode: decode,
        isFrame: isFrame
    };
})();
