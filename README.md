# 2026_Nubida_10M — 누비다 플랫폼 서버 전체 백업

**백업 시점**: 2026-10-08
**출처**: A서버 (`nubidaplet-server`, 공인 121.175.13.55) LIVE 컨테이너에서 직접 추출

---

## ⚠️ 이 백업의 가장 중요한 원칙

**소스는 LIVE 컨테이너에서 `docker cp` 로 직접 추출했습니다.**
호스트 `/home/nubidaplet/docker/` 사본은 **구버전이며 `frontend/` 가 없습니다.**
실제로 `nubida-platform-app`의 `site-manager.html`은 라이브와 호스트 사본의 md5가 달랐습니다
(라이브가 더 최신). 따라서 복원은 **반드시 이 백업(라이브 기준)** 을 사용해야 합니다.

---

## 📦 백업 구성

| 디렉토리 | 내용 | 소스 |
|---|---|---|
| `nubida-platform-app/` | 메인 플랫폼 (FastAPI 백엔드 + 프론트엔드) | `docker cp nubida-platform-app:/app` |
| `music-ai-app/` | 노래 생성 AI (Flask + PyTorch) | `docker cp music-ai-app:/app` |
| `chatai-web-app/` | AI 채팅 (Node.js) | `docker cp chatai-web-app:/app` |
| `shop-web-app/` | 포인트 상점 (Flask) | `docker cp shop-web-app:/app` |
| `_db/db_all.sql` | DB 전체 덤프 (403 테이블, 8 DB) | `mariadb-dump --all-databases` |
| `_server_config/` | Caddyfile, systemd, crontab, 컨테이너/이미지 목록 | 호스트 |
| `_scripts/` | 운영 스크립트 (백업/검증) | 호스트 |
| `RESTORE_복원방법.md` | 복원 절차서 | — |

### ❌ 포함되지 않은 것 (그 이유)
| 제외 항목 | 이유 |
|---|---|
| `uploads/`, `static/assets/uploads/` | 사용자 업로드 데이터 (411MB, 용량) |
| `static/mr/`, `static/models/` | AI 모델·음원 (대용량, 재다운로드 가능) |
| Docker 이미지 (5.3G) | GitHub 100MB 제한. A서버 `/data/hdd/backups/`에 별도 보관 |
| `node_modules/`, `__pycache__/` | 의존성 (재설치 가능) |
| `*.data` (sherpa 158MB) | GitHub 100MB 제한 |
| **DB 실제 데이터** | `db_all.sql` 에는 포함되나, **운영 최신 데이터는 A/B서버 백업 참조** |

---

## 🚨 복원 시 반드시 알아야 할 것 (모르면 데이터·기능 손실)

1. **`/app/app/static/` 은 죽은 트리** — `main.py`에서 `FRONTEND_DIR = ../frontend` 만 서빙.
   프론트 수정·복원은 항상 `frontend/` 대상.

2. **`docker compose up -d` 금지** — 컨테이너 재생성 시 이미지 레이어로 롤백되어
   컨테이너 내부 수정분이 통째로 유실된다. **반드시 `docker restart` 만.**

3. **백엔드 `.py` 수정 후 `docker restart` 필수** — uvicorn이 `--reload` 없이 돌아
   구코드를 유지한다 (신규 엔드포인트가 404로 보임).

4. **미러(B서버)는 별도 DB** — 같은 username이라도 비밀번호 해시가 다름.

5. **설정 파일은 부분 수정만** — `read_file`로 앞만 보고 `write_file`로 덮어쓰면
   뒤쪽 설정이 조용히 삭제된다. 치환 삽입 + `diff` 검증을 사용할 것.

---

## 🔧 복원 절차 (요약)

```bash
# 1) 소스 복원 (컨테이너 생성 후)
docker cp ./nubida-platform-app/. nubida-platform-app:/app/
docker cp ./music-ai-app/.      music-ai-app:/app/
docker cp ./chatai-web-app/.    chatai-web-app:/app/
docker cp ./shop-web-app/.      shop-web-app:/app/

# 2) DB 복원
docker exec -i music-db mariadb -u root -p'***MASKED***' < _db/db_all.sql

# 3) 설정 복원
sudo cp _server_config/Caddyfile /etc/caddy/Caddyfile
crontab _server_config/crontab_nubidaplet.txt

# 4) 재시작 (compose up 금지!)
docker restart nubida-platform-app music-ai-app chatai-web-app shop-web-app
```

---

## 🖥️ 서비스 구성 (2026-10-08 기준)

| 컨테이너 | 포트 | 역할 |
|---|---|---|
| nubida-platform-app | 8005 | 메인 플랫폼 (백엔드+프론트) |
| music-db | 8001 | MariaDB (8개 DB, 403 테이블) |
| music-ai-app | 8004 | 노래 생성 AI |
| shop-web-app | 8003 | 포인트 상점 |
| chatai-web-app | — | AI 채팅 |
| redis-server | — | 세션/캐시 |
| ollama | — | LLM (socat 프록시 → B서버 실제 모델) |

---

## 🔐 보안

- 모든 **비밀번호를 `***MASKED***` 로 치환**했습니다 (12개 파일).
- 커밋 직전 전체 트리 유출 검사 완료 (`grep dbsdudcjf2020` → 0건).
- 권장: 저장소 **Private 유지**, 복원 후 실제 비밀번호는 안전한 곳에서 주입.

---

## 🗂️ 관련 시스템 (Hermes 백업 체계)

| 위치 | 내용 |
|---|---|
| A서버 `/data/hdd/backups/full_*/` | 완전 백업 (이미지 5.3G 포함) |
| B서버 `critical_backups/_from_A/` | 이 백업의 사본 (교차 백업) |
| A→B 교차 백업 | 매주 일 06:00 자동 |
| 검증 스크립트 | A `scripts/verify_backup.sh`, B `~/verify_backup_B.sh` |

**한 서버가 완전히 죽어도 다른 서버 백업으로 복원 가능합니다.**

---

*이 백업은 Hermes Agent가 윤비스님 지시로 생성했습니다. 상세 문의: 서버 관리자.*
