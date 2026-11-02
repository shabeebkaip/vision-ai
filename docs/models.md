# AI models: what we use, what we avoid, and why

_Checked 2 November 2026. Re-check licences before every model release (ML-11)._

## Decisions

| Use | Model | Licence | Status |
| --- | --- | --- | --- |
| Live detection on edge boxes | **RF-DETR Nano / Small** (`rfdetr`, COCO weights), exported to ONNX / TensorRT | Apache-2.0 code and weights | Default. `vision-edge --detector rfdetr-nano` in development, `onnx` in production |
| Larger sites, more accuracy | RF-DETR Medium / Large | Apache-2.0 | Allowed |
| Backup detector | D-FINE (`ustc-community/dfine-*` via transformers) | Apache-2.0 | Allowed, not wired yet |
| Fine-tuned PPE, hairnet, forklift (V1) | RF-DETR Small fine-tuned on our data | Apache-2.0 base; our weights are ours | Phase 7 |
| Tracking | Our own ByteTrack-style tracker (`edge/src/vision_edge/tracking.py`) | Ours | See ADR 007 |
| AI second opinion (cloud) | Claude Haiku via API; self-hosted Qwen3-VL 2B/8B later | API terms / Apache-2.0 | Phase 4 (CLD-12) |
| Offline second opinion on the edge | SmolVLM2 (256M–2.2B) | Apache-2.0 | Later, hospital / government sites |
| Auto-labelling (dev only) | Grounding DINO, Florence-2 (`florence-community/Florence-2-base`, no remote code) | Apache-2.0 / MIT | Phase 7 |

**Never ship:** Ultralytics YOLO (AGPL-3.0), RF-DETR Atto/Femto/Pico/XL/2XL (`rfdetr-plus`, PML-1.0: needs a Roboflow paid licence for self-hosting), YOLO-NAS weights (non-commercial), YOLO-World (GPL-3.0), DEIMv2 (custom licence). `scripts/licence_check.py` blocks all of them in CI.

## Practical notes

- **Python versions.** onnxruntime 1.31 has no Python 3.10 wheels and torch 2.15 / transformers 5 need 3.11+. Development uses 3.11+; Jetson boxes (JetPack 6, Python 3.10) use NVIDIA's own onnxruntime-gpu / TensorRT builds, so the edge code stays 3.10-compatible.
- **No CPU-only torch on PyPI for Linux.** PyPI's torch wheel carries CUDA libraries (about 3 GB). On laptops without a GPU, install CPU torch from download.pytorch.org, or skip torch and run the exported ONNX model.
- **Mirror the weights.** RF-DETR weights download from `storage.googleapis.com/rfdetr/` (moving to `repo.roboflow.com/rfdetr/`). Keep our own copy in our object storage and verify the md5 values below before every build.
- **Hugging Face is not needed for RF-DETR inference**; the DINOv2 backbone is only fetched when training from scratch without an RF-DETR checkpoint.

## Full check (licences, versions, weight URLs, sources)

### Summary table

