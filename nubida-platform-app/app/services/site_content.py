# -*- coding: utf-8 -*-
"""
공개사이트 콘텐츠 관리 (네비게이션 / 푸터 / 상담정보 / 페이지 본문)

app_settings K-V 하나(key="site_content")에 JSON으로 저장한다.
- 공개 GET : /api/v1/public/site-content          (인증 불필요)
- 본사 GET : /api/v1/headquarters/site-content     (본사)
- 본사 PUT : /api/v1/headquarters/site-content     (본사 저장)
- 본사 GET : /api/v1/headquarters/site-content/pages/{slug}  (위지윅 에디터 단일 페이지)
- 본사 PUT : /api/v1/headquarters/site-content/pages/{slug}  (위지윅 에디터 단일 저장)
최초 조회 시 DEFAULT_SITE_CONTENT 를 자동 시드(lazy seed)한다.

페이지 본문 스키마 (pages[slug]):
    {
      "title": "…", "eyebrow": "…",
      "hero_image": "/common/...", "hero_alt": "…",
      "blocks": [ {id, type, …필드}, … ]
    }
블록 type 6종:
    section : h/p/img/alt      → 흰 카드 (img 있으면 상단 이미지 카드 fig-top)
    heading : h/level          → 단독 제목 (2~4)
    text    : p                → 단독 문단 (줄바꿈으로 여러 문단)
    image   : img/alt/caption  → 단독 이미지 카드
    divider : (없음)           → 구분선
    button  : label/url/style  → CTA 버튼 (primary/outline/ghost)
이전 버전(sections 배열) 데이터는 조회/저장 시점에 blocks 로 자동 변환한다.
"""
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

KEY = "site_content"

# 블록 type → 허용 필드 (위 외 키는 저장 시 폐기 — HTML 주입·임의 확장 차단)
BLOCK_SCHEMA = {
    "section": ("h", "p", "img", "alt"),
    "heading": ("h", "level"),
    "text": ("p",),
    "image": ("img", "alt", "caption"),
    "divider": (),
    "button": ("label", "url", "style"),
}

# 이미지/버튼 URL 허용 패턴 (외부 도메인은 http(s)만, 내부는 정적 경로만)
_IMG_URL_RE = re.compile(r"^(https?://|/common/|/uploads/|/files/)")
_BTN_URL_RE = re.compile(r"^(https?://|/|#|mailto:)")

