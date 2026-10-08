"""
누비다 AI — 채팅 어시스턴트 라우터 (확정설계안 v2)

- 학생: POST /ai/chat, POST /ai/feedback, GET /ai/history
- 원장/본사: GET /ai/faq/search
- 본사: POST /ai/faq/publish, GET /ai/stats
- 원칙: 정답 직접 제공 금지 (시스템 프롬프트 + attempt 게이트 + post-guard 이중/삼중 방어)
"""
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.schemas import ApiResponse, AiChatRequest, AiFeedbackRequest, AiFaqPublishRequest
from app.models import AiMessage, AiFaqKnowledge, AiFeedback, Enrollment, Course
from app.services import ai_client, rag
from app.services.prompt_builder import build_messages, guard_reply, MAX_ATTEMPT

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

DAILY_QUOTA = 50          # 학생 1일 질문 쿼터
HISTORY_LIMIT = 50
CONTEXT_HISTORY = 6       # LLM에 넣을 최근 대화 수


# ============================================================
# POST /api/v1/ai/chat — 학생 질문 → 누비다 AI 답변
# ============================================================
@router.post("/chat")
async def ai_chat(
    body: AiChatRequest,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]
    attempt = min(max(body.attempt, 1), MAX_ATTEMPT)

    # 1) 일일 쿼터 확인 (ai_messages 기준)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        await db.execute(
            select(func.count(AiMessage.id)).where(
                AiMessage.student_id == student_id,
                AiMessage.role == "user",
                AiMessage.created_at >= today_start,
            )
        )
    ).scalar() or 0
    if used >= DAILY_QUOTA:
        raise HTTPException(429, f"오늘 질문 한도를 모두 사용했어요 ({DAILY_QUOTA}회). 내일 다시 질문해 주세요.")

    # 2) 강좌 검증 (수강 중인 강좌만)
    course_name = None
    if body.course_id:
        enrolled = (
            await db.execute(
                select(Enrollment.id).where(
                    Enrollment.student_id == student_id,
                    Enrollment.course_id == body.course_id,
                )
            )
        ).scalar()
        if not enrolled:
            raise HTTPException(403, "수강 중인 강좌에 대해서만 질문할 수 있습니다.")
        course = await db.get(Course, body.course_id)
        course_name = course.name if course else None

    # 3) RAG 검색 (published 지식)
    similar_faqs = await rag.search_faq(db, body.message, body.course_id)
    faq_used = similar_faqs[0] if similar_faqs else None

    # 4) 최근 대화 이력
    history_rows = (
        await db.execute(
            select(AiMessage)
            .where(AiMessage.student_id == student_id)
            .order_by(AiMessage.id.desc())
            .limit(CONTEXT_HISTORY)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    # 5) LLM 호출 (자체 LLM — Ollama OPENAI 호환)
    messages = build_messages(
        question=body.message,
        attempt=attempt,
        similar_faqs=similar_faqs,
        history=history,
        course_name=course_name,
    )
    try:
        # 상세하고 긴 답변(개념+코드 뜯어 설명)이 잘리지 않도록 충분한 max_tokens 확보 (메인 8005과 동일)
        result = await ai_client.chat(messages, max_tokens=2048)
    except ai_client.LlmUnavailableError as e:
        raise HTTPException(
            503,
            "누비다 AI 서버가 아직 준비 중이에요. 잠시 후 다시 질문해 주세요. "
            f"(LLM 연결 안 됨: {str(e)[:80]})",
        ) from e

    # 6) post-guard (완성 코드 방어)
    reply = guard_reply(result["content"], attempt)

    # 7) 저장 (질문 + 답변)
    db.add(AiMessage(student_id=student_id, course_id=body.course_id, role="user", content=body.message, attempt=attempt))
    ai_msg = AiMessage(
        student_id=student_id,
        course_id=body.course_id,
        role="assistant",
        content=reply,
        model=result["model"],
        tokens_in=result["tokens_in"],
        tokens_out=result["tokens_out"],
        attempt=attempt,
        faq_id=faq_used["id"] if faq_used else None,
    )
    db.add(ai_msg)
    await db.commit()

    return ApiResponse(
        status="success",
        data={
            "reply": reply,
            "faq_used": bool(faq_used),
            "faq_id": faq_used["id"] if faq_used else None,
            "attempt": attempt,
            "allow_more": attempt < MAX_ATTEMPT,
            "message_id": ai_msg.id,
        },
    )


# ============================================================
# POST /api/v1/ai/chat/stream — 학생 질문 → SSE 스트리밍 답변
# ============================================================
#  guard_reply()는 '완성 코드'를 잘라내는 post-guard 이므로,
#  코드 블록(```) 안쪽은 화면에 보내지 않고 버퍼링한다.
#  - 코드 블록 밖  : 즉시 전송 (체감 대기 최소화)
#  - 코드 블록 안  : 버퍼링 후, 닫히는 순간 guard_reply로 검사
#      · 완성 스케치(setup~loop) → 차단 문구로 대체
#      · 일반 장문(15줄+)        → 앞 10줄만 노출
#      · 정상 코드               → 그대로 노출
@router.post("/chat/stream")
async def ai_chat_stream(
    body: AiChatRequest,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]
    attempt = min(max(body.attempt, 1), MAX_ATTEMPT)

    # 1) 일일 쿼터 확인 (ai_messages 기준)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        await db.execute(
            select(func.count(AiMessage.id)).where(
                AiMessage.student_id == student_id,
                AiMessage.role == "user",
                AiMessage.created_at >= today_start,
            )
        )
    ).scalar() or 0
    if used >= DAILY_QUOTA:
        raise HTTPException(429, f"오늘 질문 한도를 모두 사용했어요 ({DAILY_QUOTA}회). 내일 다시 질문해 주세요.")

    # 2) 강좌 검증
    course_name = None
    if body.course_id:
        enrolled = (
            await db.execute(
                select(Enrollment.id).where(
                    Enrollment.student_id == student_id,
                    Enrollment.course_id == body.course_id,
                )
            )
        ).scalar()
        if not enrolled:
            raise HTTPException(403, "수강 중인 강좌에 대해서만 질문할 수 있습니다.")
        course = await db.get(Course, body.course_id)
        course_name = course.name if course else None

    # 3) RAG 검색
    similar_faqs = await rag.search_faq(db, body.message, body.course_id)
    faq_used = similar_faqs[0] if similar_faqs else None

    # 4) 최근 대화 이력
    history_rows = (
        await db.execute(
            select(AiMessage)
            .where(AiMessage.student_id == student_id)
            .order_by(AiMessage.id.desc())
            .limit(CONTEXT_HISTORY)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    # 5) 프롬프트 구성
    messages = build_messages(
        question=body.message,
        attempt=attempt,
        similar_faqs=similar_faqs,
        history=history,
        course_name=course_name,
    )

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def event_gen():
        buf_out: list[str] = []   # 화면에 실제로 나간 텍스트(최종 저장용)
        model_used = ""
        tok_out = 0
        failed = False

        # ---- 코드 블록 상태 추적 ----
        # code_buf      : 현재 코드 블록 본문
        # fence_head    : 여는 펜스 원문 (```cpp 등 언어 태그 보존)
        # pending_text  : '```' 조각이 걸쳐 있을 수 있어 보류하는 텍스트
        code_buf: list[str] = []
        fence_head = "```"
        in_code = False
        pending_text = ""

        def emit(text: str) -> str:
            """화면 전송 + 최종 저장용 버퍼에 적재"""
            if text:
                buf_out.append(text)
            return _sse("delta", {"text": text}) if text else ""

        def feed_delta(piece: str):
            """
            조각을 상태에 따라 분류해 전송할 텍스트 목록을 만든다.

            핵심: 여는/닫는 펜스는 code_buf에 넣지 않는다.
                  (_guard_code_block이 복원하므로 중복 방지)
                  '```' 이 조각 경계에 걸치면 pending_text로 보류한다.
            """
            nonlocal in_code, fence_head, pending_text, code_buf
            out_events = []
            chunk = pending_text + piece
            pending_text = ""

            while chunk:
                if in_code:
                    idx = chunk.find("```")
                    if idx == -1:
                        # 닫는 펜스가 `` / ` 로 끝나면 다음 조각과 이어질 수 있어 보류
                        if chunk.endswith("``"):
                            code_buf.append(chunk[:-2])
                            pending_text = "``"
                        elif chunk.endswith("`"):
                            code_buf.append(chunk[:-1])
                            pending_text = "`"
                        else:
                            code_buf.append(chunk)
                        break
                    code_buf.append(chunk[:idx])
                    safe = _guard_code_block("".join(code_buf), fence_head)
                    code_buf = []
                    in_code = False
                    out_events.append(safe)
                    chunk = chunk[idx + 3:]
                else:
                    idx = chunk.find("```")
                    if idx == -1:
                        hold = 0
                        for k in (3, 2, 1):
                            if chunk.endswith("`" * k):
                                hold = k
                                break
                        if hold and len(chunk) > hold:
                            out_events.append(chunk[:-hold])
                            pending_text = chunk[-hold:]
                        elif hold:
                            pending_text = chunk
                        else:
                            out_events.append(chunk)
                        break
                    if idx > 0:
                        out_events.append(chunk[:idx])
                    nl = chunk.find("\n", idx)
                    if nl == -1:
                        # 펜스 라인이 아직 끝나지 않음 → 보류
                        pending_text = chunk[idx:]
                        break
                    head = chunk[idx:nl].strip() or "```"
                    if " " in head:
                        head = head.split()[0]
                    # 여는 펜스는 보관만 (본문에는 미포함)
                    fence_head = head
                    chunk = chunk[nl + 1:]
                    in_code = True
            return out_events

        try:
            async for ev in ai_client.stream_chat(messages, max_tokens=2048):
                if ev["type"] == "error":
                    failed = True
                    yield _sse("error", {
                        "detail": "누비다 AI 서버가 아직 준비 중이에요. "
                                  "잠시 후 다시 질문해 주세요."
                    })
                    break

                if ev["type"] == "done":
                    model_used = ev.get("model") or ""
                    tok_out = ev.get("tokens_out") or 0
                    # 남은 보류 텍스트/미닫힌 코드 블록 정리
                    if pending_text:
                        yield emit(pending_text)
                        pending_text = ""
                    if in_code and code_buf:
                        safe = _guard_code_block("".join(code_buf), fence_head)
                        code_buf = []
                        in_code = False
                        yield emit(safe)
                    break

                for piece_out in feed_delta(ev["text"]):
                    yield emit(piece_out)

        except Exception as exc:
            import traceback as _tb
            logger.error("[/ai/chat/stream] 스트리밍 실패: %r\n%s", exc, _tb.format_exc())
            yield _sse("error", {
                "detail": "답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요."
            })
            return

        if failed:
            return

        # 6) 최종 텍스트 → post-guard (코드 블록 밖 마크다운 정리 포함)
        final_text = guard_reply("".join(buf_out), attempt)

        # 7) 저장 (질문 + 답변)
        try:
            db.add(AiMessage(student_id=student_id, course_id=body.course_id,
                             role="user", content=body.message, attempt=attempt))
            ai_msg = AiMessage(
                student_id=student_id,
                course_id=body.course_id,
                role="assistant",
                content=final_text,
                model=model_used,
                tokens_in=0,
                tokens_out=tok_out,
                attempt=attempt,
                faq_id=faq_used["id"] if faq_used else None,
            )
            db.add(ai_msg)
            await db.commit()
            await db.refresh(ai_msg)
            msg_id = ai_msg.id
        except Exception:
            msg_id = None

        # 8) 메타데이터 전송 (푸터 정리 후 버튼 부착용)
        yield _sse("meta", {
            "message_id": msg_id,
            "attempt": attempt,
            "allow_more": attempt < MAX_ATTEMPT,
            "faq_used": bool(faq_used),
            "final": final_text,
        })
        yield _sse("done", {})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # 프록시 버퍼링 방지
            "Connection": "keep-alive",
        },
    )


