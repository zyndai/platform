# Single image for both the API (web) and the worker — the start command differs
# per Render service. Uses uv for fast, reproducible installs.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first (layer cache) — prod deps only, no dev/test tools.
COPY pyproject.toml ./
RUN uv sync --no-dev

COPY . .

# Default command (API). Render's worker service overrides this via render.yaml.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
