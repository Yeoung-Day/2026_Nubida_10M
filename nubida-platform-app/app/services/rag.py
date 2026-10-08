"""
누비다 AI — RAG 검색 (ai_faq_knowledge 기반)

- 임베딩 유사도 검색 (로컬 임베딩 모델, ai_client.embed)
- 임베딩 불가 시 키워드(LIKE) fallback
- 해결률(up/(up+down)) 가중치로 '실제 도움 된 설명' 우선
- FAQ 승격 조건: 해결률 ≥ 70% & 누적 질문(up+down) ≥ 3
"""
import json
import math

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiFaqKnowledge
from app.services import ai_client

SIMILARITY_THRESHOLD = 0.75
TOP_K = 3
PROMOTE_SOLVE_RATE = 0.70
PROMOTE_MIN_VOTES = 3


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def solve_rate(up: int, down: int) -> float:
    total = up + down
    return (up / total) if total else 0.0


def _load_embedding(faq: AiFaqKnowledge) -> list[float]:
    try:
        return json.loads(faq.embedding) if faq.embedding else []
    except (json.JSONDecodeError, TypeError):
        return []


def _faq_to_dict(faq: AiFaqKnowledge, sim: float = 0.0) -> dict:
    return {
        "id": faq.id,
        "course_id": faq.course_id,
        "question": faq.question,
        "answer": faq.answer,
        "up_count": faq.up_count,
        "down_count": faq.down_count,
        "solve_rate": round(solve_rate(faq.up_count, faq.down_count) * 100),
        "status": faq.status,
        "sim": round(sim, 3),
    }


async def search_faq(
    db: AsyncSession,
    question: str,
    course_id: int | None = None,
    top_k: int = TOP_K,
) -> list[dict]:
    """
    published 지식에서 유사 Q&A 검색.
    우선순위: 유사도 × 해결률 가중 (실제로 도움 된 설명 우선)
    """
    stmt = select(AiFaqKnowledge).where(AiFaqKnowledge.status == "published")
    if course_id:
        stmt = stmt.where(or_(AiFaqKnowledge.course_id == course_id, AiFaqKnowledge.course_id.is_(None)))
    stmt = stmt.limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    # 1) 임베딩 유사도 (가능할 때)
    q_emb = await ai_client.embed(question)
    scored: list[tuple[float, AiFaqKnowledge]] = []
    if q_emb:
        for faq in rows:
            f_emb = _load_embedding(faq)
            sim = cosine_sim(q_emb, f_emb)
            if sim >= SIMILARITY_THRESHOLD:
                # 해결률 가중: 0.75 유사도 + 최대 0.2 보너스
                bonus = solve_rate(faq.up_count, faq.down_count) * 0.2
                scored.append((sim + bonus, faq))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [_faq_to_dict(faq, sim) for sim, faq in scored[:top_k]]

    # 2) 임베딩 불가 → 키워드 fallback (질문 키워드 포함 여부)
    terms = [t for t in question.replace("?", "").split() if len(t) >= 2][:5]
    if not terms:
        return []
    like_clauses = [AiFaqKnowledge.question.like(f"%{t}%") for t in terms]
    stmt2 = (
        select(AiFaqKnowledge)
        .where(AiFaqKnowledge.status == "published", or_(*like_clauses))
        .order_by((AiFaqKnowledge.up_count - AiFaqKnowledge.down_count).desc())
        .limit(top_k)
    )
    rows2 = (await db.execute(stmt2)).scalars().all()
    return [_faq_to_dict(f) for f in rows2]


async def add_knowledge(
    db: AsyncSession,
    question: str,
    answer: str,
    course_id: int | None = None,
    source: str = "ai",
    source_id: int | None = None,
) -> AiFaqKnowledge:
    """새 Q&A 지식 추가 (기본 pending) — 임베딩 캐시 포함"""
    emb = await ai_client.embed(question)
    faq = AiFaqKnowledge(
        course_id=course_id,
        question=question[:500],
        answer=answer,
        embedding=json.dumps(emb, ensure_ascii=False) if emb else None,
        source=source,
        source_id=source_id,
        status="pending",
    )
    db.add(faq)
    await db.commit()
    await db.refresh(faq)
    return faq


async def register_feedback(db: AsyncSession, faq_id: int | None, helpful: int) -> None:
    """✅해결 → up_count++, ⚠️부족 → down_count++ (해당 FAQ가 있을 때)"""
    if not faq_id:
        return
    faq = await db.get(AiFaqKnowledge, faq_id)
    if not faq:
        return
    if helpful == 1:
        faq.up_count += 1
    elif helpful == -1:
        faq.down_count += 1
    total = faq.up_count + faq.down_count
    faq.quality_score = solve_rate(faq.up_count, faq.down_count) if total else 0.0
    await db.commit()


def qualify_for_promotion(faq: AiFaqKnowledge) -> bool:
    """FAQ 승격 후보 조건: 해결률 ≥ 70% & 누적 질문 ≥ 3"""
    total = faq.up_count + faq.down_count
    return total >= PROMOTE_MIN_VOTES and solve_rate(faq.up_count, faq.down_count) >= PROMOTE_SOLVE_RATE
