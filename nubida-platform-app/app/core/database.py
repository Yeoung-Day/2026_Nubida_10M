from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, func

from app.core.config import settings

# SQLite timeout 설정 (5초 busy wait, WAL 모드)
connect_args = {"timeout": 15} if "sqlite" in settings.DATABASE_URL else {}

# MySQL 등 풀링 필요 시에만 pool 인자 적용
# (SQLite/aiosqlite는 NullPool — pool_size/max_overflow 전달 시 TypeError 발생)
engine_kwargs = dict(echo=settings.DEBUG, connect_args=connect_args)
if "sqlite" not in settings.DATABASE_URL:
    engine_kwargs.update(
        pool_recycle=3600,       # 1시간마다 연결 재생성 (MySQL wait_timeout 8시간 대비)
        pool_pre_ping=False,     # aiomysql 호환성 문제로 비활성화 (SQLAlchemy 2.0.23 + aiomysql 0.3.2 ping() 호환 버그)
        pool_size=5,             # 동시 연결 수
        max_overflow=10,         # 추가 연결 허용
    )
engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def _ensure_column(conn, table, column, ddl):
    """SQLite 컬럼 자동 마이그레이션 — 이미 존재하면 무시, 실패해도 서버 기동에는 영향 없음"""
    try:
        rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        names = [r[1] for r in rows]
        if column not in names:
            await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    except Exception as e:
        print(f"[migration] {table}.{column} 스킵: {e}")


async def init_db():
    async with engine.begin() as conn:
        from app.models import all_models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
        # busy_timeout 설정만 (WAL 모드 비활성화 - overlayfs 호환성)
        if "sqlite" in settings.DATABASE_URL:
            await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
            # ── 자동 마이그레이션: 학생 첫 접속 사용가이드 (온보딩) ──
            await _ensure_column(conn, "users", "first_login_at", "first_login_at DATETIME")
            await _ensure_column(conn, "users", "onboarding_done", "onboarding_done BOOLEAN DEFAULT 0")
            # ── 자동 마이그레이션: 학습 진행률 block_index (콘텐츠 블록 진행) ──
            await _ensure_column(conn, "learning_progress", "block_index", "block_index INTEGER")

    # ── 기본 과목(교육명) 마스터 시드 (subjects 테이블이 비어 있을 때만) ──
    try:
        async with async_session() as seed_session:
            from app.models import Subject
            cnt = (await seed_session.execute(select(func.count()).select_from(Subject))).scalar() or 0
            if cnt == 0:
                for i, name in enumerate(["국어", "수학", "영어", "과학", "사회", "코딩", "메이커", "AI", "기타"]):
                    seed_session.add(Subject(name=name, sort_order=i))
                await seed_session.commit()
                print("[seed] 기본 과목 마스터 9종 등록 완료")
    except Exception as e:
        print(f"[seed] 과목 마스터 시드 스킵: {e}")
