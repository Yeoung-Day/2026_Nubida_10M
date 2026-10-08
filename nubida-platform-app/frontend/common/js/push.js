/**
 * 누비다플랫폼 — PWA Push Notification 구독 관리
 * 모든 페이지에서 <script src="/common/js/push.js"></script> 로 로드
 */

let pushInitialized = false;

/**
 * Push 알림 초기화 (로그인 후 호출)
 */
async function initPushNotifications() {
    if (pushInitialized) return;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        console.log('🔔 Push 알림: 브라우저 미지원');
        return;
    }

    try {
        // 서비스워커가 이미 등록되어 있는지 확인
        const registration = await navigator.serviceWorker.ready;

        // 권한 확인
        if (Notification.permission === 'denied') {
            console.log('🔔 Push 알림: 권한 거부됨');
            return;
        }

        // 권한 요청 (아직 결정되지 않은 경우)
        if (Notification.permission === 'default') {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                console.log('🔔 Push 알림: 권한 거부');
                return;
            }
        }

        // VAPID 공개키 조회
        let publicKey;
        try {
            const res = await apiGet('/push/vapid-public-key');
            publicKey = res.data.public_key;
        } catch (e) {
            console.log('🔔 VAPID 키 조회 실패:', e);
            return;
        }

        // 기존 구독 확인
        let subscription = await registration.pushManager.getSubscription();
        const token = localStorage.getItem('token') || localStorage.getItem('access_token');
        if (!token) return;

        if (!subscription) {
            // 새 구독 생성
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey),
            });
        }

        // 서버에 구독 정보 전송
        const subData = subscription.toJSON();
        await apiPost('/push/subscribe', {
            endpoint: subData.endpoint,
            keys: subData.keys,
            user_agent: navigator.userAgent,
        });

        pushInitialized = true;
        console.log('🔔 Push 알림 구독 완료');
    } catch (e) {
        console.log('🔔 Push 알림 초기화 실패:', e);
    }
}

/**
 * Push 구독 해제 (로그아웃 시 호출)
 */
async function unsubscribePush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

    try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
            const subData = subscription.toJSON();
            // 서버에 구독 해제 알림
            try {
                await apiPost('/push/unsubscribe', { endpoint: subData.endpoint });
            } catch (e) { /* 무시 */ }
            await subscription.unsubscribe();
        }
        pushInitialized = false;
        console.log('🔔 Push 알림 구독 해제');
    } catch (e) {
        console.log('🔔 Push 알림 해제 실패:', e);
    }
}

/**
 * URL-safe Base64 → Uint8Array 변환
 * (PushManager.subscribe()의 applicationServerKey 형식)
 */
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

/**
 * 테스트 푸시 발송
 */
async function sendTestPush() {
    try {
        await apiPost('/push/send', {
            title: '✅ 누비다플랫폼',
            body: '푸시 알림이 정상 작동합니다!',
            type: 'test',
        });
        showAlert('🔔 테스트 푸시를 발송했습니다!', 'success');
    } catch (e) {
        showAlert('푸시 발송 실패: ' + (e.message || ''), 'error');
    }
}

// DOMContentLoaded 시 자동 초기화 (인증 완료 후)
document.addEventListener('DOMContentLoaded', function() {
    // 약간 지연해서 auth.js가 먼저 실행되도록 함
    setTimeout(function() {
        const token = localStorage.getItem('token') || localStorage.getItem('access_token');
        if (token) {
            initPushNotifications();
        }
    }, 500);
});
