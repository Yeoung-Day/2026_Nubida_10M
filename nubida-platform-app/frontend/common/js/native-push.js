/**
 * 누비다플랫폼 AI튜터 — 네이티브 앱 푸시 알림 (FCM / APNs)
 *
 * 하이브리드 앱(Capacitor)에서만 동작. 웹 브라우저에서는 조용히 무시된다.
 * - 앱 시작(로그인 후) 시 권한 요청 → 토큰 획득 → 서버 등록
 * - 알림 수신 시 배너 표시, 탭하면 해당 페이지로 이동
 *
 * 로드: 모든 주요 페이지에서 push.js 뒤에 추가
 *   <script src="/common/js/native-push.js?v=20260911a"></script>
 */
(function () {
    'use strict';

    var TAG = '🔔 [native-push]';
    var registered = false;
    var currentToken = null;

    function isNative() {
        try {
            if (window.Capacitor && window.Capacitor.isNativePlatform) {
                return window.Capacitor.isNativePlatform();
            }
            var o = window.location.origin || '';
            return o.startsWith('capacitor://') || o === 'https://localhost' || o === 'http://localhost';
        } catch (e) {
            return false;
        }
    }

    function getPlugin(name) {
        try {
            if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins[name]) {
                return window.Capacitor.Plugins[name];
            }
        } catch (e) {}
        return null;
    }

    function platform() {
        try {
            if (window.Capacitor && window.Capacitor.getPlatform) {
                return window.Capacitor.getPlatform();   // 'android' | 'ios' | 'web'
            }
        } catch (e) {}
        return 'web';
    }

    function getToken() {
        return localStorage.getItem('token') || localStorage.getItem('access_token') || '';
    }

    /** 서버에 기기 토큰 등록 */
    function registerToServer(token) {
        var t = getToken();
        if (!t) {
            console.log(TAG, '로그인 전 — 토큰 등록 보류');
            return Promise.resolve();
        }
        var body = {
            token: token,
            platform: platform(),
            device_id: (navigator.userAgent || '').slice(0, 180),
            app_version: (window.APP_VERSION || '1.0.0')
        };
        var base = (window.IS_NATIVE && window.MOBILE_API_URL)
            ? window.MOBILE_API_URL.replace(/\/+$/, '') + '/api/v1'
            : (window.location.protocol + '//' + window.location.host + '/api/v1');

        return fetch(base + '/push/register-device', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + t
            },
            body: JSON.stringify(body)
        }).then(function (r) {
            if (r.ok) console.log(TAG, '✅ 기기 등록 완료 (' + platform() + ')');
            else console.log(TAG, '⚠️ 기기 등록 실패', r.status);
        }).catch(function (e) {
            console.log(TAG, '⚠️ 기기 등록 오류', e);
        });
    }

    /** 푸시 초기화 */
    function initNativePush() {
        if (registered) return;
        if (!isNative()) return;

        var Push = getPlugin('PushNotifications');
        if (!Push) {
            console.log(TAG, 'PushNotifications 플러그인 없음 (앱 재빌드 필요)');
            return;
        }
        registered = true;

        // 1) 권한 요청
        Push.requestPermissions().then(function (perm) {
            if (perm.receive !== 'granted') {
                console.log(TAG, '알림 권한 거부됨');
                return;
            }

            // 2) 토큰 수신 리스너
            Push.addListener('registration', function (tok) {
                currentToken = tok.value;
                console.log(TAG, '토큰 수신:', String(tok.value).slice(0, 24) + '...');
                registerToServer(tok.value);
            });

            Push.addListener('registrationError', function (err) {
                console.log(TAG, '토큰 등록 오류', err);
            });

            // 3) 알림 수신 (포그라운드)
            Push.addListener('pushNotificationReceived', function (n) {
                console.log(TAG, '알림 수신', n);
                try {
                    if (window.showToast) {
                        showToast((n.title || '알림') + '\n' + (n.body || ''), 'info');
                    }
                } catch (e) {}
            });

            // 4) 알림 탭 → 페이지 이동
            Push.addListener('pushNotificationActionPerformed', function (action) {
                var d = (action && action.notification && action.notification.data) || {};
                var url = d.url || d.link || '';
                if (url) {
                    window.location.href = url;
                } else if (d.notif_type) {
                    // 유형별 기본 이동
                    var map = {
                        notice: '/pages/student/notifications.html',
                        learning_added: '/pages/student/courses.html',
                        portfolio_approved: '/pages/student/portfolio.html',
                        portfolio_rejected: '/pages/student/portfolio.html',
                        portfolio_feedback: '/pages/student/portfolio.html',
                        portfolio_revision: '/pages/student/portfolio.html',
                        portfolio_status: '/pages/student/portfolio.html'
                    };
                    if (map[d.notif_type]) window.location.href = map[d.notif_type];
                }
            });

            // 5) 등록 실행
            Push.register();
        }).catch(function (e) {
            console.log(TAG, '권한 요청 실패', e);
        });
    }

    /** Android 알림 채널 생성 (Android 8+) */
    function createChannel() {
        if (!isNative()) return;
        var Push = getPlugin('PushNotifications');
        if (!Push || !Push.createChannel) return;
        try {
            Push.createChannel({
                id: 'nubida_default',
                name: '누비다 알림',
                description: '누비다플랫폼 AI튜터 알림',
                importance: 4,
                visibility: 1,
                sound: 'default',
                vibration: true
            }).then(function () {
                console.log(TAG, '알림 채널 생성');
            }).catch(function () {});
        } catch (e) {}
    }

    /** 로그인 후 재등록 (토큰이 이미 있으면 서버에 다시 등록) */
    window.initNativePush = initNativePush;
    window.nativePushReregister = function () {
        if (currentToken) registerToServer(currentToken);
    };

    // 앱 시작 시
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            createChannel();
            setTimeout(initNativePush, 800);
        });
    } else {
        createChannel();
        setTimeout(initNativePush, 800);
    }
})();
