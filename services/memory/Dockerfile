# Single image for both the API (web) and the worker — the start command differs
# per Render service. Uses uv for fast, reproducible installs.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Build context is services/ (see infra compose files) so the ChatGPT plugin
# package can sit beside memory on PYTHONPATH.
COPY memory/pyproject.toml memory/uv.lock ./
RUN uv sync --frozen --no-dev

COPY memory/ .
COPY chatgpt-plugin /chatgpt-plugin
COPY claude-plugin /claude-plugin
# /app too: the plugin services run `uvicorn --app-dir /<plugin>`, which puts that
# directory on sys.path instead of the working directory, so `import app` needs /app here.
# The Claude plugin reuses the ChatGPT plugin's tool modules, so both stay on the path.
ENV PYTHONPATH="/chatgpt-plugin:/claude-plugin:/app"

# Default command (API). Render's worker service overrides this via render.yaml.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
