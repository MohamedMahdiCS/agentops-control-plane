# API and worker image. The same image runs `uvicorn`, `alembic` or the worker.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first for layer caching; versions are pinned by uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY backend ./backend
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 agentops \
    && mkdir -p /app/data/benchmarks/runs \
    && chown -R agentops:agentops /app/data

USER agentops

ARG GIT_COMMIT_SHA=""
ENV PATH="/app/.venv/bin:$PATH" \
    APP_ENV=production \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
