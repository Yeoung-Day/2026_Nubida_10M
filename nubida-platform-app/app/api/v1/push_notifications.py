"""
🔔 PWA Push Notification API — Web Push 구독/발송
"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.config import settings
from app.models import PushSubscription, Notification
from app.schemas import ApiResponse

router = APIRouter(prefix="/push", tags=["푸시 알림"])


# ============================================================
# VAPID public key 조회 (프론트에서 구독 시 필요)
# ============================================================

@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """VAPID 공개키 — 브라우저 PushSubscription 생성 시 사용"""
    return ApiResponse(data={
        "public_key": settings.VAPID_PUBLIC_KEY,
        "claim_email": settings.VAPID_CLAIM_EMAIL,
    })


# ============================================================
# 구독 등록 (upsert)
# ============================================================

@router.post("/subscribe")
async def subscribe(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push 구독 정보 저장 (중복 시 업데이트)"""
    endpoint = data.get("endpoint")
    p256dh_key = data.get("keys", {}).get("p256dh") or data.get("p256dh")
    auth_key = data.get("keys", {}).get("auth") or data.get("auth")

    if not endpoint or not p256dh_key or not auth_key:
        raise HTTPException(status_code=400, detail="endpoint, p256dh, auth 모두 필요합니다.")

    # Upsert
    stmt = sqlite_insert(PushSubscription).values(
        user_id=current_user["id"],
        endpoint=endpoint,
        p256dh_key=p256dh_key,
        auth_key=auth_key,
        user_agent=data.get("user_agent", ""),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "endpoint"],
        set_={
            "p256dh_key": p256dh_key,
            "auth_key": auth_key,
            "user_agent": data.get("user_agent", ""),
        }
    )
    await db.execute(stmt)
    await db.commit()

    return ApiResponse(message="구독이 등록되었습니다.")


# ============================================================
# 구독 해제
# ============================================================