| Model / package | Version (2026-11-02) | Code licence | Weights licence | Weights host | Smallest useful variant | Verdict |
|---|---|---|---|---|---|---|
| rfdetr: N / S / M / L detection, Seg N–2XL, Keypoint preview | 1.11.2 (PyPI, 2026-10-04) | Apache-2.0 | Apache-2.0 | storage.googleapis.com/rfdetr/... (main branch is moving to repo.roboflow.com/rfdetr/...) | Nano: 30.5M params, 384px (file size not verified, about 120 MB fp32 estimated) | **SHIP** |
| rfdetr-plus: Atto / Femto / Pico / XL / 2XL detection | rfdetr-plus 1.1.0 (XL/2XL). Atto/Femto/Pico exist only on rf-detr main (1.12.0.dev), not yet released | PML-1.0 | PML-1.0 (needs a Roboflow plan; commercial self-hosting needs the Enterprise add-on) | storage.googleapis.com/rfdetr/platform-licensed/... | Atto: 7.4M params, 380px | **AVOID** (unless we buy Roboflow Enterprise) |
| supervision | 0.31.3 (2026-10-28) | MIT | n/a (no weights) | n/a | n/a | **SHIP** (note: `sv.ByteTrack` was removed in 0.31.0) |
| trackers (Roboflow) | 2.6.1 (2026-09-25) | Apache-2.0 | n/a (no weights found in the package) | n/a | n/a | **SHIP** |
| D-FINE (`ustc-community/dfine-*`) via transformers | transformers 5.22.1; D-FINE needs ≥4.52 | Apache-2.0 (transformers and upstream Peterande/D-FINE) | Apache-2.0 (all 13 ustc-community checkpoints) | huggingface.co | dfine-nano-coco: 15.3 MB safetensors | **SHIP** |
| RT-DETRv2 (`PekingU/rtdetr_v2_*`) via transformers | needs transformers ≥4.49 | Apache-2.0 (upstream lyuwenyu/RT-DETR as well) | Apache-2.0 (r18vd/r34vd/r50vd/r101vd) | huggingface.co | rtdetr_v2_r18vd: 80.9 MB safetensors | **SHIP** |
| Florence-2-base | microsoft repo last modified 2025-08-04; native in transformers ≥4.56 | MIT | MIT | huggingface.co | base: 463 MB safetensors (about 0.23B params) | **SHIP** (use `florence-community/Florence-2-base` natively; avoid the `trust_remote_code` path) |
| SmolVLM2 | 2.2B-Instruct last modified 2025-04-08; needs transformers ≥4.50 | Apache-2.0 | Apache-2.0 (256M / 500M / 2.2B) | huggingface.co | SmolVLM2-256M-Video-Instruct: 1.03 GB fp32 safetensors | **SHIP** |
| Qwen3-VL 2B / 4B / 8B | needs transformers ≥4.57 | Apache-2.0 (QwenLM/Qwen3-VL) | Apache-2.0 (all 40 Qwen/Qwen3-VL-* repos, including FP8 and GGUF) | huggingface.co | Qwen3-VL-2B-Instruct: 4.26 GB bf16 (FP8 and GGUF variants also exist) | **SHIP** (needs a GPU edge box) |
| Grounding DINO (original, IDEA-Research) | in transformers since ≤4.40 | Apache-2.0 | Apache-2.0 (grounding-dino-tiny / -base) | huggingface.co | grounding-dino-tiny: 689 MB safetensors | **SHIP** (in practice DEV-ONLY: too slow for real-time; best for auto-labelling) |
| onnxruntime / onnxruntime-gpu | 1.31.1 / 1.31.1 (2026-10-26) | MIT | n/a | n/a | CPU wheel 23.8 MB; GPU wheel 255.6 MB (Linux x86_64) | **SHIP** |
| torch | 2.15.0 (2026-10-28) | BSD-style (SPDX: Apache-2.0 AND BSD-3-Clause AND MIT AND …) | n/a | n/a | Linux x86_64 PyPI wheel 539 MB, about 3.0 GB with CUDA 13 deps | **SHIP** (but prefer ONNX Runtime on edge) |
| ultralytics (YOLOv8/11/26) | 8.4.198 (2026-11-02) | AGPL-3.0 | AGPL-3.0 (Enterprise licence sold separately) | github.com/ultralytics/assets/releases | n/a | **AVOID** (banned) |

### Notes per model

### 1. RF-DETR (`rfdetr`)
- **Version:** 1.11.2 on PyPI (uploaded 2026-10-04). GitHub main is at `1.12.0.dev` (commit 7cd8f7c, 2026-11-02).
- **Code licence:** Apache-2.0 (`rfdetr-1.11.2.dist-info/licenses/LICENSE`, PyPI classifier "Apache Software License").
- **Which sizes use which licence** (README in the 1.11.2 wheel, plus main-branch README and `docs/snippets/license-rfdetr.md`):
  - **Apache-2.0:** detection Nano, Small, Medium and Large (also Base and the older Large); **every Seg size from Nano to 2XLarge** (Seg-XL and Seg-2XL are Apache, unlike detection XL/2XL); Keypoint (Preview).
  - **PML-1.0:** detection **Atto, Femto, Pico, XL and 2XL**, plus RF-DETR NAS models. These ship only in `rfdetr[plus]`, which installs the `rfdetr_plus` package.
  - Main-branch README: "commercial use is included when you deploy on Roboflow; commercial self-hosting requires the Enterprise add-on."
  - The PML-1.0 text (from the `rfdetr_plus-1.1.0` wheel) says you may only use it under a separate Roboflow "Platform Agreement", and the licence stops if your account is not in good standing. **This is not acceptable for edge boxes at customer sites unless we buy Roboflow Enterprise.**
