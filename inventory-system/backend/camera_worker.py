"""Privacy-safe OpenCV + YOLO26 shelf-inventory worker.

Frames are held in RAM for a single detection cycle only. This module never
writes camera images or video to disk; it persists only inventory records.
"""
import logging
import os
import threading
from datetime import datetime, timedelta

import config
import database

log = logging.getLogger("camera_worker")


def point_in_region(cx, cy, region):
    """Support configured {box: (...)} regions and raw rectangle regions."""
    x1, y1, x2, y2 = region.get("box", region) if isinstance(region, dict) else region
    return x1 <= cx <= x2 and y1 <= cy <= y2


def count_detections_per_region(results, frame_shape=None):
    """Filter YOLO boxes, then count each accepted centroid in one shelf region."""
    counts = {pid: 0 for pid in config.SHELF_REGIONS}
    for box in results.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        if conf < config.CONFIDENCE_THRESHOLD:
            continue
        label = _name_for(results, cls_id)
        coords = box.xyxy[0]
        x1, y1, x2, y2 = coords.tolist() if hasattr(coords, "tolist") else coords
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        # Shelf rectangles are calibrated at 1280×720. Browser cameras may
        # submit another resolution, so normalize their centroids first.
        if frame_shape:
            height, width = frame_shape[:2]
            if width and height:
                cx, cy = cx * 1280 / width, cy * 720 / height
        for product_id, region in config.SHELF_REGIONS.items():
            if point_in_region(cx, cy, region):
                # Fine-tuned models should list the product ID (or an explicit
                # model_labels value) as the class. COCO labels remain a
                # backwards-compatible fallback for the prototype regions.
                expected = set(region.get("model_labels", [product_id]))
                if label in expected or (config.ALLOW_GENERIC_COCO_COUNTING and label in config.COUNTABLE_COCO_CLASSES):
                    counts[product_id] += 1
                break
    return counts


def _name_for(results, class_id):
    """Return a model label whether Ultralytics supplied a list or a dict."""
    names = results.names
    return str(names.get(class_id, "") if hasattr(names, "get") else names[class_id])


def unknown_detections_per_region(results):
    """Return high-confidence labels in shelf regions that cannot be counted.

    A custom shelf model should use product IDs as its class labels (for
    example ``salt_1kg``). The legacy COCO allow-list remains supported for
    calibrated regions, but any other detected label on a shelf is surfaced to
    an operator instead of changing inventory.
    """
    unknown = []
    for box in results.boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        if confidence < config.CONFIDENCE_THRESHOLD:
            continue
        label = _name_for(results, class_id)
        coords = box.xyxy[0]
        x1, y1, x2, y2 = coords.tolist() if hasattr(coords, "tolist") else coords
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        shape = getattr(results, "orig_shape", None)
        if shape:
            height, width = shape[:2]
            if width and height:
                cx, cy = cx * 1280 / width, cy * 720 / height
        for product_id, region in config.SHELF_REGIONS.items():
            if not point_in_region(cx, cy, region):
                continue
            expected = set(region.get("model_labels", [product_id]))
            is_legacy_coco_label = label in config.COUNTABLE_COCO_CLASSES
            if label not in expected and not (config.ALLOW_GENERIC_COCO_COUNTING and is_legacy_coco_label):
                unknown.append({"label": label, "product_id": product_id, "confidence": confidence})
            break
    return unknown


class ShelfReconciler:
    """Apply only stable visual count changes to the auditable inventory DB."""

    def __init__(self):
        self.last_observed = None
        self.repeat_count = 0
        self.baseline = None
        self.unknown_alerted_at = {}

    def reconcile(self, counts):
        # One transient bad frame must never move stock. Establish the first
        # stable camera baseline without overwriting the existing database.
        if counts == self.last_observed:
            self.repeat_count += 1
        else:
            self.last_observed = dict(counts)
            self.repeat_count = 1
        if self.repeat_count < config.STABLE_COUNT_CYCLES:
            return {}
        if self.baseline is None:
            self.baseline = dict(counts)
            log.info("Established stable shelf baseline: %s", self.baseline)
            return {}

        changed = {}
        for product_id, observed_count in counts.items():
            previous_count = self.baseline.get(product_id, observed_count)
            delta = observed_count - previous_count
            if not delta:
                continue
            if not database.get_product(product_id):
                log.warning("Shelf region %s has no matching product; ignoring count change", product_id)
                continue
            if delta > 0:
                current = database.receive_stock(
                    product_id, delta, "camera_receipt",
                    note="Stable shelf-camera increase",
                )
            else:
                current = database.get_latest_count(product_id) or 0
                removed = min(-delta, current)
                if not removed:
                    self.baseline[product_id] = observed_count
                    continue
                current -= removed
                database.log_sales_event(product_id, removed, sale_type="auto")
                database.write_stock_log(product_id, current)
            self.baseline[product_id] = observed_count
            changed[product_id] = current
            log.info("Shelf camera reconciled %s by %+d; inventory is now %d", product_id, delta, current)
        return changed

    def report_unknown(self, detections):
        now = datetime.utcnow()
        cooldown = timedelta(seconds=config.UNKNOWN_ITEM_ALERT_COOLDOWN_SECONDS)
        for item in detections:
            key = (item["product_id"], item["label"])
            if now - self.unknown_alerted_at.get(key, datetime.min) < cooldown:
                continue
            message = (f"Unknown shelf item '{item['label']}' detected in the "
                       f"{item['product_id']} region; inventory was not changed.")
            database.record_alert("unknown", "WARNING", message, False)
            self.unknown_alerted_at[key] = now
            log.warning(message)


