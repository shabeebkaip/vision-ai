# ADR 002: RF-DETR instead of Ultralytics YOLO

Status: accepted (2 Nov 2026)

**Decision.** The default detector is RF-DETR (Nano/Small/Medium/Large, Apache-2.0), exported to
ONNX/TensorRT for production. Ultralytics packages are banned.

**Why.** Ultralytics YOLO is AGPL-3.0, and its licence page requires a paid Enterprise licence for
any commercial product, SaaS or edge device, including models we train ourselves. RF-DETR matches or
beats YOLO on COCO accuracy at similar latency (Nano 48.4 mAP at 2.3 ms on a T4) with a permissive
licence. RF-DETR's extra sizes (Atto, Femto, Pico, XL, 2XL) are under PML-1.0 and also excluded.

**Consequences.** Some tutorials and pretrained community models assume YOLO; we fine-tune RF-DETR
instead. The licence guard in CI enforces this.