- **Atto / Femto / Pico:** none of these appear in the released `rfdetr` 1.11.2 or `rfdetr-plus` 1.1.0 wheels. They exist only on rf-detr main (README table: Atto 7.4M params, 380px, 30.5 AP; Femto 7.9M, 384px, 37.8 AP; Pico 8.4M, 560px, 41.6 AP; all PML 1.0). Their backbone is PE-Core-T. Weight URLs for them were not found in the open repo, so they presumably come from rfdetr_plus (**not verified**).
- **How to stay safe:** `pip install rfdetr` with no `[plus]` extra. The `rfdetr.platform` code only loads `rfdetr_plus` if it is already installed, so leaving it out keeps us Apache-only. We should add a CI check that `rfdetr_plus` is not in the lockfile.
- **Dependencies (1.11.2):** `torch>=2.2.0`, `torchvision>=0.17.0`, `transformers>=5.1.0,<6.0.0`, `supervision>=0.29.0`, `pydantic>=2,<3`, `pyDeprecate>=0.9,<0.10`. Python ≥3.10. Optional extras: `onnx` (onnx, onnxsim, onnxruntime), `tensorrt` (onnxruntime-gpu, tensorrt≥8.6.1), `train` (pytorch_lightning, torchmetrics, peft, roboflow, …).
- **Hugging Face fetch:** the DINOv2 backbone is pulled from the Hugging Face hub (`facebook/dinov2-*`) only when `pretrain_weights is None` (`rfdetr/models/lwdetr.py:836`). When we load an RF-DETR checkpoint, the backbone config comes from JSON files inside the package, so inference does not need huggingface.co.
- **Smallest size:** Nano is 30.5M params at 384px, with 2.3 ms latency on a T4 (TensorRT, FP16). The `.pth` file size is **not verified** because GCS is blocked; at fp32 it should be about 120 MB.

**Exact weight URLs in `rfdetr` 1.11.2 (`rfdetr/assets/model_weights.py`). All are Apache-2.0:**
```
rf-detr-nano.pth        https://storage.googleapis.com/rfdetr/nano_coco/checkpoint_best_regular.pth   md5 fb6504cce7fbdc783f7a46991f07639f
rf-detr-small.pth       https://storage.googleapis.com/rfdetr/small_coco/checkpoint_best_regular.pth  md5 fb37061c1af7bace359c91b723a8d5c1
rf-detr-medium.pth      https://storage.googleapis.com/rfdetr/medium_coco/checkpoint_best_regular.pth md5 7223f764a87b863f02eb8d52bf0ce2ee
rf-detr-base.pth        https://storage.googleapis.com/rfdetr/rf-detr-base-coco.pth                   md5 b4d3ce46099eaed50626ede388caf979
rf-detr-base-2.pth      https://storage.googleapis.com/rfdetr/rf-detr-base-2.pth                      md5 462f4d9df407ddc1812f42614040e913
rf-detr-base-o365.pth   https://storage.googleapis.com/rfdetr/top-secret-1234/lwdetr_dinov2_small_o365_checkpoint.pth md5 d93f4921ccbb0f0a2e4364bed290892b
rf-detr-large.pth       https://storage.googleapis.com/rfdetr/rf-detr-large.pth                      md5 992c8e862aa733a7bb2777e45d49f1a0
rf-detr-large-2026.pth  https://storage.googleapis.com/rfdetr/rf-detr-large-2026.pth                 md5 5cb72153541cbcb9aa6efa26222acc75
rf-detr-keypoint-preview-xlarge.pth https://storage.googleapis.com/rfdetr/rf-detr-keypoint-preview-xlarge.pth md5 6de511943ee85a547d4c5cb527daf0eb
rf-detr-seg-preview.pt  https://storage.googleapis.com/rfdetr/rf-detr-seg-preview.pt                  md5 e35820c28fb86080558123e47a5e49ca
rf-detr-seg-nano.pt     https://storage.googleapis.com/rfdetr/rf-detr-seg-n-ft.pth                    md5 9995497791d0ff1664a1d9ddee9cfd20
rf-detr-seg-small.pt    https://storage.googleapis.com/rfdetr/rf-detr-seg-s-ft.pth                    md5 0a2a3006381d0c42853907e700eadd08
rf-detr-seg-medium.pt   https://storage.googleapis.com/rfdetr/rf-detr-seg-m-ft.pth                    md5 a49af1562c3719227ad43d0ca53b4c7a
rf-detr-seg-large.pt    https://storage.googleapis.com/rfdetr/rf-detr-seg-l-ft.pth                    md5 275f7b094909544ed2841c94a677d07e
rf-detr-seg-xlarge.pt   https://storage.googleapis.com/rfdetr/rf-detr-seg-xl-ft.pth                   md5 3693b35d0eea86ebb3e0444f4a611fba
rf-detr-seg-xxlarge.pt  https://storage.googleapis.com/rfdetr/rf-detr-seg-2xl-ft.pth                  md5 040bc3412af840fa8a47e0ff69b552ba
```
**PML-1.0 weights in `rfdetr-plus` 1.1.0 (`rfdetr_plus/assets/model_weights.py`). Do not ship these:**
```
rf-detr-xlarge.pth   https://storage.googleapis.com/rfdetr/platform-licensed/rf-detr-xlarge.pth   md5 6ddf834f2bc5bed3214a82f9b0aaeed7
rf-detr-xxlarge.pth  https://storage.googleapis.com/rfdetr/platform-licensed/rf-detr-xxlarge.pth  md5 e3204689c1f0280427e4c33e6a2ac6cd
```
- **Host change coming:** on rf-detr main (unreleased 1.12.0.dev), every URL above has moved from `storage.googleapis.com/rfdetr/` to `https://repo.roboflow.com/rfdetr/` (same paths). Whitelist both hosts, or better, mirror the files ourselves and check them against the md5 values above.

