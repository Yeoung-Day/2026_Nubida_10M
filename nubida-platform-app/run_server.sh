#!/bin/bash
# Nubida Platform Server - Python 3.11 직접 실행 (--reload 없음)
export PYTHONPATH=/root/shared/nubida-platform/backend/venv/lib/python3.11/site-packages:/root/shared/nubida-platform/backend
cd /root/shared/nubida-platform/backend
exec /root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn_final.log 2>&1
