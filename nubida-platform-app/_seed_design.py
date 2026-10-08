"""디자인 확인용 샘플 공고 시드 (검증 후 삭제 예정)."""
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import text
from app.core.database import get_db

ROWS = [
    dict(t="2026 하반기 강사양성과정 모집", c="강사양성과정",
         s="초등 코딩 지도 역량을 키우는 정규 강사양성과정입니다.",
         ct="누비다플랫폼과 함께할 강사를 모집합니다.\n\n■ 교육 대상\n- 코딩 교육에 관심 있는 누구나\n- 누비다플랫폼 소속 희망 강사\n\n■ 교육 일정\n- 2026.10.01(수) ~ 10.31(금)\n- 매주 수·금 19:00 ~ 21:00\n\n■ 교육 내용\n1. 블록코딩 지도법\n2. 아두이노·센서 활용 수업 설계\n3. AI 활용 교육 워크숍\n4. 학부모 상담 및 클래스 운영\n\n■ 수료 혜택\n- 누비다플랫폼 인증 강사 자격\n- 소속 학원 매칭 우선권",
         st="open", rs="2026-09-21", re="2026-10-31", cap=30,
         lo="서울 강남 본사 교육장", fe="무료", co="1661-0000",
         pin=1, so=0),
    dict(t="겨울방학 특강 — 아두이노 메이커 클래스 지도사 과정", c="코딩지도사",
         s="방학 특강을 직접 운영할 수 있는 실전 중심 과정입니다.",
         ct="겨울방학 특강 강사를 양성하는 실습 중심 과정입니다.\n\n■ 과정 개요\n방학 기간 집중 운영되는 메이커 클래스를 직접 설계하고 운영할 수 있도록 돕습니다.\n\n■ 실습 키트\n- 아두이노 나노 + 확장보드\n- 초음파 센서 / 서보모터 / LED\n\n■ 특전\n- 수료 후 특강 배정 우선\n- 교안 및 소스코드 제공",
         st="open", rs="2026-10-01", re="2026-11-30", cap=20,
         lo="부산 해운대 교육장", fe="30만원", co="1661-0000",
         pin=0, so=1),
    dict(t="[마감] 2026 상반기 학부모 코딩교실", c="학부모교육",
         s="학부모님을 위한 4주 단기 코딩 체험 과정입니다.",
         ct="학부모님을 대상으로 한 단기 체험 과정입니다.\n\n■ 일정 : 2026.04.01 ~ 04.30 (4주)\n■ 대상 : 초등 학부모 20명\n■ 장소 : 서울 강남 본사\n\n※ 본 과정은 모집이 마감되었습니다.",
         st="closed", rs="2026-03-01", re="2026-03-28", cap=20,
         lo="서울 강남 본사", fe="무료", co="1661-0000",
         pin=0, so=2),
]


async def main():
    gen = get_db()
    db = await gen.__anext__()
    async with db as conn:
        await conn.execute(text("DELETE FROM edu_programs"))
        for r in ROWS:
            await conn.execute(text("""
                INSERT INTO edu_programs
                  (title, category, content, summary, status, recruit_start, recruit_end,
                   capacity, location, fee, contact, is_pinned, sort_order, is_visible,
                   created_by_name)
                VALUES (:t,:c,:ct,:s,:st,:rs,:re,:cap,:lo,:fe,:co,:pin,:so,1,'본사')
            """), r)
        await conn.commit()
        n = await conn.execute(text("SELECT COUNT(*) FROM edu_programs"))
        print("공고:", n.scalar())


asyncio.run(main())
