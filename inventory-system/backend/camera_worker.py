"""Privacy-safe OpenCV + YOLO26 shelf-inventory worker.

Frames are held in RAM for a single detection cycle only. This module never
writes camera images or video to disk; it persists only inventory records.
"""
import logging
import threading
import time
from datetime import datetime, timedelta

import config
import database
from detector import get_detector, normalize_label

log = logging.getLogger("camera_worker")


def point_in_region(cx, cy, region):
    """Test a 1280x720-space point against a region definition."""
    x1, y1, x2, y2 = region.get("box", region) if isinstance(region, dict) else region
    return x1 <= cx <= x2 and y1 <= cy <= y2


def label_matches(label, expected):
    """Compare model labels while ignoring case, spaces, hyphens and underscores."""
    return normalize_label(label) == normalize_label(expected)


def _region_model_labels(product_id, region, product=None):
    if isinstance(region, dict):
        labels = region.get("model_labels")
        if labels is None:
            labels = region.get("label")
        if labels is not None:
            return [str(label) for label in (labels if isinstance(labels, (list, tuple, set)) else [labels])]
    if product and product.get("camera_label"):
        return [str(product["camera_label"])]
    return [str(product_id)]


def label_matches_region(label, product_id, region):
    """Return whether a model label maps to the given product's shelf region."""
    return any(label_matches(label, expected) for expected in _region_model_labels(product_id, region))


def _registered_shelf_regions():
    """Map configured product-ID regions to products currently in inventory."""
    registered = {}
    products = database.get_all_products()
    by_id = {product["product_id"]: product for product in products}
    by_normalized_id = {}
    for product in products:
        by_normalized_id.setdefault(normalize_label(product["product_id"]), []).append(product)
    claimed_product_ids = set()
    for product_id, definition in config.SHELF_REGIONS.items():
        labels = _region_model_labels(product_id, definition)
        product = by_id.get(product_id)
        if product is None:
            matches = by_normalized_id.get(normalize_label(product_id), [])
            if len(matches) == 1:
                product = matches[0]
        if product is None:
            label_matches = [item for item in products if any(
                label_matches(expected, item.get("camera_label", "")) or
                label_matches(expected, item.get("name", "")) for expected in labels
            )]
            if len(label_matches) == 1:
                product = label_matches[0]
        if not product:
            continue
        if product["product_id"] in claimed_product_ids:
            log.warning("Product %s is mapped to multiple camera regions; only the first region is used",
                        product["product_id"])
            continue
        claimed_product_ids.add(product["product_id"])
        box = definition.get("box", definition) if isinstance(definition, dict) else definition
        registered[product["product_id"]] = {
            "box": box,
            "model_labels": _region_model_labels(product_id, definition, product),
        }
    return registered


def registered_camera_labels():
    """Return model labels mapped to configured regions and catalog products."""
    return {label for region in _registered_shelf_regions().values() for label in region["model_labels"]}


def warn_region_configuration(custom_classes=None):
    """Warn about unregistered configured regions and custom classes without zones."""
    registered = _registered_shelf_regions()
    for product_id, definition in config.SHELF_REGIONS.items():
        labels = _region_model_labels(product_id, definition)
        if not any(normalize_label(product_id) == normalize_label(registered_id) or
                   any(label_matches(expected, registered_label)
                       for expected in labels for registered_label in region["model_labels"])
                   for registered_id, region in registered.items()):
            log.warning("Shelf region %s has no matching product_id in the database", product_id)
    classes = custom_classes or config.CUSTOM_MODEL_CLASSES
    mapped = {normalize_label(label) for region in config.SHELF_REGIONS.values()
              for label in _region_model_labels("", region)}
    for class_name in classes:
        if normalize_label(class_name) not in mapped:
            log.warning("Custom-model class %s has no configured shelf region; draw/configure its region", class_name)


def _threshold_for(detection):
    return (config.CUSTOM_CONFIDENCE_THRESHOLD if detection.get("source") == "custom"
            else config.COCO_CONFIDENCE_THRESHOLD)