@router.post("/unsubscribe")
async def unsubscribe(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push 구독 해제"""
    endpoint = data.get("endpoint")
    if endpoint:
        await db.execute(
            delete(PushSubscription)
            .where(PushSubscription.user_id == current_user["id"])
            .where(PushSubscription.endpoint == endpoint)
        )
    else:
        # 전체 해제
        await db.execute(
            delete(PushSubscription)
            .where(PushSubscription.user_id == current_user["id"])
        )
    await db.commit()
    return ApiResponse(message="구독이 해제되었습니다.")


# ============================================================
# 푸시 알림 발송 (내부 호출용)
# ============================================================

async def send_push_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    body: str = "",
    notif_type: str = "general",
    data: Optional[dict] = None,
):
    """특정 사용자에게 푸시 알림 발송

    1. DB에 Notification 레코드 저장
    2. 모든 PushSubscription에 Web Push 발송
    """
    import asyncio
    from app.core.event_bus import event_bus

    # 1. DB 저장
    notif = Notification(
        user_id=user_id,
        title=title,
        content=body,
        notif_type=notif_type,
        is_read=False,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)

    # 2. SSE 실시간 전송
    try:
        event_data = json.dumps({
            "type": "notification",
            "data": {
                "id": notif.id,
                "title": title,
                "content": body,
                "type": notif_type,
                "created_at": str(notif.created_at),
            }
        })
        await event_bus.publish(user_id, event_data)
    except Exception:
        pass  # SSE 실패해도 main 기능에는 영향 없음

    # 3. 발송 — 네이티브(FCM/APNs) + 웹 푸시(VAPID)
    subs_result = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user_id)
    )
    subscriptions = subs_result.scalars().all()

    payload = json.dumps({
        "title": title,
        "body": body,
        "tag": notif_type,
        "data": data or {},
        "icon": "/common/assets/logo.svg",
        "badge": "/common/assets/logo.svg",
    })

    web_subs = [s for s in subscriptions if s.endpoint]
    native_subs = [s for s in subscriptions if s.device_token]

    # ── 3-A. 네이티브 앱 (FCM / APNs) ──
    if native_subs:
        await _send_native_push(db, native_subs, title, body, notif_type, data)

    # ── 3-B. 웹 푸시 (VAPID) ──
    if web_subs:
        try:
            from pywebpush import webpush, WebPushException

            for sub in web_subs:
                try:
                    webpush(
                        subscription_info={
                            "endpoint": sub.endpoint,
                            "keys": {
                                "p256dh": sub.p256dh_key,
                                "auth": sub.auth_key,
                            }
                        },
                        data=payload,
                        vapid_private_key=settings.VAPID_PRIVATE_KEY,
                        vapid_claims={
                            "sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}",
                        },
                    )
                except WebPushException as e:
                    # 410 Gone = 구독 만료 → 삭제
                    if e.response and e.response.status_code == 410:
                        await db.execute(
                            delete(PushSubscription).where(PushSubscription.id == sub.id)
                        )
                        await db.commit()
                except Exception:
                    pass  # 개별 발송 실패는 무시
        except ImportError:
            pass  # pywebpush 미설치 시 무시
        except Exception:
            pass

    return notif


# ============================================================
# 네이티브 푸시 발송 (FCM / APNs)
# ============================================================

def _fcm_configured() -> bool:
    """FCM 자격증명(서비스 계정)이 설정돼 있는지"""
    try:
        return bool(
            settings.FCM_CREDENTIALS_JSON
            or (settings.FCM_CREDENTIALS_FILE and __import__("os").path.exists(settings.FCM_CREDENTIALS_FILE))
        )
    except Exception:
        return False


def _apns_configured() -> bool:
    """APNs 자격증명(.p8 키)이 설정돼 있는지"""
    try:
        import os
        return bool(
            settings.APNS_KEY_ID
            and settings.APNS_TEAM_ID
            and settings.APNS_KEY_FILE
            and os.path.exists(settings.APNS_KEY_FILE)
        )
    except Exception:
        return False


async def _send_native_push(
    db: AsyncSession,
    subs: list,
    title: str,
    body: str,
    notif_type: str,
    data: Optional[dict] = None,
):
    """FCM(Android) + APNs(iOS) 발송

    - Android → Firebase Admin SDK (google-services.json / 서비스 계정 JSON)
    - iOS     → APNs HTTP/2 (JWT .p8 키)
    ⚠️ 자격증명 미설정 시 조용히 건너뛴다 (웹 푸시는 계속 동작).
    """
    import asyncio

    data_payload = {k: str(v) for k, v in (data or {}).items()}
    data_payload["notif_type"] = notif_type

    android_tokens = [s.device_token for s in subs if s.platform == "android" and s.device_token]
    ios_tokens = [s.device_token for s in subs if s.platform == "ios" and s.device_token]

    # ── Android: FCM ──
    if android_tokens and _fcm_configured():
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging

            if not firebase_admin._apps:
                if settings.FCM_CREDENTIALS_JSON:
                    cred = credentials.Certificate(json.loads(settings.FCM_CREDENTIALS_JSON))
                else:
                    cred = credentials.Certificate(settings.FCM_CREDENTIALS_FILE)
                firebase_admin.initialize_app(cred)

            # 500개씩 배치
            for i in range(0, len(android_tokens), 500):
                batch = android_tokens[i:i + 500]
                msg = messaging.MulticastMessage(
                    tokens=batch,
                    notification=messaging.Notification(title=title, body=body),
                    data=data_payload,
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            sound="default",
                            channel_id="nubida_default",
                        ),
                    ),
                )
                try:
                    resp = await asyncio.to_thread(messaging.send_each_for_multicast, msg)
                    # 무효 토큰 정리
                    for idx, r in enumerate(resp.responses):
                        if not r.success:
                            err = str(r.exception)
                            if "registration-token-not-registered" in err or "invalid-argument" in err:
                                await db.execute(
                                    delete(PushSubscription).where(
                                        PushSubscription.device_token == batch[idx]
                                    )
                                )
                    await db.commit()
                except Exception:
                    pass
        except ImportError:
            pass  # firebase-admin 미설치
        except Exception:
            pass

    # ── iOS: APNs ──
    if ios_tokens and _apns_configured():
        try:
            import httpx
            import time
            import jwt as pyjwt  # PyJWT

            with open(settings.APNS_KEY_FILE, "r") as f:
                private_key = f.read()

            token = pyjwt.encode(
                {"iss": settings.APNS_TEAM_ID, "iat": int(time.time())},
                private_key,
                algorithm="ES256",
                headers={"kid": settings.APNS_KEY_ID},
            )
            host = "api.push.apple.com" if not settings.APNS_USE_SANDBOX else "api.sandbox.push.apple.com"
            url = f"https://{host}/3/device/"

            headers = {
                "authorization": f"bearer {token}",
                "apns-topic": settings.APNS_BUNDLE_ID or "kr.nubida.app",
                "apns-push-type": "alert",
                "apns-priority": "10",
            }
            payload = {
                "aps": {
                    "alert": {"title": title, "body": body},
                    "sound": "default",
                    "badge": 1,
                },
                **data_payload,
            }

            async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
                for dev_token in ios_tokens:
                    try:
                        r = await client.post(url + dev_token, json=payload, headers=headers)
                        if r.status_code in (400, 410):
                            # BadDeviceToken / Unregistered → 정리
                            await db.execute(
                                delete(PushSubscription).where(
                                    PushSubscription.device_token == dev_token
                                )
                            )
                    except Exception:
                        pass
                await db.commit()
        except ImportError:
            pass  # httpx / PyJWT 미설치
        except Exception:
            pass


# ============================================================
# 네이티브 기기 토큰 등록 (앱 → 서버)
# ============================================================

@router.post("/register-device")
async def register_device(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """네이티브 앱(FCM/APNs) 기기 토큰 등록

    body: { token, platform: 'android'|'ios', device_id?, app_version? }
    """
    token = (data.get("token") or "").strip()
    platform = (data.get("platform") or "").strip().lower()
    device_id = (data.get("device_id") or "").strip() or None
    app_version = (data.get("app_version") or "").strip() or None

    if not token:
        raise HTTPException(status_code=400, detail="토큰이 필요합니다.")
    if platform not in ("android", "ios", "web"):
        raise HTTPException(status_code=400, detail="platform 은 android/ios/web 중 하나여야 합니다.")

    user_id = int(current_user.get("user_id") or current_user.get("id") or 0)

    # 같은 토큰이 이미 있으면 소유자/시각 갱신 (중복 방지)
    existing = await db.execute(
        select(PushSubscription).where(PushSubscription.device_token == token)
    )
    sub = existing.scalars().first()

    from datetime import datetime
    now = datetime.utcnow()

    if sub:
        sub.user_id = user_id
        sub.platform = platform
        if device_id is not None:
            sub.device_id = device_id
        if app_version is not None:
            sub.app_version = app_version
        sub.last_seen_at = now
    else:
        sub = PushSubscription(
            user_id=user_id,
            device_token=token,
            platform=platform,
            device_id=device_id,
            app_version=app_version,
            last_seen_at=now,
            user_agent=device_id or platform,
        )
        db.add(sub)

    await db.commit()
    await db.refresh(sub)

    return ApiResponse(
        status="success",
        message="기기가 등록되었습니다.",
        data={"id": sub.id, "platform": platform},
    )


@router.post("/unregister-device")
async def unregister_device(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """네이티브 기기 토큰 해제 (로그아웃 등)"""
    token = (data.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="토큰이 필요합니다.")

    await db.execute(delete(PushSubscription).where(PushSubscription.device_token == token))
    await db.commit()
    return ApiResponse(status="success", message="기기 등록이 해제되었습니다.")


@router.get("/native-status")
async def native_push_status(
    current_user: dict = Depends(require_role("super_admin", "admin")),
):
    """네이티브 푸시 자격증명 설정 상태 (관리자 진단용)"""
    return ApiResponse(
        status="success",
        data={
            "fcm_configured": _fcm_configured(),
            "apns_configured": _apns_configured(),
            "note": "자격증명이 없으면 앱 토큰은 등록되지만 실제 발송은 건너뜁니다.",
        },
    )


# ============================================================
# 전체 사용자에게 푸시 발송 API (관리자 전용)
# ============================================================

@router.post("/broadcast")
async def broadcast_push(
    data: dict,
    current_user: dict = Depends(require_role("super_admin", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """전체 사용자에게 푸시 알림 발송 (관리자 전용)"""
    title = data.get("title", "알림")
    body = data.get("body", "")
    notif_type = data.get("type", "broadcast")

    # 모든 사용자 조회
    from app.models import User
    users = await db.execute(select(User.id).where(User.is_active == True))
    user_ids = [row[0] for row in users.all()]

    # 각 사용자에게 발송
    for uid in user_ids:
        await send_push_notification(db, uid, title, body, notif_type)

    return ApiResponse(message=f"{len(user_ids)}명에게 알림을 발송했습니다.")


# ============================================================
# 특정 사용자에게 푸시 발송 API (내부용)
# ============================================================

@router.post("/send")
async def send_push(
    data: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자에게 테스트 푸시 발송"""
    await send_push_notification(
        db,
        current_user["id"],
        title=data.get("title", "테스트 알림"),
        body=data.get("body", "푸시 알림이 정상 작동합니다!"),
        notif_type=data.get("type", "test"),
    )
    return ApiResponse(message="푸시 알림을 발송했습니다.")


# ============================================================
# 도메인 알림 헬퍼 — 강좌 자료(학습내용) 변경 / 공지
# ============================================================

async def notify_course_updated(
    db: AsyncSession,
    course_id: int,
    action: str = "수정",
    title_suffix: str = "",
):
    """강좌 자료(학습내용)가 변경되면 수강 학생들에게 알림 발송.

    학생 알림 페이지 화이트리스트에 포함된 notif_type='learning_added' 로 적재한다.
    과거의 'course_updated' 스팸 타입은 더 이상 생성하지 않는다.
    """
    from app.models import Enrollment, Course
    from app.core.event_bus import event_bus

    try:
        c_res = await db.execute(select(Course.name).where(Course.id == course_id))
        course_name = c_res.scalar() or "강좌"

        s_res = await db.execute(
            select(Enrollment.student_id)
            .where(Enrollment.course_id == course_id, Enrollment.status == "active")
            .distinct()
        )
        student_ids = [row[0] for row in s_res.all()]
    except Exception:
        return

    label = "학습 내용이 추가되었습니다" if "추가" in action else "학습 내용이 업데이트되었습니다"
    for sid in student_ids:
        try:
            await send_push_notification(
                db,
                sid,
                title=f"[{course_name}] {label}",
                body=f"'{course_name}' 강좌에 새로운 학습 내용이 {action}되었습니다.",
                notif_type="learning_added",
                data={"course_id": course_id, "kind": "learning_added"},
            )
        except Exception:
            continue


async def notify_notice_published(
    db: AsyncSession,
    notice_title: str,
    notice_id: Optional[int] = None,
    target_student_ids: Optional[list] = None,
):
    """공지사항이 발행되면 학생들에게 알림 발송 (notif_type='notice')."""
    from app.models import User
    from sqlalchemy import select as _select

    if target_student_ids is None:
        try:
            u_res = await db.execute(_select(User.id).where(User.role == "student"))
            target_student_ids = [row[0] for row in u_res.all()]
        except Exception:
            return

    for sid in target_student_ids:
        try:
            await send_push_notification(
                db,
                sid,
                title="[공지] " + notice_title,
                body="새로운 공지사항이 등록되었습니다.",
                notif_type="notice",
                data={"notice_id": notice_id, "kind": "notice"},
            )
        except Exception:
            continue