# ============================================================
# 기본 시드 — 네비: 회사소개 첫 링크 / 교육기관 찾기 / 역할별포털 없음
# ※ DEFAULT 는 구형 sections 형식 그대로 두고, 시드/조회/저장 시 blocks 로 변환된다.
# ============================================================
DEFAULT_SITE_CONTENT = {
    "nav": [
        {"title": "회사소개", "url": "/pages/company.html"},
        {"title": "교육기관 찾기", "url": "/pages/find-academy.html"},
        {"title": "가이드 영상", "url": "/pages/guide-videos.html"},
        {"title": "파트너십", "url": "/pages/partnership.html"},
        {"title": "문의하기", "url": "/pages/contact.html"},
    ],
    "footer_links": [
        {"title": "회사소개", "url": "/pages/company.html"},
        {"title": "이용약관", "url": "/pages/policy.html?tab=terms"},
        {"title": "개인정보처리방침", "url": "/pages/policy.html?tab=privacy"},
        {"title": "파트너십", "url": "/pages/partnership.html"},
        {"title": "문의하기", "url": "/pages/contact.html"},
    ],
    "contact": {
        "phone": "1661-0000",
        "email": "partner@nubida.kr",
        "address": "부산광역시 사상구 사상로 349번길 59, 3층",
        "hours": "평일 09:00 ~ 18:00",
        "modal_title": "가맹 · 개원 상담 안내",
        "modal_sub": "누비다 교육센터(직영/프랜차이즈) 운영에 관한 문의는 아래 경로로 접수해 주세요. 본사 담당자가 1:1로 상담해 드립니다.",
        "modal_note": "💡 가입 후 본사 1:1 문의를 이용하시면 지사 정보와 상담 내역을 온라인으로 편리하게 관리할 수 있어요.",
    },
    "pages": {
        "company": {
            "title": "교육의 미래를 여는 기술",
            "eyebrow": "회사소개",
            "hero_image": "/common/assets/design-images/future_korean_education_1779004527860.jpg",
            "hero_alt": "미래 교육 현장",
            "sections": [
                {
                    "h": "누비다플랫폼은",
                    "img": "/common/assets/design-images/ai_learning_platform_ui_1779004560505.jpg",
                    "alt": "누비다 AI 학습 플랫폼 UI",
                    "p": "메이커 코딩 + AI 교육에 특화된 올인원 통합 플랫폼을 만듭니다.\n본사 관리부터 에듀케어(공부방) 운영, 학생 학습, 학부모 모니터링까지 — 교육 사업의 전 과정을 하나의 시스템에서 연결합니다.",
                },
                {
                    "h": "핵심 가치",
                    "img": "/common/assets/design-images/ai_tutor_interaction_1779005503442.jpg",
                    "alt": "AI 튜터 학습 상호작용",
                    "p": "1) 현장 중심 — 원장님과 선생님의 실제 운영 흐름에서 설계를 시작합니다.\n2) 데이터 기반 — 학습·출결·매출 데이터를 한눈에 보고 의사결정합니다.\n3) 지속 혁신 — 아두이노 하드웨어부터 AI 분석까지 새로운 교육 기술을 가장 먼저 만나볼 수 있습니다.",
                },
                {
                    "h": "함께하는 곳",
                    "p": "부산광역시 사상구 사상로 349번길 59, 3층 — 누비다플랫폼 본사.\n직영 · 프랜차이즈 교육센터와 함께 성장하고 있습니다.",
                },
            ],
        },
        "policy": {
            "title": "이용약관 및 개인정보처리방침",
            "eyebrow": "약관 · 정책",
            "sections": [
                {
                    "h": "이용약관",
                    "p": "제1조(목적) 본 약관은 누비다플랫폼(이하 '회사')이 제공하는 교육 통합 플랫폼 서비스의 이용 조건과 절차, 회사와 회원의 권리·의무를 규정함을 목적으로 합니다.\n제2조(회원가입) 서비스 가입은 본 약관에 동의하고 회사가 정한 양식에 따라 가입 신청함으로써 성립합니다. 회사는 심사 후 승인 여부를 통지합니다.\n제3조(서비스 이용) 회원은 본인이 등록한 역할(본사/원장/에듀케어/학생/학부모)에 따라 서비스를 이용할 수 있으며, 플랫폼 내 모든 데이터는 교육 목적으로만 사용되어야 합니다.",
                },
                {
                    "h": "개인정보처리방침",
                    "p": "1) 수집 항목 — 이름, 연락처, 소속 기관 정보, 학습 기록(출결·성적·포트폴리오) 등 서비스 제공에 필요한 최소한의 정보를 수집합니다.\n2) 이용 목적 — 회원 식별, 학습·운영 관리, 상담 응대, 서비스 품질 개선.\n3) 보유 기간 — 회원 탈퇴 또는 보유 목적 달성 시까지. 관계 법령이 정하는 경우 해당 기간 동안 보관합니다.\n4) 문의 — 개인정보 관련 문의는 partner@nubida.kr 로 접수해 주세요.",
                },
            ],
        },
        "partnership": {
            "title": "누비다와 함께 성장할 파트너를 찾습니다",
            "eyebrow": "파트너십",
            "hero_image": "/common/assets/design-images/future_campus_collaboration_1779005540029.jpg",
            "hero_alt": "미래 교육 캠퍼스 협업",
            "sections": [
                {
                    "h": "누비다 교육센터",
                    "img": "/common/assets/design-images/arduino_coding_education_1779007970947.jpg",
                    "alt": "아두이노 코딩 교육 현장",
                    "p": "메이커 코딩 · AI 교육 커리큘럼과 올인원 운영 시스템이 패키지로 제공되는 직영/프랜차이즈 모델입니다.\n개원 준비부터 원생 모집, 수업 운영까지 본사가 함께합니다.",
                },
                {
                    "h": "에듀케어 제휴",
                    "img": "/common/assets/design-images/interactive_digital_textbook_science_1779005523044.jpg",
                    "alt": "인터랙티브 디지털 학습",
                    "p": "기존 공부방 · 교습소에 누비다 커리큘럼과 플랫폼을 도입하는 제휴 모델입니다.\n학습 관리 자동화로 선생님의 행정 부담을 줄이고, 학부모 신뢰를 높입니다.",
                },
                {
                    "h": "지사 파트너",
                    "p": "지역별 교육 콘텐츠 · 하드웨어 공급망을 함께하는 B2B 파트너를 모집합니다.\n개방형 지역 관리(Region) 체계로 지사 고유의 사업 영역을 보장합니다.",
                },
            ],
        },
        "contact": {
            "title": "궁금한 점을 남겨 주세요",
            "eyebrow": "문의하기",
            "hero_image": "/common/assets/design-images/debugging_future_education_1779007597825.jpg",
            "hero_alt": "미래 교육 디버깅",
            "sections": [
                {
                    "h": "이용 문의",
                    "p": "플랫폼 이용 · 계정 · 결제 문의는 로그인 후 본사 1:1 문의를 이용하시면 상담 내역이 온라인으로 보관되어 편리합니다.",
                },
                {
                    "h": "기관 · 사업 문의",
                    "p": "개원, 제휴, 지사 파트너십 문의는 아래 연락처로 접수해 주세요. 영업일 기준 24시간 이내에 회신해 드립니다.",
                },
            ],
        },
    },
}