### 2. supervision
- **Version:** 0.31.3 (PyPI, 2026-10-28). Licence: MIT (`license_expression: MIT`; repo `LICENSE.md` "MIT License, Copyright (c) 2022 Roboflow"). Python ≥3.10. Dependencies: av, defusedxml, matplotlib, numpy, pillow, pydeprecate, pyyaml, requests, scipy, tqdm. There is no torch dependency.
- **API check on the 0.31.3 wheel:**
  - `sv.PolygonZone` and `sv.PolygonZoneAnnotator` are present (`supervision/detection/tools/polygon_zone.py`).
  - `sv.LineZone`, `sv.LineZoneAnnotator` and `sv.LineZoneAnnotatorMulticlass` are present (`supervision/detection/line_zone.py`).
  - **`sv.ByteTrack` has been removed.** The changelog says: "Removed, as scheduled for `supervision-0.31.0`: `sv.ByteTrack` (use `ByteTrackTracker` from the `trackers` package instead)". The method also changed name, from `update_with_detections()` to `update()`. Inside supervision, the smoother and annotators now import `from trackers import ByteTrackTracker`.
  - **There is no time-in-zone API in the library.** Time-in-zone is an example, `examples/time_in_zone/` in the supervision repo (MIT). It uses `PolygonZone` with `trackers.ByteTrackTracker` and the `FPSBasedTimer` / `ClockBasedTimer` helpers in `examples/time_in_zone/utils/timers.py`. There are RF-DETR versions of the example (`rfdetr_file_example.py`, `rfdetr_stream_example.py`). We need to copy those timer classes into our own code; they are about 50 lines, MIT.
- Sources: https://pypi.org/project/supervision/ , https://github.com/roboflow/supervision (docs/changelog.md, examples/time_in_zone)

### 3. trackers (Roboflow)
- **Version:** 2.6.1 (PyPI, 2026-09-25). Licence: Apache-2.0 (classifier and wheel LICENSE; also the GitHub roboflow/trackers LICENSE). Python ≥3.10.
- **Exports:** `ByteTrackTracker`, `BoTSORTTracker`, `OCSORTTracker`, `SORTTracker`, `CBIoUTracker`, `McByteTracker`, `MotionEstimator`/CMC, and `MotionAwareTraceAnnotator`.
- **Weights:** no URLs for downloadable weights were found in the package source, so these are motion/IoU trackers with no ReID model to license.
- **Dependencies:** numpy≥2.0.2, supervision≥0.26.1, scipy≥1.13.1, opencv-python≥4.8.0, rich, requests, pydeprecate.
- Source: https://pypi.org/project/trackers/