def _guard_code_block(code_text: str, fence_head: str = "```") -> str:
    """
    코드 블록 하나를 post-guard 규칙에 맞게 정제한다.
      - 완성 스케치(setup~loop) → 차단 문구
      - 그 외                   → 원래 펜스(언어 태그 포함) 그대로 복원
    fence_head: 여는 펜스 원문 (예: '```cpp', '```')
    """
    from app.services.prompt_builder import _full_sketch_in_block
    if _full_sketch_in_block(code_text):
        return "\n(실행 가능한 완성 코드는 제공하지 않아요. 직접 조립해 보세요)\n"
    # 언어 태그를 보존해서 복원 (cpp/python 등이 사라지면 렌더링이 깨짐)
    head = fence_head if fence_head.startswith("```") else "```"
    return head + "\n" + code_text + "```\n"


# ============================================================
# POST /api/v1/ai/feedback — ✅해결(1) / ⚠️부족(-1)
# ============================================================
@router.post("/feedback")
async def ai_feedback(
    body: AiFeedbackRequest,
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]

    # 해당 답변 존재/소유 확인
    msg = await db.get(AiMessage, body.message_id)
    if not msg or msg.student_id != student_id or msg.role != "assistant":
        raise HTTPException(404, "답변 메시지를 찾을 수 없습니다.")

    db.add(
        AiFeedback(
            message_id=body.message_id,
            student_id=student_id,
            helpful=body.helpful,
            attempt=msg.attempt,  # 평가 대상 답변의 힌트 단계 (1~4)
            comment=body.comment,
        )
    )
    # 연결된 FAQ 카운트 반영 (해결/부족 → 학습)
    await rag.register_feedback(db, msg.faq_id, body.helpful)
    # 피드백 저장 — faq_id가 없어도 반드시 커밋 (register_feedback은 faq 없으면 commit 안 함)
    await db.commit()

    return ApiResponse(status="success", message="피드백이 반영되었습니다." if body.helpful == 1 else "더 자세한 힌트를 준비할게요!")


