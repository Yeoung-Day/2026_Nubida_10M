# 🔄 복원 방법 (A서버)

이 백업은 **2026-10-08 현재 상태 그대로** 복원하기 위한 것입니다.

## 백업 구성
| 파일 | 내용 |
|---|---|
| `sources_docker.tar.gz` | 모든 소스코드 (프론트/백엔드/JS) |
| `sources_acestep.tar.gz` | 노래AI 소스 |
| `system/Caddyfile` | Caddy 도메인 라우팅 |
| `system/hermes-gateway.service` | 자동시작 서비스 |
| `system/crontab_nubidaplet.txt` | cron 작업 |
| `db_all.sql` | DB 전체 (403 테이블) |
| `uploads.tar.gz` | 사용자 업로드 파일 |
| `data_music.tar.gz` | 노래AI 음악 산출물 |
| `docker_containers.txt` | 컨테이너 구성 |
| `docker_images.txt` | 이미지 목록 |

## 복원 절차
```bash
BK=/data/hdd/backups/full_XXXXXXXX

# 1) 소스 복원
cd / && tar -xzf $BK/sources_docker.tar.gz
cd / && tar -xzf $BK/sources_acestep.tar.gz

# 2) 설정 복원
sudo cp $BK/system/Caddyfile /etc/caddy/Caddyfile
sudo cp $BK/system/hermes-gateway.service /etc/systemd/system/
crontab $BK/system/crontab_nubidaplet.txt

# 3) DB 복원
docker exec -i music-db mariadb -u root -p'***MASKED***' < $BK/db_all.sql

# 4) 업로드 파일 복원
docker run --rm -v nubida-platform_nubida-platform-uploads:/data -v $BK:/backup alpine \
  tar -xzf /backup/uploads.tar.gz -C /data

# 5) 데이터 복원
cd / && tar -xzf $BK/data_music.tar.gz

# 6) 재시작
sudo systemctl reload caddy
docker restart nubida-platform-app music-ai-app chatai-web-app shop-web-app
```