class CameraDetector:
    """Lazily opens an integrated/USB webcam and runs in-memory inference."""

    def __init__(self):
        import cv2
        from ultralytics import YOLO

        self.cv2 = cv2
        if not os.path.exists(config.YOLO_MODEL_PATH):
            raise RuntimeError(f"YOLO model not found: {config.YOLO_MODEL_PATH}. Add your fine-tuned yolo26n.pt before starting the worker.")
        self.model = YOLO(config.YOLO_MODEL_PATH)
        self.cap = None

    def _open_camera(self):
        # Index 0 is normally the integrated webcam. Set CAMERA_INDEX to USB
        # camera's index; fallback candidates keep disconnections non-fatal.
        candidates = [config.CAMERA_INDEX] + [i for i in getattr(config, "CAMERA_FALLBACK_INDICES", [0, 1, 2]) if i != config.CAMERA_INDEX]
        for index in candidates:
            cap = self.cv2.VideoCapture(index)
            cap.set(self.cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(self.cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if cap.isOpened():
                self.cap = cap
                log.info("Shelf camera opened at index %s", index)
                return True
            cap.release()
        return False

    def next_counts(self):
        # Capture: reconnect on failed/open-unavailable cycles.
        if self.cap is None and not self._open_camera():
            log.warning("No webcam available; retrying next detection interval")
            return None
        ok, frame = self.cap.read()
        if not ok:
            log.warning("Webcam frame read failed; releasing and retrying next interval")
            self.cap.release()
            self.cap = None
            return None
        try:
            # Inference -> filter -> region match; frame remains in memory only.
            results = self.model(frame, verbose=False)[0]
            return count_detections_per_region(results, frame.shape), unknown_detections_per_region(results)
        except Exception as exc:
            log.exception("YOLO inference failed: %s", exc)
            return None
        finally:
            del frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def calibrate_region(product_id, label=None, camera_index=None):
    """Draw a one-time shelf rectangle and add it to ``config.SHELF_REGIONS``.

    Press Enter/Space to accept; Esc cancels. No calibration image is saved.
    Copy the returned box into config.py to retain it after a server restart.
    """
    import cv2
    index = config.CAMERA_INDEX if camera_index is None else camera_index
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open camera index {index} for calibration")
    try:
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("Camera opened but did not return a calibration frame")
        x, y, width, height = cv2.selectROI("Draw shelf region then press Enter", frame, showCrosshair=True)
        if width <= 0 or height <= 0:
            return None
        box = (int(x), int(y), int(x + width), int(y + height))
        config.SHELF_REGIONS[product_id] = {"box": box, "label": label or product_id}
        return box
    finally:
        cap.release()
        cv2.destroyAllWindows()


def run_detection_loop(stop_event: threading.Event, on_cycle=None):
    """Thread loop: capture → inference → stable reconciliation → alert."""
    try:
        detector = CameraDetector()
    except Exception as exc:
        log.error("Camera worker not started: %s", exc)
        return
    interval = getattr(config, "DETECTION_INTERVAL", config.DETECTION_INTERVAL_SECONDS)
    reconciler = ShelfReconciler()
    log.info("YOLO shelf worker started; one frame every %ss", interval)
    try:
        while not stop_event.is_set():
            observation = detector.next_counts()
            if observation is not None:
                counts, unknown = observation
                changed = reconciler.reconcile(counts)
                reconciler.report_unknown(unknown)
                # Alert evaluation is synchronous, in this same detection cycle.
                if on_cycle:
                    on_cycle(changed)
            stop_event.wait(interval)
    finally:
        detector.close()
