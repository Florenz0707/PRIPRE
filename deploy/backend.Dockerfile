FROM ghcr.io/astral-sh/uv:0.9.24 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/src ./backend/src
COPY config ./config
COPY scripts/verify_installed.py /tmp/verify_installed.py
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_CONCURRENT_DOWNLOADS=1 UV_HTTP_TIMEOUT=20 UV_HTTP_RETRIES=1 \
    uv sync --locked --no-dev --no-editable --reinstall-package pripre \
    && /app/.venv/bin/python /tmp/verify_installed.py \
    && useradd --uid 10001 --create-home app
USER app
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "pripre.api:app", "--host", "0.0.0.0", "--port", "8000"]