# ============================================================
# GET /api/v1/ai/history — 내 대화 이력
# ============================================================
@router.get("/history")
async def ai_history(
    course_id: int | None = Query(None),
    current_user: dict = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    student_id = current_user["id"]
    stmt = (
        select(AiMessage)
        .where(AiMessage.student_id == student_id)
        .order_by(AiMessage.id.desc())
        .limit(HISTORY_LIMIT)
    )
    if course_id:
        stmt = stmt.where(AiMessage.course_id == course_id)
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "course_id": m.course_id,
            "attempt": m.attempt,
            "faq_id": m.faq_id,
            "created_at": str(m.created_at) if m.created_at else None,
        }
        for m in reversed(rows)
    ]
    return ApiResponse(status="success", data=items)


# ============================================================
# GET /api/v1/ai/faq/search — FAQ 검색 (원장/본사)
# ============================================================
@router.get("/faq/search")
async def faq_search(
    q: str = Query("", max_length=200),
    course_id: int | None = Query(None),
    status: str = Query("published"),
    _: dict = Depends(require_role("director", "admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AiFaqKnowledge).where(AiFaqKnowledge.status == status)
    if course_id:
        stmt = stmt.where(AiFaqKnowledge.course_id == course_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (AiFaqKnowledge.question.like(like)) | (AiFaqKnowledge.answer.like(like))
        )
    stmt = stmt.order_by(AiFaqKnowledge.quality_score.desc()).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return ApiResponse(status="success", data=[rag._faq_to_dict(f) for f in rows])


# ============================================================
# POST /api/v1/ai/faq/publish — FAQ 승격/거절 (본사)
# ============================================================
@router.post("/faq/publish")
async def faq_publish(
    body: AiFaqPublishRequest,
    _: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    faq = await db.get(AiFaqKnowledge, body.faq_id)
    if not faq:
        raise HTTPException(404, "FAQ를 찾을 수 없습니다.")
    if body.action == "publish":
        faq.status = "published"
        msg = "FAQ가 승격되어 RAG에 반영되었습니다."
    else:
        faq.status = "rejected"
        msg = "FAQ가 거절 처리되었습니다."
    await db.commit()
    return ApiResponse(status="success", message=msg)


# ============================================================
# GET /api/v1/ai/stats — 통계 (본사)
# ============================================================
@router.get("/stats")
async def ai_stats(
    days: int = Query(7, ge=1, le=30),
    _: dict = Depends(require_role("admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now() - timedelta(days=days)

    total_q = (
        await db.execute(
            select(func.count(AiMessage.id)).where(AiMessage.role == "user", AiMessage.created_at >= since)
        )
    ).scalar() or 0

    total_a = (
        await db.execute(
            select(func.count(AiMessage.id)).where(AiMessage.role == "assistant", AiMessage.created_at >= since)
        )
    ).scalar() or 0

    solved = (
        await db.execute(
            select(func.count(AiFeedback.id)).where(AiFeedback.helpful == 1, AiFeedback.created_at >= since)
        )
    ).scalar() or 0
    lacking = (
        await db.execute(
            select(func.count(AiFeedback.id)).where(AiFeedback.helpful == -1, AiFeedback.created_at >= since)
        )
    ).scalar() or 0

    faq_count = (
        await db.execute(select(func.count(AiFaqKnowledge.id)).where(AiFaqKnowledge.status == "published"))
    ).scalar() or 0

    # 인기 FAQ top5 (해결률 기준)
    top_faqs = (
        await db.execute(
            select(AiFaqKnowledge)
            .where(AiFaqKnowledge.status == "published")
            .order_by((AiFaqKnowledge.up_count - AiFaqKnowledge.down_count).desc())
            .limit(5)
        )
    ).scalars().all()

    return ApiResponse(
        status="success",
        data={
            "period_days": days,
            "questions": total_q,
            "answers": total_a,
            "solved": solved,
            "lacking": lacking,
            "solve_rate": round(solved * 100 / (solved + lacking)) if (solved + lacking) else 0,
            "published_faqs": faq_count,
            "top_faqs": [rag._faq_to_dict(f) for f in top_faqs],
        },
    )