def _scaled_centroid(detection, frame_shape=None):
    x1, y1, x2, y2 = detection["box"]
    cx, cy = (float(x1) + float(x2)) / 2, (float(y1) + float(y2)) / 2
    if frame_shape:
        height, width = frame_shape[:2]
        if width and height:
            cx, cy = cx * 1280 / width, cy * 720 / height
    return cx, cy


def count_detections_per_region(detections, frame_shape=None):
    """Count filtered model detections whose labels and centers match regions."""
    regions = _registered_shelf_regions()
    counts = {pid: 0 for pid in regions}
    for detection in detections:
        if float(detection.get("conf", 0)) < _threshold_for(detection):
            continue
        label = detection["label"]
        cx, cy = _scaled_centroid(detection, frame_shape)
        matches = [(pid, region) for pid, region in regions.items()
                   if point_in_region(cx, cy, region) and
                   any(label_matches(label, expected) for expected in region["model_labels"])]
        if not matches:
            continue
        if matches[0][0] in counts:
            counts[matches[0][0]] += 1
    return counts


def unknown_detections_per_region(detections, frame_shape=None):
    """Return only unmapped custom-model detections inside configured regions."""
    unknown = []
    regions = _registered_shelf_regions()
    mapped_labels = {normalize_label(label) for region in regions.values() for label in region["model_labels"]}
    for detection in detections:
        if detection.get("source") != "custom":
            continue
        confidence = float(detection.get("conf", 0))
        if confidence < config.CUSTOM_CONFIDENCE_THRESHOLD or normalize_label(detection["label"]) in mapped_labels:
            continue
        cx, cy = _scaled_centroid(detection, frame_shape)
        for product_id, region in regions.items():
            if point_in_region(cx, cy, region):
                unknown.append({"label": detection["label"], "product_id": product_id,
                                "confidence": confidence, "source": "custom"})
                break
    return unknown


def explain_detection(detection, frame_shape=None):
    """Return (counted, reason) for one raw candidate, for diagnostics."""
    source = detection.get("source")
    label = detection.get("label", "")
    if source == "coco" and normalize_label(label) not in config.COCO_ALLOWED_CLASSES:
        return False, "discarded COCO class (not apple, banana, or orange)"
    if float(detection.get("conf", 0)) < _threshold_for(detection):
        return False, f"below threshold ({_threshold_for(detection):.2f})"
    cx, cy = _scaled_centroid(detection, frame_shape)
    containing = []
    for pid, definition in config.SHELF_REGIONS.items():
        region = {"box": definition.get("box", definition) if isinstance(definition, dict) else definition,
                  "model_labels": _region_model_labels(pid, definition)}
        if point_in_region(cx, cy, region):
            containing.append((pid, region))
    if not containing:
        return False, "outside every configured region"
    matching = [(pid, region) for pid, region in containing
                if any(label_matches(label, expected) for expected in region["model_labels"])]
    if not matching:
        return False, "label mismatch for the region containing this detection"
    product_ids = {item["product_id"] for item in database.get_all_products()}
    if matching[0][0] not in product_ids:
        return False, f"region {matching[0][0]} has no matching product in the database"
    return True, f"counted in {matching[0][0]}"


