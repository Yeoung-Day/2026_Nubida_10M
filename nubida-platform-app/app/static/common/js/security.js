/**
 * 누비다플랫폼 — 보안 유틸리티 함수
 * XSS 방어, 입력 검증, HTML 이스케이프
 */

/**
 * HTML 특수문자 이스케이프 — XSS 방어 (가장 중요)
 * 사용법: element.innerHTML = esc(userInput)
 */
function esc(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
}

/**
 * HTML 태그 제거 (안전한 태그만 허용)
 */
function sanitizeHtml(str) {
    if (str == null) return '';
    const SAFE_TAGS = /<\/?(b|i|u|a|br|p|span|strong|em|ul|ol|li|h[1-6])[^>]*>/gi;
    return String(str)
        .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
        .replace(/on\w+\s*=\s*["'][^"']*["']/gi, '')
        .replace(/javascript\s*:/gi, '')
        .replace(/<[^>]*>/g, function(match) {
            return SAFE_TAGS.test(match) ? match : '';
        });
}

/**
 * 모든 HTML 태그 제거 → 순수 텍스트
 */
function stripTags(str) {
    if (str == null) return '';
    return String(str).replace(/<[^>]*>/g, '');
}

/**
 * 입력값 유형별 검증
 * @param {string} str - 검증할 문자열
 * @param {string} type - 'text' | 'email' | 'phone' | 'number' | 'url'
 * @returns {boolean}
 */
function validateInput(str, type) {
    if (str == null || str === '') return false;
    const val = String(str).trim();
    const rules = {
        text: () => val.length >= 1 && val.length <= 500,
        email: () => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val),
        phone: () => /^01[016789]-\d{3,4}-\d{4}$/.test(val) || /^\d{10,11}$/.test(val),
        number: () => /^\d+(\.\d+)?$/.test(val),
        url: () => {
            try { new URL(val); return true; }
            catch { return false; }
        }
    };
    return (rules[type] || rules.text)();
}

/**
 * 통합 XSS 방어: 태그 제거 + 이스케이프
 */
function preventXSS(str) {
    return esc(stripTags(str));
}

/**
 * API 응답 데이터 안전하게 표시
 * 객체/배열의 모든 문자열 필드에 esc() 적용
 */
function sanitizeData(data) {
    if (data == null) return data;
    if (typeof data === 'string') return esc(data);
    if (Array.isArray(data)) return data.map(sanitizeData);
    if (typeof data === 'object') {
        const safe = {};
        for (const [k, v] of Object.entries(data)) {
            safe[k] = sanitizeData(v);
        }
        return safe;
    }
    return data;
}
