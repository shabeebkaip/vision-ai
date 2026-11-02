# Code-Ox Vision cloud API image (REP-05 partial, CLD-20 later).
# Build from the repository root:  docker build -f deploy/cloud.Dockerfile -t codeox/vision-cloud .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
# The uv workspace needs every member's pyproject.toml; only shared/ and cloud/ are installed.
COPY pyproject.toml uv.lock README.md ./
COPY edge/pyproject.toml edge/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
COPY shared shared
COPY cloud cloud
RUN uv sync --frozen --no-dev --package vision-cloud

RUN useradd --system --uid 10001 vision
USER vision
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["vision-cloud", "serve", "--host", "0.0.0.0", "--port", "8000"]
