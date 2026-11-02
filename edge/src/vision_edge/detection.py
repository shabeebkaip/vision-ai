"""Detectors (task EDG-05).

Three back-ends behind one interface:
  - `ReplayDetector`  : returns detections cached in the frame (tests, evaluation harness)
  - `RFDetrDetector`  : RF-DETR via the `rfdetr` package (development; needs `--extra rfdetr`)
  - `OnnxDetector`    : an RF-DETR model exported to ONNX (production edge boxes, CPU or GPU)

Only RF-DETR Nano/Small/Medium/Large are allowed (Apache-2.0). Ultralytics YOLO is banned (AGPL).
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from vision_edge.frames import Frame, Image
from vision_shared.schemas import Detection

# COCO category ids as used by DETR-family models (1-based, with gaps).
COCO_CLASSES: dict[int, str] = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane", 6: "bus", 7: "train",
    8: "truck", 9: "boat", 10: "traffic light", 11: "fire hydrant", 13: "stop sign",
    14: "parking meter", 15: "bench", 16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep",
    21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe", 27: "backpack",
    28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase", 34: "frisbee", 35: "skis",
    36: "snowboard", 37: "sports ball", 38: "kite", 39: "baseball bat", 40: "baseball glove",
    41: "skateboard", 42: "surfboard", 43: "tennis racket", 44: "bottle", 46: "wine glass",
    47: "cup", 48: "fork", 49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
    54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza",
    60: "donut", 61: "cake", 62: "chair", 63: "couch", 64: "potted plant", 65: "bed",
    67: "dining table", 70: "toilet", 72: "tv", 73: "laptop", 74: "mouse", 75: "remote",
    76: "keyboard", 77: "cell phone", 78: "microwave", 79: "oven", 80: "toaster", 81: "sink",
    82: "refrigerator", 84: "book", 85: "clock", 86: "vase", 87: "scissors", 88: "teddy bear",
    89: "hair drier", 90: "toothbrush",
}  # fmt: skip

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Detector(Protocol):
    name: str

    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]:
        """Return one list of detections per frame, boxes in that frame's pixel coordinates."""
        ...


class ReplayDetector:
    """Uses detections already attached to the frame (cached JSONL)."""

    name = "replay"

    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]:
        return [list(f.detections or []) for f in frames]


def _filter(dets: list[Detection], threshold: float, classes: set[str] | None) -> list[Detection]:
    return [
        d
        for d in dets
        if d.confidence >= threshold and (classes is None or d.class_name in classes)
    ]


class RFDetrDetector:
    """RF-DETR through the `rfdetr` package. Weights download on first use."""

    SIZES: ClassVar[dict[str, str]] = {
        "nano": "RFDETRNano",
        "small": "RFDETRSmall",
        "medium": "RFDETRMedium",
        "large": "RFDETRLarge",
    }

    def __init__(
        self,
        size: str = "nano",
        threshold: float = 0.35,
        classes: set[str] | None = None,
        weights: str | None = None,
    ) -> None:
        if size not in self.SIZES:
            raise ValueError(
                f"RF-DETR size must be one of {sorted(self.SIZES)} (Apache-2.0 sizes only)"
            )
        try:
            import rfdetr
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "rfdetr is not installed: run `uv sync --all-packages --extra rfdetr`"
            ) from exc
        cls = getattr(rfdetr, self.SIZES[size])
        kwargs: dict[str, Any] = {}
        if weights:
            kwargs["pretrain_weights"] = weights
        self._model = cls(**kwargs)
        with contextlib.suppress(Exception):  # optional speed-up
            self._model.optimize_for_inference()
        self.name = f"rfdetr-{size}"
        self.threshold = threshold
        self.classes = classes

    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]:  # pragma: no cover
        out: list[list[Detection]] = []
        for frame in frames:
            if frame.image is None:
                out.append([])
                continue
            rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
            result = self._model.predict(rgb, threshold=self.threshold)
            dets = [
                Detection(
                    class_name=COCO_CLASSES.get(int(cid), str(int(cid))),
                    confidence=float(conf),
                    box=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                )
                for b, conf, cid in zip(
                    result.xyxy, result.confidence, result.class_id, strict=True
                )
            ]
            out.append(_filter(dets, self.threshold, self.classes))
        return out


def _sigmoid(x: NDArray[np.float32]) -> NDArray[np.float32]:
    out: NDArray[np.float32] = (1.0 / (1.0 + np.exp(-x))).astype(np.float32)
    return out


