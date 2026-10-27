FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app.py .
# Host networking (see ../docker-compose.yml): binds loopback only, Caddy fronts it.
CMD ["uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8200"]
