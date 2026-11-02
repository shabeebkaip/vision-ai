# Edge runtime image (task HW-04, first version): x86-64, CPU or NVIDIA GPU via onnxruntime.
# Jetson (arm64, JetPack 6) gets its own image on the L4T base in HW-04 proper.
#
#   docker build -f deploy/edge/Dockerfile -t codeox/vision-edge:dev .
#   docker run --rm -v $PWD/site.yaml:/config/site.yaml:ro -v vision-data:/var/lib/vision \
#       codeox/vision-edge:dev run /config/site.yaml --camera cam1 --detector onnx --model /models/rfdetr-nano.onnx
#
# EDGE_EXTRAS=rfdetr adds RF-DETR + PyTorch for CPU inference in development (large image; the dev
# compose stack builds this). Leave it empty for the production-shaped ONNX image.
FROM python:3.11-slim-bookworm

ARG EDGE_EXTRAS=""

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    VISION_OUTBOX_DIR=/var/lib/vision/outbox \
    VISION_LOG_JSON=true \
    RF_HOME=/var/lib/vision/cache/rfdetr \
    HF_HOME=/var/lib/vision/cache/hf \
    TORCH_HOME=/var/lib/vision/cache/torch

WORKDIR /app
# Workspace manifests first so dependency layers are cached between code changes.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY edge/pyproject.toml edge/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
COPY cloud/pyproject.toml cloud/pyproject.toml
RUN mkdir -p shared/src/vision_shared edge/src/vision_edge ml/src/vision_ml \
    && touch shared/src/vision_shared/__init__.py edge/src/vision_edge/__init__.py ml/src/vision_ml/__init__.py \
    && uv sync --frozen --no-dev --package vision-edge --no-install-workspace \
        ${EDGE_EXTRAS:+--extra $EDGE_EXTRAS}

COPY shared/ shared/
COPY edge/ edge/
RUN uv sync --frozen --no-dev --package vision-edge ${EDGE_EXTRAS:+--extra $EDGE_EXTRAS}

RUN useradd --system --uid 10001 --home-dir /var/lib/vision vision \
    && mkdir -p /var/lib/vision/outbox /models /config \
    && chown -R vision /var/lib/vision
USER vision
VOLUME ["/var/lib/vision"]

ENTRYPOINT ["tini", "--", "vision-edge"]
CMD ["--help"]
