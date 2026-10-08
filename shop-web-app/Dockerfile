FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# SATA SSD 연결 폴더 권한 부여
RUN chmod -R 777 /app/static/uploads
EXPOSE 5000
CMD ["python", "app.py"]