def sanitize_html(v):
    """저장 전 HTML/스크립트 제거 (제목·본문 등 텍스트 필드)"""
    if isinstance(v, str):
        return re.sub(r"<[^>]*>", "", v).strip()
    return v


def _clean(obj):
    """dict/list 재귀 HTML 제거"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, str):
        return sanitize_html(obj)
    return obj


# ============================================================
# 블록 정규화 (저장 시점 검증 — type 화이트리스트, HTML 제거, URL 검증)
# ============================================================
def _clean_id(v, idx):
    s = v if isinstance(v, str) else ""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s):
        return s
    return f"b{idx + 1}"


def _clean_block(blk, idx):
    """블록 1개 정규화. 허용되지 않은 type/형태면 None"""
    if not isinstance(blk, dict):
        return None
    btype = blk.get("type")
    if btype not in BLOCK_SCHEMA:
        return None
    out = {"id": _clean_id(blk.get("id"), idx), "type": btype}
    for f in BLOCK_SCHEMA[btype]:
        v = blk.get(f)
        if isinstance(v, str):
            v = sanitize_html(v)
            if f in ("img",):
                v = v if _IMG_URL_RE.match(v) else ""
            if f == "url":
                v = v if _BTN_URL_RE.match(v) else "#"
            out[f] = v
        else:
            out[f] = v
    if btype == "heading":
        try:
            out["level"] = min(max(int(out.get("level") or 3), 2), 4)
        except (TypeError, ValueError):
            out["level"] = 3
    if btype == "button":
        if out.get("style") not in ("primary", "outline", "ghost"):
            out["style"] = "primary"
    return out


def _clean_blocks(blocks):
    """블록 배열 정규화 (None 제거, id 연속성 보장)"""
    out = []
    if isinstance(blocks, list):
        for i, blk in enumerate(blocks):
            cb = _clean_block(blk, i)
            if cb is None:
                continue
            # id 중복 방지 (중복이면 재부여)
            ids = {b["id"] for b in out}
            if cb["id"] in ids:
                cb["id"] = f"b{i + 1}"
                while cb["id"] in ids:
                    cb["id"] += "x"
            out.append(cb)
    return out


def _sections_to_blocks(sections):
    """구버전 sections 배열 → section 블록 변환 (이미지 있으면 fig-top 카드)"""
    blocks = []
    if isinstance(sections, list):
        for s in sections:
            if not isinstance(s, dict):
                continue
            b = {"type": "section"}
            for f in ("h", "p", "img", "alt"):
                if s.get(f):
                    b[f] = s[f]
            blocks.append(b)
    return blocks


def _normalize_page(pg):
    """페이지 1개 정규화 — 항상 blocks 배열을 가지도록 (sections 자동 변환)"""
    if not isinstance(pg, dict):
        pg = {}
    hero = pg.get("hero_image")
    hero = hero if (isinstance(hero, str) and _IMG_URL_RE.match(sanitize_html(hero))) else ""
    npg = {
        "title": sanitize_html(pg.get("title")),
        "eyebrow": sanitize_html(pg.get("eyebrow")),
        "hero_image": hero,
        "hero_alt": sanitize_html(pg.get("hero_alt")),
        "blocks": _clean_blocks(pg.get("blocks") if isinstance(pg.get("blocks"), list) else _sections_to_blocks(pg.get("sections"))),
    }
    return npg


def _normalize_pages(pages):
    """pages dict 정규화 (메모리 변환 — 조회/저장 공용)"""
    out = {}
    if isinstance(pages, dict):
        for slug, pg in pages.items():
            out[slug] = _normalize_page(pg)
    return out


# ============================================================
# 조회 / 저장
# ============================================================
async def get_site_content(db: AsyncSession) -> dict:
    """site_content 조회 — 없으면 기본 시드 자동 삽입 후 반환.
    반환 전 pages 를 blocks 형식으로 정규화하므로 호출부는 항상 blocks 를 쓴다."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == KEY))
    row = result.scalar_one_or_none()
    if row and row.value:
        value = row.value
        if isinstance(value, str):  # 과거 문자열 저장 방어
            try:
                value = json.loads(value)
            except Exception:
                value = DEFAULT_SITE_CONTENT
        if isinstance(value, dict) and isinstance(value.get("pages"), dict):
            value["pages"] = _normalize_pages(value["pages"])
        return value
    # lazy seed — 최초 1회 기본 시드 삽입 (blocks 형식으로 저장)
    seed = json.loads(json.dumps(DEFAULT_SITE_CONTENT))
    seed["pages"] = _normalize_pages(seed.get("pages"))
    db.add(AppSetting(key=KEY, value=seed))
    await db.commit()
    return seed


