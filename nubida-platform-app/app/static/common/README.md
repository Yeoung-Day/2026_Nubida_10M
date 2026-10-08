# 누비다플랫폼 CSS 구조 v6.0

## 📁 디렉토리 구조

```
common/css/
├── reset.css                — CSS 초기화 (Normalize)
├── variables.css            — 디자인 토큰 (색상, 간격, 폰트, 그림자)
├── common.css               — 공통 레이아웃 (베이스, 사이드바, 본문, 유틸리티)
├── responsive.css           — 모바일/태블릿 반응형 (모바일 퍼스트)
│
├── components/              — 재사용 가능한 UI 컴포넌트
│   ├── animations.css       — 애니메이션 (@keyframes + 유틸리티 클래스)
│   ├── badges.css           — 배지/태그 (상태 표시)
│   ├── buttons.css          — 버튼 (primary/secondary/outline/ghost/danger)
│   ├── cards.css            — 카드 (stat-card, card, gallery, hover-lift)
│   ├── forms.css            — 폼/입력 (input, select, textarea, search-bar)
│   ├── modals.css           — 모달 (overlay, modal, 애니메이션)
│   ├── tables.css           — 테이블 (data-table, wrapper)
│   └── tabs.css             — 탭/필터 (filter-tab pill 스타일)
│
├── features/                — 기능별 스타일 (여러 페이지에서 사용)
│   ├── arduino.css          — 아두이노 코드 에디터
│   ├── audit.css            — 감사 로그
│   ├── chat.css             — 채팅 (실시간 메시지, 말풍선)
│   ├── notifications.css    — 알림/푸시 알림
│   └── progress.css         — 학습 진도
│
└── pages/                   — 역할별 페이지 스타일
    ├── branch/
    │   └── style.css        — 지사 페이지 전용
    ├── director/
    │   └── style.css        — 원장 페이지 전용
    ├── headquarters/
    │   └── style.css        — 본사 페이지 전용
    ├── landing.css          — 랜딩 페이지 (index.html) 전용
    ├── parent/
    │   └── style.css        — 학부모 페이지 전용
    ├── platform/
    │   └── style.css        — 플랫폼 관리 페이지 전용
    └── student/
        └── style.css        — 학생 페이지 전용
```

## 📋 CSS 로드 순서 (권장)

### 모든 페이지 공통
```html
<link rel="stylesheet" href="/common/css/reset.css?v=20260525a">
<link rel="stylesheet" href="/common/css/variables.css?v=20260525a">
<link rel="stylesheet" href="/common/css/common.css?v=20260525a">
<link rel="stylesheet" href="/common/css/responsive.css?v=20260525a">
<link rel="stylesheet" href="/common/css/components/animations.css?v=20260525a">
```

### 역할별 페이지 스타일
```html
<link rel="stylesheet" href="/common/css/pages/headquarters/style.css?v=20260525a">
```

### 기능별 스타일 (해당 페이지에서만)
```html
<!-- 채팅 페이지 -->
<link rel="stylesheet" href="/common/css/features/chat.css?v=20260525a">

<!-- 아두이노 에디터 페이지 -->
<link rel="stylesheet" href="/common/css/features/arduino.css?v=20260525a">
```

## 🧩 컴포넌트 사용 가이드

### 새 페이지를 만들 때 필요한 CSS
1. **공통 5개:** reset + variables + common + responsive + animations
2. **역할 스타일:** pages/{role}/style.css
3. **컴포넌트:** 필요한 것만 추가 (buttons.css, cards.css 등)
4. **기능:** 해당하는 기능 스타일 (chat.css, arduino.css 등)

### 컴포넌트별 용도
| 파일 | 주요 클래스 | 사용 페이지 |
|------|------------|-----------|
| buttons.css | .btn, .btn-primary, .btn-secondary | 모든 페이지 |
| cards.css | .card, .stat-card, .gallery-card | 대시보드, 통계 |
| forms.css | .form-input, .form-select, .form-textarea | 설정, 등록 |
| tables.css | .data-table, .table-wrapper | 사용자 목록, 결제 |
| badges.css | .badge, .badge-success, .badge-danger | 상태 표시 |
| modals.css | .modal-overlay, .modal | 팝업, 확인창 |
| tabs.css | .filter-tabs, .filter-tab | 필터, 탭 UI |
| animations.css | .animate-fade-in, .animate-fade-up | 페이지 진입 효과 |

## 🔄 마이그레이션 (v5 → v6)

CSS 구조를 변경한 후 캐시를 갱신하려면:
1. `service-worker.js`의 `STATIC_CACHE` 버전 번호 증가
2. 모든 HTML의 CSS `v=20260525a` 쿼리스트링 업데이트
3. 사용자 브라우저에서 `Ctrl+Shift+R` (강력 새로고침)

## 📝 주석 규칙

모든 CSS 파일은 다음 규칙을 따릅니다:
- **파일 상단:** 파일 설명, 최종 수정일
- **각 섹션:** `/* ── 섹션 이름 ── */` 형식의 한글 주석
- **!important 사용 시:** 반드시 사유를 주석으로 표기
