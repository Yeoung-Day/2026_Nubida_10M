from pathlib import Path
import secrets
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "누비다플랫폼 통합 공부방 교육 시스템"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "mysql+aiomysql://nubida:nubida1234@localhost:3306/nubida_platform?charset=utf8mb4"
    # PostgreSQL: "postgresql+asyncpg://user:pass@localhost:5432/nubida"

    # Security
    # Reads SECRET_KEY from the environment if set; otherwise generates a
    # cryptographically random key at startup (secrets.token_urlsafe).
    # NOTE: a runtime-generated value changes across restarts and would
    # invalidate any signed tokens/sessions. Set SECRET_KEY in the
    # environment for a persistent key in production.
    SECRET_KEY: str = secrets.token_urlsafe(48)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Uploads
    UPLOADS_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "uploads")

    # PWA Push Notifications (VAPID)
    VAPID_PUBLIC_KEY: str = "BOE8iz8M_ILmORAYbkF-60QG11L_wFARe5RLHgQdg5L3Mec5VbWCbsCy0553ki7x7J5DJZz3EsxYQc36gYL2dIA"
    VAPID_PRIVATE_KEY: str = "7wGGfOeiH5ZQ5VzKd_T7dBQFuNx3lw_XYFa5gfsg3as"
    VAPID_CLAIM_EMAIL: str = "admin@nubida.com"

    # ── 네이티브 앱 푸시 (FCM / APNs) ──
    # FCM (Android) — Firebase 서비스 계정. JSON 문자열 또는 파일 경로 중 하나.
    FCM_CREDENTIALS_JSON: str = ""                                   # 서비스 계정 JSON (문자열)
    FCM_CREDENTIALS_FILE: str = ""                                   # 또는 파일 경로 (.json)
    # APNs (iOS) — Apple Developer .p8 키
    APNS_KEY_ID: str = ""                                            # Key ID (예: ABC123DEFG)
    APNS_TEAM_ID: str = ""                                           # Team ID
    APNS_KEY_FILE: str = ""                                          # .p8 파일 경로
    APNS_BUNDLE_ID: str = "kr.nubida.app"
    APNS_USE_SANDBOX: bool = False                                   # 개발 중 True

    # 누비다 AI — LLM 설정 (Ollama)
    LLM_BASE_URL: str = "http://ollama:11434/v1"
    LLM_MODEL: str = "qwen3:8b"
    LLM_TIMEOUT: int = 180
    LLM_EMBED_MODEL: str = "bge-m3"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
