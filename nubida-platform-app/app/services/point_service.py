"""
포인트 자동 지급 유틸리티 — 교육 완료 / 포트폴리오 승인 시 호출
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import CoursePoint, PointTransaction


async def award_points_for_course_completion(
    db: AsyncSession,
    student_id: int,
    course_id: int,
    enrollment_id: int,
) -> int:
    """교육 과정 완료 시 포인트 지급 (반환: 지급된 포인트)"""
    points = await _get_course_points(db, "course", course_id)
    if points <= 0:
        return 0

    txn = PointTransaction(
        user_id=student_id,
        points=points,
        transaction_type="course_complete",
        reference_id=enrollment_id,
        description=f"교육 과정 완료 포인트 ({points}p)",
    )
    db.add(txn)
    await db.commit()
    return points


async def award_points_for_portfolio_approve(
    db: AsyncSession,
    student_id: int,
    portfolio_id: int,
    course_id: int = None,
) -> int:
    """포트폴리오 승인 시 포인트 지급 (반환: 지급된 포인트)"""
    points = await _get_course_points(db, "portfolio", course_id)
    if points <= 0:
        return 0

    txn = PointTransaction(
        user_id=student_id,
        points=points,
        transaction_type="portfolio_approve",
        reference_id=portfolio_id,
        description=f"포트폴리오 승인 포인트 ({points}p)",
    )
    db.add(txn)
    await db.commit()
    return points


async def _get_course_points(
    db: AsyncSession,
    target_type: str,
    target_id: int = None,
) -> int:
    """
    포인트 설정 조회 로직:
    1. 특정 target_id에 설정된 포인트가 있으면 사용
    2. 없으면 target_id=NULL(기본값) 설정 사용
    3. 없으면 0 반환
    """
    # 1. 특정 ID 설정
    if target_id:
        result = await db.execute(
            select(CoursePoint).where(
                CoursePoint.target_type == target_type,
                CoursePoint.target_id == target_id,
                CoursePoint.is_active == True,
            )
        )
        cp = result.scalar_one_or_none()
        if cp:
            return cp.points

    # 2. 기본값 설정
    result = await db.execute(
        select(CoursePoint).where(
            CoursePoint.target_type == target_type,
            CoursePoint.target_id.is_(None),
            CoursePoint.is_active == True,
        )
    )
    cp = result.scalar_one_or_none()
    return cp.points if cp else 0
