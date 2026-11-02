# Edge service image for development and the office demo (REP-05).
# Build context is the repository root:
#   docker build -f deploy/edge/Dockerfile --build-arg EDGE_EXTRAS=rfdetr -t codeox/vision-edge:dev .
# EDGE_EXTRAS=rfdetr adds RF-DETR + PyTorch (CPU inference, large image). Leave it empty for a slim
# image that runs the ONNX detector or replayed detections. Production Jetson images are HW-* tasks.
FROM python:3.11-slim-bookworm

ARG EDGE_EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# ffmpeg: H.264 event clips (vision_edge.media). Run with `init: true` (compose) for signal handling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app
# Dependencies first so code changes do not reinstall PyTorch.
COPY pyproject.toml uv.lock README.md ./
COPY shared/pyproject.toml shared/
COPY edge/pyproject.toml edge/
COPY ml/pyproject.toml ml/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package vision-edge \
        ${EDGE_EXTRAS:+--extra $EDGE_EXTRAS}

COPY shared/ shared/
COPY edge/ edge/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package vision-edge ${EDGE_EXTRAS:+--extra $EDGE_EXTRAS}

RUN useradd --create-home --uid 10001 vision && mkdir -p /data && chown vision /data
USER vision
WORKDIR /data
ENV VISION_OUTBOX_DIR=/data/outbox \
    VISION_LOG_JSON=true \
    HF_HOME=/data/cache/hf \
    TORCH_HOME=/data/cache/torch \
    RF_HOME=/data/cache/rfdetr

ENTRYPOINT ["vision-edge"]
CMD ["--help"]
