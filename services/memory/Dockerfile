# Single image for both the API (web) and the worker — the start command differs
# per Render service. Uses uv for fast, reproducible installs.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first (layer cache) — prod deps only, no dev/test tools.
# uv.lock is copied alongside pyproject.toml and the install is --frozen: without
# the lockfile, `uv sync` re-resolves from pyproject.toml (which allows newer
# versions than the pin) and a lock-only change never invalidates this layer,
# so the pinned dependency set never reaches the containers.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Default command (API). Render's worker service overrides this via render.yaml.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