### 4. D-FINE (transformers)
- **Repo names:** the Hugging Face repos use hyphens, `ustc-community/dfine-{nano,small,medium,large,xlarge}-{coco,obj365,obj2coco}`, not `dfine_*`. All 13 repos are tagged `license:apache-2.0`. The upstream code (github.com/Peterande/D-FINE) is Apache-2.0.
- **transformers version:** `models/d_fine` is missing in 4.51.0 and present in 4.52.1, so D-FINE needs **transformers ≥4.52**. The latest release is 5.22.1 (2026-10-30, Python ≥3.11).
- **Size:** dfine-nano-coco is `model.safetensors` 15,278,996 bytes (about 3.8M params). Host: huggingface.co.
- Sources: https://huggingface.co/api/models?author=ustc-community , https://huggingface.co/api/models/ustc-community/dfine-nano-coco/tree/main , https://github.com/Peterande/D-FINE

### 5. RT-DETRv2 (transformers)
- **Repos:** `PekingU/rtdetr_v2_{r18vd,r34vd,r50vd,r101vd}`, all tagged `license:apache-2.0`. The upstream code (github.com/lyuwenyu/RT-DETR) is Apache-2.0.
- **transformers version:** `models/rt_detr_v2` is present from 4.49.0, so RT-DETRv2 needs **transformers ≥4.49**.
- **Size:** r18vd is `model.safetensors` 80,904,640 bytes. Host: huggingface.co.
- Sources: https://huggingface.co/api/models?author=PekingU&search=rtdetr_v2 , https://huggingface.co/api/models/PekingU/rtdetr_v2_r18vd/tree/main

### 6. Vision-language models and open-vocabulary detectors
- **Florence-2:**
  - `microsoft/Florence-2-base` is MIT (LICENSE: "MIT License, Copyright (c) Microsoft Corporation"). The repo carries the `custom_code` tag, so the microsoft repo needs `trust_remote_code`.
  - Native support (`models/florence2`) arrived in **transformers 4.56**. It uses the `florence-community/Florence-2-{base,base-ft,large,large-ft}` repos, which are also tagged MIT.
  - Size: base `model.safetensors` is 463,221,266 bytes.
  - **Recommendation:** use `florence-community/Florence-2-base` so that no remote code runs on customer boxes.
- **SmolVLM2:**
  - `HuggingFaceTB/SmolVLM2-2.2B-Instruct`, `-500M-Video-Instruct` and `-256M-Video-Instruct` are all Apache-2.0.
  - Needs **transformers ≥4.50** (`models/smolvlm`).
  - Smallest is 256M-Video-Instruct at 1,025,998,224 bytes (fp32). The 2.2B model is 2 shards totalling about 8.99 GB (fp32).
- **Qwen3-VL:**
  - All 40 `Qwen/Qwen3-VL-*` repos (2B/4B/8B/32B/30B-A3B/235B, Instruct and Thinking, plus FP8 and GGUF variants) are tagged `license:apache-2.0`. The GitHub QwenLM/Qwen3-VL repo LICENSE is Apache-2.0.
  - Needs **transformers ≥4.57** (`models/qwen3_vl` is missing in 4.56.0 and present in 4.57.0).
  - Smallest is Qwen3-VL-2B-Instruct at `model.safetensors` 4,255,140,312 bytes (bf16). FP8 and GGUF versions exist for smaller memory use.
- **Grounding DINO:**
  - `IDEA-Research/grounding-dino-tiny` and `-base` are both Apache-2.0. The upstream github.com/IDEA-Research/GroundingDINO repo is Apache-2.0.
  - In transformers since at least 4.40.
  - tiny is `model.safetensors` 689,359,096 bytes.
  - Note: Grounding DINO 1.5 / 1.6 / DINO-X from IDEA are API-only and **not** open. Only the original model is covered here.
- **Host for all of these:** huggingface.co. Edge boxes should get weights from our own mirror or bundle, never pull them live.
- Sources: https://huggingface.co/api/models/microsoft/Florence-2-base , https://huggingface.co/microsoft/Florence-2-base/blob/main/LICENSE , https://huggingface.co/api/models?author=florence-community , https://huggingface.co/api/models?author=HuggingFaceTB&search=SmolVLM2 , https://huggingface.co/api/models?author=Qwen&search=Qwen3-VL , https://huggingface.co/api/models?author=IDEA-Research&search=grounding

