"""
pending_approvals DB 유틸리티 — 승인 전 사용자(branch_admin/director) 관리
- 운영(MySQL) / 개발·미러(SQLite)를 DATABASE_URL로 자동 감지해 동일 인터페이스 제공
- SQLite 폴백: 미러 VM(MySQL 없음)에서도 원장/에듀케어 가입 → 본사 승인 E2E 가능 (9/7)
- 신규 가입자의 학원명/에듀케어명(branch_name) 저장 — 승인 시 Branch/Academy 자동생성 name 우선 사용
"""
import os
from datetime import datetime


# ============================================================
# 엔진 판별 / 커넥션
# ============================================================

def _db_url():
    try:
        from app.core.config import settings
        return settings.DATABASE_URL
    except Exception:
        return os.environ.get("DATABASE_URL", "")


def _is_sqlite():
    return _db_url().startswith("sqlite")


def _sqlite_path():
    # sqlite+aiosqlite:////dev/shm/nubida_final.db  →  /dev/shm/nubida_final.db
    url = _db_url()
    path = url.split("///", 1)[-1]
    return path or "/dev/shm/nubida_final.db"


class _SqliteCursor:
    """sqlite3 cursor 래퍼 — pymysql DictCursor처럼 dict 행 반환, %s → ? 자동 치환, with 지원"""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        return self._cur.execute(sql.replace('%s', '?'), params or ())

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass  # 실제 close는 커넥션에서


class _SqliteConn:
    def __init__(self, path):
        import sqlite3
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def cursor(self):
        return _SqliteCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_pending_conn():
    """pending_approvals 연결 반환 (DATABASE_URL 기준 SQLite/MySQL 자동 분기)"""
    if _is_sqlite():
        conn = _SqliteConn(_sqlite_path())
    else:
        import pymysql
        DB_CONFIG = {
            "host": os.environ.get("DB_HOST", "localhost"),
            "port": int(os.environ.get("DB_PORT", "3306")),
            "user": os.environ.get("DB_USER", "nubida"),
            "password": os.environ.get("DB_PASSWORD", "nubida1234"),
            "database": os.environ.get("DB_NAME", "nubida_platform"),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }
        conn = pymysql.connect(**DB_CONFIG)
    _ensure_schema(conn)
    return conn


# ============================================================
# 스키마 보장 (테이블 생성 + branch_name 컬럼 백필, 1회만)
# ============================================================

_schema_checked = False


def _ensure_schema(conn):
    global _schema_checked
    if _schema_checked:
        return
    cur = conn.cursor()
    if _is_sqlite():
        cur.execute(
            '''CREATE TABLE IF NOT EXISTS pending_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(50) NOT NULL,
                phone VARCHAR(20),
                role VARCHAR(20) NOT NULL DEFAULT 'student',
                branch_id INTEGER,
                director_id INTEGER,
                registration_code VARCHAR(7) DEFAULT '',
                academy_type VARCHAR(30) DEFAULT '',
                region VARCHAR(50) DEFAULT '',
                branch_name VARCHAR(100) DEFAULT '',
                requested_at DATETIME,
                status VARCHAR(20) DEFAULT 'pending'
            )'''
        )
    else:
        cur.execute(
            '''CREATE TABLE IF NOT EXISTS pending_approvals (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(50) NOT NULL,
                phone VARCHAR(20),
                role VARCHAR(20) NOT NULL DEFAULT 'student',
                branch_id INT,
                director_id INT,
                registration_code VARCHAR(7) DEFAULT '',
                academy_type VARCHAR(30) DEFAULT '',
                region VARCHAR(50) DEFAULT '',
                branch_name VARCHAR(100) DEFAULT '',
                requested_at DATETIME,
                status VARCHAR(20) DEFAULT 'pending'
            )'''
        )
    # 구버전 스키마 보정 — branch_name 컬럼 부재 시 추가 (ALTER 권한 없으면 무시)
    try:
        if _is_sqlite():
            cur.execute("PRAGMA table_info(pending_approvals)")
            cols = [r["name"] for r in cur.fetchall()]
        else:
            cur.execute("SHOW COLUMNS FROM pending_approvals")
            cols = [r["Field"] for r in cur.fetchall()]
        if "branch_name" not in cols:
            cur.execute("ALTER TABLE pending_approvals ADD COLUMN branch_name VARCHAR(100) DEFAULT ''")
    except Exception:
        pass  # 운영 DB에 ALTER 권한이 없는 경우 등 — 기존 동작 유지
    conn.commit()
    _schema_checked = True


# ============================================================
# CRUD
# ============================================================

def add_pending_user(username, email, password_hash, name, phone, role,
                     branch_id=None, director_id=None, registration_code=None,
                     academy_type='', region='', branch_name=''):
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute(
                '''INSERT INTO pending_approvals
                   (username, email, password_hash, name, phone, role, branch_id, director_id,
                    registration_code, academy_type, region, branch_name, requested_at, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')''',
                (username, email, password_hash, name, phone, role, branch_id, director_id,
                 registration_code or '', academy_type or '', region or '', branch_name or '',
                 datetime.utcnow().isoformat())
            )
        conn.commit()
        user_id = c.lastrowid
    finally:
        conn.close()
    return user_id


def get_pending_user(user_id):
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute('SELECT * FROM pending_approvals WHERE id = %s AND status = %s', (user_id, 'pending'))
            row = c.fetchone()
    finally:
        conn.close()
    return row


def get_all_pending_users(status='pending'):
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute('SELECT * FROM pending_approvals WHERE status = %s ORDER BY requested_at DESC', (status,))
            rows = c.fetchall()
    finally:
        conn.close()
    return rows


def delete_pending_user(user_id):
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute('UPDATE pending_approvals SET status = %s WHERE id = %s', ('rejected', user_id))
            c.execute('DELETE FROM pending_approvals WHERE id = %s', (user_id,))
        conn.commit()
    finally:
        conn.close()


def approve_pending_user(user_id):
    """pending_approvals에서 사용자 정보를 가져와 반환 (메인 DB 저장은 호출자가 처리)"""
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute('SELECT * FROM pending_approvals WHERE id = %s AND status = %s', (user_id, 'pending'))
            row = c.fetchone()
            if not row:
                return None
            user_data = dict(row)
            # 승인일시도 함께 기록 (감사 추적)
            c.execute(
                'UPDATE pending_approvals SET status = %s, approved_at = %s WHERE id = %s',
                ('approved', datetime.utcnow().isoformat(), user_id)
            )
        conn.commit()
        return user_data
    finally:
        conn.close()


def mark_pending_approved(user_id):
    """pending 레코드에 승인일시를 기록 (approved_at). 메인 DB 저장 성공 후 호출."""
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute(
                'UPDATE pending_approvals SET approved_at = %s WHERE id = %s',
                (datetime.utcnow().isoformat(), user_id)
            )
        conn.commit()
    finally:
        conn.close()


def pending_user_count():
    conn = get_pending_conn()
    try:
        with conn.cursor() as c:
            c.execute('SELECT COUNT(*) as cnt FROM pending_approvals WHERE status = %s', ('pending',))
            row = c.fetchone()
            count = row['cnt'] if row else 0
    finally:
        conn.close()
    return count
