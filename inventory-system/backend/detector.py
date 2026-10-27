"""Shared lazy, thread-safe inference for the custom shelf and COCO models."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

import config

log = logging.getLogger("detector")
_UNSET = object()


def normalize_label(label: str) -> str:
    """Normalize label spelling without changing the model's displayed name."""
    return "".join(char.casefold() for char in str(label) if char.isalnum())


_EXPECTED_CUSTOM_CLASSES = {normalize_label(label) for label in config.CUSTOM_MODEL_CLASSES}


def _names_values(names: Any) -> list[str]:
    values = names.values() if hasattr(names, "values") else names
    return [str(value) for value in values]


def _name_for(names: Any, class_id: int) -> str:
    if hasattr(names, "get"):
        value = names.get(class_id, names.get(str(class_id), ""))
    else:
        value = names[class_id]
    return str(value)


def _scalar(value: Any) -> float:
    if hasattr(value, "item"):
        return float(value.item())
    if hasattr(value, "tolist"):
        value = value.tolist()
    while isinstance(value, (tuple, list)):
        value = value[0]
    return float(value)


def _coordinates(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    while isinstance(value, (tuple, list)) and len(value) == 1 and isinstance(value[0], (tuple, list)):
        value = value[0]
    return [float(item) for item in value]


def box_iou(first: list[float], second: list[float]) -> float:
    """Calculate intersection-over-union for xyxy boxes."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_first = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_second = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_first + area_second - intersection
    return intersection / union if union else 0.0


class DualModelDetector:
    """Lazily load models once and return filtered, merged frame detections."""

    def __init__(self, custom_model: Any = _UNSET, coco_model: Any = _UNSET,
                 custom_path: str | None = None, coco_path: str | None = None,
                 model_loader=None):
        self.custom_path = custom_path or config.CUSTOM_MODEL_PATH
        self.coco_path = coco_path or config.COCO_MODEL_PATH
        self._custom_model = None if custom_model is _UNSET else custom_model
        self._coco_model = None if coco_model is _UNSET else coco_model
        self._custom_injected = custom_model is not _UNSET
        self._coco_injected = coco_model is not _UNSET
        self._model_loader = model_loader
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._loaded = False

    @property
    def custom_model(self):
        self._ensure_loaded()
        return self._custom_model

    @property
    def coco_model(self):
        self._ensure_loaded()
        return self._coco_model

    @staticmethod
    def _absolute(path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(config.BACKEND_DIR, path)

    def _loader(self):
        if self._model_loader:
            return self._model_loader
        from ultralytics import YOLO
        return YOLO

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            loader = None
            custom_path = self._absolute(self.custom_path)
            if not self._custom_injected:
                if not os.path.isfile(custom_path):
                    message = f"Custom YOLO model best.pt was not found: {custom_path}"
                    log.error(message)
                    raise RuntimeError(message)
                loader = self._loader()
                self._custom_model = loader(custom_path)
            if not self._coco_injected:
                coco_path = self._absolute(self.coco_path)
                if not os.path.isfile(coco_path):
                    fallback = os.path.join(config.BACKEND_DIR, "yolo11n.pt")
                    if os.path.isfile(fallback):
                        coco_path = fallback
                if os.path.isfile(coco_path):
                    loader = loader or self._loader()
                    self._coco_model = loader(coco_path)
                    self.coco_path = coco_path
                else:
                    self._coco_model = None
                    log.warning("COCO model not found at %s (or yolo11n.pt); continuing with custom model only",
                                self._absolute(self.coco_path))
            custom_names = getattr(self._custom_model, "names", {}) if self._custom_model else {}
            coco_names = getattr(self._coco_model, "names", {}) if self._coco_model else {}
            if self._custom_model:
                classes = _names_values(custom_names)
                log.info("Custom YOLO model %s classes: %s", custom_path, classes)
                actual = {normalize_label(name) for name in classes}
                if actual != _EXPECTED_CUSTOM_CLASSES:
                    log.warning("Custom model classes do not match expected Gloria_biscuits, Gunanzi_snack, Mirinda_apple: %s", classes)
            if self._coco_model:
                log.info("COCO model %s classes: %s", self._absolute(self.coco_path), _names_values(coco_names))
            self._loaded = True

    @staticmethod
    def _run_model(model: Any, frame: Any, confidence: float) -> Any:
        result = model(frame, conf=confidence, verbose=False)
        return result[0] if isinstance(result, (tuple, list)) else result

    @staticmethod
    def _extract(result: Any, source: str) -> list[dict[str, Any]]:
        names = getattr(result, "names", None)
        detections = []
        for box in getattr(result, "boxes", ()) or ():
            class_id = int(_scalar(box.cls))
            confidence = _scalar(box.conf)
            coords = _coordinates(box.xyxy)
            if len(coords) != 4:
                continue
            detections.append({"label": _name_for(names, class_id), "conf": confidence,
                               "box": coords, "source": source})
        return detections

    def raw_detect(self, frame: Any, confidence: float = 0.01) -> list[dict[str, Any]]:
        """Return unfiltered candidates for diagnostics, including COCO rejects."""
        self._ensure_loaded()
        candidates = []
        with self._inference_lock:
            if self._custom_model:
                result = self._run_model(self._custom_model, frame, confidence)
                candidates.extend(self._extract(result, "custom"))
            if self._coco_model:
                result = self._run_model(self._coco_model, frame, confidence)
                candidates.extend(self._extract(result, "coco"))
        return candidates

    def detect(self, frame: Any) -> list[dict[str, Any]]:
        """Return confidence-filtered custom detections and allowed COCO fruit."""
        return self._detect_at_thresholds(
            frame,
            config.CUSTOM_CONFIDENCE_THRESHOLD,
            config.COCO_CONFIDENCE_THRESHOLD,
        )

    def _detect_at_thresholds(self, frame: Any, custom_threshold: float,
                              coco_threshold: float) -> list[dict[str, Any]]:
        """Run both models on one image using the supplied confidence cutoffs."""
        self._ensure_loaded()
        candidates = []
        with self._inference_lock:
            if self._custom_model:
                result = self._run_model(self._custom_model, frame, custom_threshold)
                candidates.extend(self._extract(result, "custom"))
            if self._coco_model:
                result = self._run_model(self._coco_model, frame, coco_threshold)
                candidates.extend(self._extract(result, "coco"))
        custom = [item for item in candidates if item["source"] == "custom"
                  and item["conf"] >= custom_threshold]
        coco = [item for item in candidates if item["source"] == "coco"
                and item["conf"] >= coco_threshold
                and normalize_label(item["label"]) in config.COCO_ALLOWED_CLASSES]
        merged = list(custom)
        for fruit in coco:
            if any(box_iou(fruit["box"], item["box"]) > 0.5 for item in custom):
                continue
            merged.append(fruit)
        return merged

    def detect_in_regions(self, frame: Any, regions: dict[str, Any]) -> list[dict[str, Any]]:
        """Detect full-frame objects, then retry missed product zones on crops.

        The full-frame pass finds objects outside configured zones. Every zone
        is also inferred as a crop on every cycle, so an incomplete full-frame
        result cannot hide additional products in a partition. Crop detections
        are translated back to frame pixels and tagged with their source zone.
        """
        height, width = frame.shape[:2]
        detections = self.detect(frame)
        for region_id, definition in regions.items():
            box = definition.get("box", definition) if isinstance(definition, dict) else definition
            if not isinstance(box, (tuple, list)) or len(box) != 4:
                continue
            expected_labels = definition.get("model_labels", []) if isinstance(definition, dict) else []
            expected = {normalize_label(label) for label in expected_labels}
            if not expected:
                expected = {normalize_label(region_id)}

            x1 = max(0, min(width, round(float(box[0]) * width / 1280)))
            y1 = max(0, min(height, round(float(box[1]) * height / 720)))
            x2 = max(0, min(width, round(float(box[2]) * width / 1280)))
            y2 = max(0, min(height, round(float(box[3]) * height / 720)))
            if x2 <= x1 or y2 <= y1:
                continue

            def matches_region(item: dict[str, Any]) -> bool:
                label_matches = normalize_label(item["label"]) in expected
                cx = (float(item["box"][0]) + float(item["box"][2])) / 2
                cy = (float(item["box"][1]) + float(item["box"][3])) / 2
                return label_matches and x1 <= cx <= x2 and y1 <= cy <= y2

            full_frame_matches = [item for item in detections if matches_region(item)]
            for item in full_frame_matches:
                item["region_id"] = region_id

            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            cropped_detections = self._detect_at_thresholds(
                crop,
                getattr(config, "REGION_CUSTOM_CONFIDENCE_THRESHOLD", config.CUSTOM_CONFIDENCE_THRESHOLD),
                getattr(config, "REGION_COCO_CONFIDENCE_THRESHOLD", config.COCO_CONFIDENCE_THRESHOLD),
            )
            for item in cropped_detections:
                if normalize_label(item["label"]) not in expected:
                    continue
                item["box"] = [item["box"][0] + x1, item["box"][1] + y1,
                               item["box"][2] + x1, item["box"][3] + y1]
                # The full-frame pass and crop pass often report the same
                # object. Suppress only that overlap; retain other crop boxes
                # to recover missed items in the same partition.
                if any(normalize_label(existing["label"]) == normalize_label(item["label"])
                       and box_iou(existing["box"], item["box"]) > 0.5
                       for existing in full_frame_matches):
                    continue
                item["region_id"] = region_id
                detections.append(item)
        return detections


_shared_detector: DualModelDetector | None = None
_shared_detector_lock = threading.Lock()


def get_detector() -> DualModelDetector:
    """Return the process-wide detector; model loading remains lazy."""
    global _shared_detector
    if _shared_detector is None:
        with _shared_detector_lock:
            if _shared_detector is None:
                _shared_detector = DualModelDetector()
    return _shared_detector


def detect(frame: Any) -> list[dict[str, Any]]:
    """Convenience API shared by the browser endpoint and camera worker."""
    return get_detector().detect(frame)