async def get_site_page(db: AsyncSession, slug: str):
    """단일 페이지 조회 (위지윅 에디터용) — 없으면 None"""
    content = await get_site_content(db)
    pages = content.get("pages") if isinstance(content, dict) else None
    if not isinstance(pages, dict):
        return None
    return pages.get(slug)


async def save_site_content(db: AsyncSession, data: dict) -> dict:
    """site_content 전체 저장 — HTML 제거 후 upsert, pages 는 blocks 형식으로 통일 저장.
    payload 에 pages 가 없으면(= settings ①~③ 저장) 기존 페이지 본문을 보존한다.
    페이지 본문(④)은 별도 페이지(site-manager)에서만 수정·저장된다."""
    cleaned = _clean(data or {})
    if not isinstance(cleaned, dict):
        cleaned = {}
    result = await db.execute(select(AppSetting).where(AppSetting.key == KEY))
    row = result.scalar_one_or_none()
    existing = row.value if (row and isinstance(row.value, dict)) else {}
    if isinstance(cleaned.get("pages"), dict):
        cleaned["pages"] = _normalize_pages(cleaned["pages"])
    else:
        # settings(①~③) 저장 → 기존 공개 페이지 본문 보존 (덮어쓰기 방지)
        cleaned["pages"] = existing.get("pages", {})
    if row:
        row.value = cleaned
    else:
        db.add(AppSetting(key=KEY, value=cleaned))
    await db.commit()
    return cleaned