### 7. ONNX Runtime
- **Version:** `onnxruntime` 1.31.1 and `onnxruntime-gpu` 1.31.1 (both 2026-10-26). Licence: MIT. Python ≥3.11, which means **no Python 3.10 wheels** in 1.31.
- **Wheels for 1.31.1:**
  - `onnxruntime`: cp311, cp312, cp313 (and 313t), cp314 (and 314t). Platforms: manylinux_2_28 x86_64 (23.8 MB) and aarch64 (21.4 MB), macOS 14 arm64, win amd64 and arm64.
  - `onnxruntime-gpu`: cp311, cp312, cp313 (and 313t), cp314 (and 314t). Platforms: manylinux_2_28 x86_64 (255.6 MB), manylinux_2_34 aarch64 (212.4 MB), win amd64. **Python 3.11, 3.12 and 3.13 are all covered.**
  - The CUDA major version that the onnxruntime-gpu 1.31.1 wheel targets is **not verified**: the PyPI description gave no CUDA string, and I did not download the 255 MB wheel.
- Source: https://pypi.org/project/onnxruntime/ , https://pypi.org/project/onnxruntime-gpu/

### 8. PyTorch
- **Version:** `torch` 2.15.0 (PyPI, 2026-10-28), Python ≥3.11. Licence SPDX: `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib`. All of these are permissive.
- **torchvision:** latest on PyPI is 0.29.2 (`torch>=2.14.0`). Whether 0.29.2 is the official pair for torch 2.15 is **not verified**.
- **No CPU-only wheel for Linux x86_64 on PyPI.** The PyPI `manylinux_2_28_x86_64` wheel (539 MB) is the CUDA build. On Linux it pulls `cuda-toolkit==13.2.2`, `nvidia-cudnn-cu13`, `nvidia-nccl-cu13`, `nvidia-cusparselt-cu13`, `nvidia-nvshmem-cu13`, `cuda-bindings` and `triton~=3.9.0`. These markers are `platform_system == "Linux"`, so they apply to aarch64 as well. CPU-only Linux wheels are only on `download.pytorch.org/whl/cpu`, which is blocked here.
- **Size with CUDA deps:** resolved with `uv pip compile` for cp312 / manylinux_2_28 x86_64, then the wheel sizes from PyPI were added up. The total download is **about 3.0 GB**. The biggest pieces are nvidia-cudnn-cu13 at 519 MB, torch at 539 MB, nvidia-cublas at 405 MB, triton at 286 MB, nvidia-cusolver at 228 MB, nvidia-cufft at 218 MB and nvidia-nccl-cu13 at 216 MB. The installed size on disk is **not verified**; expect several GB.
- **Edge implication:** export to ONNX and run with onnxruntime (CPU wheel 24 MB) or TensorRT, and keep torch for training or labelling machines only.
- Source: https://pypi.org/project/torch/2.15.0/

### 9. Ultralytics: why it is banned
- **Version:** 8.4.198 (PyPI, 2026-11-02). Licence: AGPL-3.0. Evidence: PyPI `license: AGPL-3.0`, the classifier "GNU Affero General Public License v3 or later (AGPLv3+)", the header in `ultralytics/__init__.py` ("Ultralytics AGPL-3.0 License - https://ultralytics.com/license"), and the GitHub LICENSE file ("GNU AFFERO GENERAL PUBLIC LICENSE Version 3").
- **Why it is banned:** AGPL-3.0 copyleft (including the network-use clause) would require releasing our product's source code, unless we buy an Ultralytics Enterprise licence. Ultralytics applies the same AGPL / Enterprise terms to its YOLO weights. The RF-DETR README benchmark tables also mark YOLO11 and YOLO26 as AGPL-3.0.
- Source: https://pypi.org/project/ultralytics/ , https://github.com/ultralytics/ultralytics/blob/main/LICENSE

### Not verified
- RF-DETR `.pth` file sizes, because storage.googleapis.com is blocked.
- Weight URLs and the release date for RF-DETR Atto, Femto and Pico. They are only on rf-detr main and are PML anyway.
- The CUDA major version of the onnxruntime-gpu 1.31.1 wheel.
- The torch 2.15 installed size on disk, and its official torchvision pairing.
- The exact patch release where D-FINE landed (4.52.0 vs 4.52.1). It is absent in 4.51.0 and present in 4.52.1.