class ShelfReconciler:
    """Apply only stable visual count changes to the auditable inventory DB."""

    def __init__(self):
        self.last_observed = None
        self.repeat_count = 0
        self.baseline = None
        self.last_stable_at = None
        self.unknown_alerted_at = {}
        self._lock = threading.Lock()

    def reconcile(self, counts):
        with self._lock:
            counts = dict(counts)
            # One transient bad frame must never move stock. Establish the first
            # stable camera baseline without overwriting the existing database.
            if counts == self.last_observed:
                self.repeat_count += 1
            else:
                self.last_observed = dict(counts)
                self.repeat_count = 1
            if self.repeat_count < config.STABLE_COUNT_CYCLES:
                return {}
            observed_at = datetime.utcnow().isoformat()
            if self.baseline is None:
                self.baseline = dict(counts)
                log.info("Established stable shelf baseline: %s", self.baseline)
                # When a product was initialized at zero, treat the first
                # stable camera count as its opening shelf receipt. Preserve
                # any non-zero inventory already recorded in the database.
                opening_receipts = {}
                for product_id, observed_count in counts.items():
                    if observed_count <= 0 or not database.get_product(product_id):
                        continue
                    current_stock = database.get_latest_count(product_id) or 0
                    if current_stock == 0:
                        opening_receipts[product_id] = database.apply_camera_delta(
                            product_id, observed_count
                        )
                        log.info("Camera recorded opening shelf count for %s: %d",
                                 product_id, observed_count)
                    # Start movement reconciliation after the opening receipts so
                    # they are not mistaken for a later sale or delivery.
                    self.last_stable_at = datetime.utcnow().isoformat()
                return opening_receipts

            changed = {}
            for product_id, observed_count in counts.items():
                if product_id not in self.baseline:
                    self.baseline[product_id] = observed_count
                    continue
                delta = observed_count - self.baseline[product_id]
                if not delta:
                    continue
                if not database.get_product(product_id):
                    log.warning("Shelf region %s has no matching product; ignoring count change", product_id)
                    continue

                # POS sales and recorded receipts have already changed the live
                # database. If the same movement is visible on the shelf, don't
                # apply it a second time as an automatic camera movement.
                known = database.get_known_inventory_changes_since(
                    product_id, self.last_stable_at or ""
                )
                known_delta = known["net_delta"]
                if delta * known_delta > 0 and abs(known_delta) >= abs(delta):
                    delta = 0
                else:
                    delta -= known_delta

                if delta:
                    current = database.apply_camera_delta(product_id, delta)
                    changed[product_id] = current
                    log.info("Shelf camera reconciled %s by %+d; inventory is now %d",
                             product_id, delta, current)
                self.baseline[product_id] = observed_count
            self.last_stable_at = observed_at
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
    """Lazily opens a webcam and uses the process-wide shared detector."""

    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.detector = get_detector()
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
            detections = self.detector.detect(frame)
            return (count_detections_per_region(detections, frame.shape),
                    unknown_detections_per_region(detections, frame.shape))
        except Exception as exc:
            log.exception("YOLO inference failed: %s", exc)
            return None
        finally:
            del frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def calibrate_region(product_id, label=None, camera_index=None, model_labels=None):
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
        x, y, roi_width, roi_height = cv2.selectROI("Draw shelf region then press Enter", frame, showCrosshair=True)
        if roi_width <= 0 or roi_height <= 0:
            return None
        frame_height, frame_width = frame.shape[:2]
        scale_x = 1280 / frame_width
        scale_y = 720 / frame_height
        box = (int(x * scale_x), int(y * scale_y),
               int((x + roi_width) * scale_x), int((y + roi_height) * scale_y))
        labels = model_labels or [label or product_id]
        config.SHELF_REGIONS[product_id] = {"box": box, "model_labels": labels}
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
    try:
        model_names = detector.detector.custom_model.names
        model_names = list(model_names.values()) if hasattr(model_names, "values") else list(model_names)
        warn_region_configuration(model_names)
    except RuntimeError:
        log.exception("Custom model is unavailable; camera worker will stop")
        return
    interval = getattr(config, "DETECTION_INTERVAL", config.DETECTION_INTERVAL_SECONDS)
    reconciler = ShelfReconciler()
    log.info("YOLO shelf worker started; one frame every %ss", interval)
    try:
        while not stop_event.is_set():
            cycle_started = time.monotonic()
            observation = detector.next_counts()
            if observation is not None:
                counts, unknown = observation
                changed = reconciler.reconcile(counts)
                reconciler.report_unknown(unknown)
                # Alert evaluation is synchronous, in this same detection cycle.
                if on_cycle:
                    try:
                        on_cycle(changed)
                    except Exception:
                        log.exception("Camera-cycle callback failed; continuing monitoring")
            stop_event.wait(max(0, cycle_started + interval - time.monotonic()))
    finally:
        detector.close()