async def save_site_page(db: AsyncSession, slug: str, data: dict) -> dict:
    """단일 페이지 저장 (위지윅 에디터용) — nav/footer/contact 등 다른 영역 보존"""
    content = await get_site_content(db)  # 정규화된 전체
    if not isinstance(content, dict):
        content = {}
    if not isinstance(content.get("pages"), dict):
        content["pages"] = {}
    npg = _normalize_page(data) if isinstance(data, dict) else {"blocks": []}
    content["pages"][slug] = npg
    result = await db.execute(select(AppSetting).where(AppSetting.key == KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = content
    else:
        db.add(AppSetting(key=KEY, value=content))
    await db.commit()
    return npg


# ============================================================
# 공개 페이지 추가 / 삭제 — DB 시드 + 실제 HTML 파일 자동 생성/삭제
# ============================================================
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
PROTECTED_SLUGS = ("company", "policy", "partnership", "contact")
# DB 페이지가 아니면서 같은 주소를 쓰는 정적 파일이 존재하는 슬러그 (충돌 방지)
RESERVED_SLUGS = ("index", "login", "register", "find-id", "find-password", "_img_grid", "find-academy", "guide-videos")
_AUTO_MARK = "<!-- nubida-auto-generated-page:1 -->"

PAGES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "pages"

_PAGE_HTML_TPL = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — 누비다플랫폼</title>
    <meta name="description" content="{title}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Outfit:wght@500;600;700;800&family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/common/css/pages/public-page.css?v=20260908e">
    <link rel="stylesheet" href="/common/css/pages/site-blocks.css?v=20260908e">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
</head>
<body data-site-page="{slug}">
{auto}
    <!-- ===== Navigation ===== -->
    <nav class="nav">
        <div class="nav-left">
            <a href="/" class="nav-logo-text">NUBIDA<span>.</span></a>
        </div>
        <div class="nav-center" id="navCenter"></div>
        <div class="nav-links">
            <a href="/pages/login.html" class="nav-btn nav-start">시작하기</a>
            <button class="nav-burger" id="navBurger" aria-label="메뉴 열기" aria-expanded="false"><span></span><span></span><span></span></button>
        </div>
    </nav>

    <!-- ===== Hero ===== -->
    <header class="page-hero">
        <span class="eyebrow" data-page-eyebrow>{title}</span>
        <h1 data-page-title>{title}</h1>
    </header>

    <!-- ===== 본문 (에디터에서 저장한 블록이 렌더됩니다) ===== -->
    <main class="site-body">
        <div id="pageSections"></div>
    </main>

    <!-- ===== Footer ===== -->
    <footer class="footer">
        <div class="footer-inner">
            <div class="footer-brand">NUBIDA<span>.</span></div>
            <div class="footer-links" id="footerLinks"></div>
        </div>
        <div class="footer-btm">© 2026 누비다플랫폼. All rights reserved.</div>
    </footer>

    <script src="/common/js/site-blocks.js?v=20260908e"></script>
    <script src="/common/js/public-site.js?v=20260908e"></script>
</body>
</html>
"""


def _page_slug_path(slug: str) -> Path:
    return PAGES_DIR / f"{slug}.html"


def _build_page_html(slug: str, title: str) -> str:
    """새 공개페이지 HTML 파일 본문 (동적 주입 구조 + 자동생성 마커)"""
    t = _clean(title) or slug
    return _PAGE_HTML_TPL.format(slug=slug, title=t, auto=_AUTO_MARK)


async def create_site_page(db: AsyncSession, slug: str, title: str = "", desc: str = "") -> dict:
    """새 공개 페이지 생성 — site_content.pages[slug] 시드 + HTML 파일 자동 생성(없을 때만).
    - slug 형식/중복/예약 주소 검증 (ValueError)
    - 반환: {"slug", "file_created"} / file_created=False 면 기존 동적 HTML에 DB 연결만 수행"""
    slug = (slug or "").strip().lower()
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("페이지 주소(slug)는 영문 소문자로 시작하고 영문·숫자·하이픈(-)만 사용할 수 있어요. (최대 40자)")
    if slug in RESERVED_SLUGS:
        raise ValueError(f"사용할 수 없는 페이지 주소입니다: {slug} (기본 제공 주소와 충돌)")
    title = _clean(title) or slug
    content = await get_site_content(db)
    if not isinstance(content, dict):
        content = {}
    pages = content.get("pages") if isinstance(content.get("pages"), dict) else {}
    if slug in pages:
        raise ValueError(f"이미 존재하는 페이지 주소입니다: {slug}")
    content["pages"] = pages

    # 1) HTML 파일 생성 (이미 존재하면: 자동생성/동적 페이지 → 연결만, 그 외 정적 파일 → 충돌)
    fpath = _page_slug_path(slug)
    file_created = False
    if fpath.exists():
        try:
            raw = fpath.read_text("utf-8", errors="ignore")
        except Exception:
            raw = ""
        if _AUTO_MARK not in raw and "data-site-page" not in raw:
            raise ValueError(f"이미 사용 중인 페이지 주소입니다: /pages/{slug}.html (정적 파일과 충돌)")
    else:
        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(_build_page_html(slug, title), "utf-8")
            file_created = True
        except OSError as e:
            raise ValueError(f"페이지 파일 생성 실패: {e}")

    # 2) DB 시드 — 기본 블록 1개(설명) + 에디터 기본값
    blocks = []
    if desc:
        d = _clean(desc)
        if d:
            blocks.append({"type": "text", "p": d})
    pages[slug] = {
        "title": title,
        "eyebrow": title,
        "hero_image": "",
        "hero_alt": "",
        "blocks": blocks,
    }
    content["pages"] = _normalize_pages(pages)
    result = await db.execute(select(AppSetting).where(AppSetting.key == KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = content
    else:
        db.add(AppSetting(key=KEY, value=content))
    await db.commit()
    return {"slug": slug, "file_created": file_created}


async def delete_site_page(db: AsyncSession, slug: str) -> dict:
    """공개 페이지 삭제 — pages[slug] 제거 + 자동생성 HTML 파일 삭제 + nav/footer 링크 정리.
    - 보호 페이지(company/policy/partnership/contact)는 삭제 불가 (ValueError)
    - 반환: {"slug", "removed_links", "file_deleted"}"""
    slug = (slug or "").strip().lower()
    if slug in PROTECTED_SLUGS:
        raise ValueError("기본 제공 페이지(회사소개·약관·파트너십·문의)는 삭제할 수 없습니다.")
    content = await get_site_content(db)
    pages = content.get("pages") if isinstance(content, dict) else None
    if not isinstance(pages, dict) or slug not in pages:
        raise ValueError("페이지를 찾을 수 없습니다.")
    del pages[slug]

    # 1) 연결된 네비/푸터 링크 정리
    removed_links = 0
    ref = "/pages/" + slug + ".html"
    for key in ("nav", "footer_links"):
        arr = content.get(key)
        if isinstance(arr, list):
            kept = []
            for it in arr:
                if isinstance(it, dict) and str(it.get("url") or "").split("?")[0] == ref:
                    removed_links += 1
                else:
                    kept.append(it)
            content[key] = kept

    # 2) 자동생성 HTML 파일만 삭제 (수동 작성 정적 HTML은 보존)
    file_deleted = False
    fpath = _page_slug_path(slug)
    if fpath.exists():
        try:
            raw = fpath.read_text("utf-8", errors="ignore")
        except Exception:
            raw = ""
        if _AUTO_MARK in raw:
            try:
                fpath.unlink()
                file_deleted = True
            except OSError:
                pass

    content["pages"] = _normalize_pages(content.get("pages") or {})
    result = await db.execute(select(AppSetting).where(AppSetting.key == KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = content
    else:
        db.add(AppSetting(key=KEY, value=content))
    await db.commit()
    return {"slug": slug, "removed_links": removed_links, "file_deleted": file_deleted}