class OnnxDetector:
    """RF-DETR exported to ONNX (`rfdetr` export). Inputs: 1x3xHxW float32, ImageNet-normalised
    RGB. Outputs: boxes (cx, cy, w, h normalised) [B, Q, 4] and class logits [B, Q, C].
    Post-processing follows the DETR top-k scheme (sigmoid, top-k over queries x classes)."""

    def __init__(
        self,
        model_path: str | Path,
        threshold: float = 0.35,
        classes: set[str] | None = None,
        class_names: dict[int, str] | None = None,
        providers: list[str] | None = None,
        top_k: int = 300,
    ) -> None:
        import onnxruntime as ort

        self._session = ort.InferenceSession(
            str(model_path), providers=providers or ort.get_available_providers()
        )
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        _, _, h, w = inp.shape
        self.input_h = int(h) if isinstance(h, int) else 384
        self.input_w = int(w) if isinstance(w, int) else 384
        self.threshold = threshold
        self.classes = classes
        self.class_names = class_names or COCO_CLASSES
        self.top_k = top_k
        self.name = f"onnx-{Path(model_path).stem}"

    def _preprocess(self, image: Image) -> NDArray[np.float32]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.input_w, self.input_h), interpolation=cv2.INTER_LINEAR)
        x = resized.astype(np.float32) / 255.0
        x = (x - IMAGENET_MEAN) / IMAGENET_STD
        return np.ascontiguousarray(x.transpose(2, 0, 1))

    def _split_outputs(
        self, outputs: list[NDArray[np.float32]]
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        names = [o.name for o in self._session.get_outputs()]
        by_name = dict(zip(names, outputs, strict=True))
        if "dets" in by_name and "labels" in by_name:
            return by_name["dets"], by_name["labels"]
        boxes = next(o for o in outputs if o.shape[-1] == 4)
        logits = next(o for o in outputs if o.shape[-1] != 4)
        return boxes, logits

    def postprocess(
        self, boxes: NDArray[np.float32], logits: NDArray[np.float32], width: int, height: int
    ) -> list[Detection]:
        """boxes [Q, 4] cxcywh normalised, logits [Q, C] for one image."""
        probs = _sigmoid(logits.astype(np.float32))
        _, c = probs.shape
        flat = probs.reshape(-1)
        k = min(self.top_k, flat.size)
        idx = np.argpartition(-flat, k - 1)[:k]
        idx = idx[np.argsort(-flat[idx])]
        dets: list[Detection] = []
        for i in idx:
            score = float(flat[i])
            if score < self.threshold:
                break
            qi, ci = divmod(int(i), c)
            name = self.class_names.get(ci)
            if name is None or (self.classes is not None and name not in self.classes):
                continue
            cx, cy, bw, bh = boxes[qi]
            x1 = max(0.0, float(cx - bw / 2) * width)
            y1 = max(0.0, float(cy - bh / 2) * height)
            x2 = min(float(width), float(cx + bw / 2) * width)
            y2 = min(float(height), float(cy + bh / 2) * height)
            dets.append(Detection(class_name=name, confidence=score, box=(x1, y1, x2, y2)))
        return dets

    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]:
        images = [f for f in frames if f.image is not None]
        results: dict[int, list[Detection]] = {}
        if images:
            batch = np.stack([self._preprocess(f.image) for f in images if f.image is not None])
            outputs = self._session.run(None, {self._input_name: batch})
            boxes, logits = self._split_outputs(list(outputs))
            for j, f in enumerate(images):
                results[id(f)] = self.postprocess(boxes[j], logits[j], f.width, f.height)
        return [results.get(id(f), []) for f in frames]


def build_detector(
    kind: str,
    *,
    model: str | None = None,
    threshold: float = 0.35,
    classes: set[str] | None = None,
) -> Detector:
    """Factory used by the CLI and harness: kind = replay | rfdetr[-size] | onnx."""
    if kind == "replay":
        return ReplayDetector()
    if kind.startswith("rfdetr"):
        size = kind.split("-", 1)[1] if "-" in kind else "nano"
        return RFDetrDetector(size=size, threshold=threshold, classes=classes, weights=model)
    if kind == "onnx":
        if not model:
            raise ValueError("onnx detector needs --model path/to/model.onnx")
        return OnnxDetector(model, threshold=threshold, classes=classes)
    raise ValueError(f"unknown detector {kind!r}")
