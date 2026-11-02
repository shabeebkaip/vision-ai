# Build from the repository root:  docker build -f cloud/Dockerfile -t codeox/vision-cloud .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Workspace metadata: every member's pyproject must exist for the lock file to resolve.
COPY pyproject.toml uv.lock README.md ./
COPY shared shared
COPY cloud cloud
COPY edge/pyproject.toml edge/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
RUN uv sync --frozen --no-dev --package vision-cloud --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 vision
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 VISION_LOG_JSON=true
USER vision
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
# Run `vision-cloud migrate` as a one-off step on deploy (CLD-20), then start the API.
CMD ["vision-cloud", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
