FROM python:3.10-slim
WORKDIR /app

# 이 부분이 Dockerfile 안에 들어가 있어야 합니다.
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask flask-cors torch torchaudio mysql-connector-python gunicorn
RUN pip install --no-cache-dir flask flask-cors torch torchaudio mysql-connector-python gunicorn redis

COPY . .

CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
