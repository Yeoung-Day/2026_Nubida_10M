/**
 * 누비다플랫폼 모바일 앱 — 서버 주소 설정
 * 
 * 네이티브 앱(Capacitor)에서 API 호출 시 사용할 백엔드 서버 주소.
 * - 웹 브라우저에서는 이 값이 무시되고 상대 경로(/api/v1)가 사용됩니다.
 * - 터널 URL이 변경되면 이 파일의 MOBILE_API_URL만 갱신하면 됩니다.
 * 
 * ⚠️ HTTPS가 필수입니다 (iOS ATS / Android cleartext 제한).
 */
window.MOBILE_API_URL = 'https://xn--od1bqqv8i85hml3aulb.kr';

/**
 * 네이티브 셸(Capacitor) 감지 플래그
 * - capacitor:// (iOS) 또는 https://localhost (Android) origin이면 네이티브
 */
window.IS_NATIVE = (function () {
    try {
        if (window.Capacitor && window.Capacitor.isNativePlatform) {
            return window.Capacitor.isNativePlatform();
        }
        const origin = window.location.origin || '';
        return origin.startsWith('capacitor://') || origin === 'https://localhost' || origin === 'http://localhost';
    } catch (e) {
        return false;
    }
})();
