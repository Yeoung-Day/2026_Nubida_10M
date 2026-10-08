# -*- coding: utf-8 -*-
"""
공개(Public) API — 인증 불필요 엔드포인트 모음
누비다플랫폼 공개 랜딩/소개 페이지에서 사용하는 콘텐츠 제공
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import ApiResponse
from app.services.site_content import get_site_content

router = APIRouter(prefix="/public", tags=["공개"])


@router.get("/site-content")
async def get_public_site_content(db: AsyncSession = Depends(get_db)):
    """
    공개 — 공개사이트 콘텐츠 (네비/푸터/상담정보/페이지 본문)
    인증 불필요. 최초 호출 시 기본 시드가 자동 삽입된다.
    """
    data = await get_site_content(db)
    return ApiResponse(data=data)
