"""Inspect custom and COCO detections without changing inventory or saving frames."""
import argparse

import config
import database
from camera_worker import explain_detection, warn_region_configuration
from detector import box_iou, get_detector, normalize_label


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose custom and COCO shelf detections")
    parser.add_argument("--camera-index", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--confidence", type=float, default=0.01,
                        help="Low-confidence candidate floor for diagnosis (default: 0.01)")
    parser.add_argument("--image", help="Inspect a still image instead of opening the camera")
    parser.add_argument("--show", action="store_true",
                        help="Show annotated camera/image; press q or Esc to close")
    return parser.parse_args()


def _print_model_info(detector):
    custom = detector.custom_model
    coco = detector.coco_model
    print(f"Custom weights: {detector._absolute(detector.custom_path)}")
    print(f"Custom classes: {custom.names}")
    if coco is None:
        print(f"COCO weights: unavailable ({detector._absolute(detector.coco_path)})")
        print("COCO classes: unavailable; custom-model detections remain enabled")
    else:
        print(f"COCO weights: {detector._absolute(detector.coco_path)}")
        print(f"COCO classes: {coco.names}")


def _inspect_frame(frame, detector, cv2, args):
    raw = detector.raw_detect(frame, confidence=args.confidence)
    custom = [item for item in raw if item["source"] == "custom" and
              item["conf"] >= config.CUSTOM_CONFIDENCE_THRESHOLD]
    print(f"Detections in frame ({len(raw)} candidate(s)):")
    for detection in raw:
        counted, reason = explain_detection(detection, frame.shape)
        if (detection["source"] == "coco" and
                normalize_label(detection["label"]) in config.COCO_ALLOWED_CLASSES and
                detection["conf"] >= config.COCO_CONFIDENCE_THRESHOLD and
                any(box_iou(detection["box"], item["box"]) > 0.5 for item in custom)):
            counted, reason = False, "deduplicated in favor of overlapping custom detection"
        status = "COUNTED" if counted else f"NOT COUNTED — {reason}"
        print(f"  {detection['source']} | {detection['label']} | "
              f"confidence={detection['conf']:.1%} | {status}")

    if args.show:
        annotated = frame.copy()
        for detection in raw:
            x1, y1, x2, y2 = (int(value) for value in detection["box"])
            counted, reason = explain_detection(detection, frame.shape)
            if (detection["source"] == "coco" and
                    normalize_label(detection["label"]) in config.COCO_ALLOWED_CLASSES and
                    detection["conf"] >= config.COCO_CONFIDENCE_THRESHOLD and
                    any(box_iou(detection["box"], item["box"]) > 0.5 for item in custom)):
                counted, reason = False, "deduplicated in favor of custom"
            color = (65, 173, 255) if detection["source"] == "coco" else (54, 223, 150)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            caption = f"{detection['source']} {detection['label']} {detection['conf']:.0%}"
            if not counted:
                caption += f" ({reason})"
            cv2.putText(annotated, caption, (x1, max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        cv2.imshow("Dual-model camera diagnostic — q/Esc to close", annotated)
        return cv2.waitKey(0 if args.image else 1) & 0xFF
    return None


def main():
    args = parse_args()
    if not 0 < args.confidence < 1:
        raise SystemExit("--confidence must be between 0 and 1")

    import cv2

    database.init_db()
    warn_region_configuration()
    detector = get_detector()
    try:
        _print_model_info(detector)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    camera = None
    try:
        if args.image:
            frame = cv2.imread(args.image)
            if frame is None:
                raise SystemExit(f"Could not read image: {args.image}")
            _inspect_frame(frame, detector, cv2, args)
            return

        camera = cv2.VideoCapture(args.camera_index)
        if not camera.isOpened():
            raise SystemExit(f"Could not open camera index {args.camera_index}. Stop the browser camera and try again.")
        while True:
            ok, frame = camera.read()
            if not ok:
                raise SystemExit("Camera did not return a frame")
            key = _inspect_frame(frame, detector, cv2, args)
            if not args.show or key in (27, ord("q")):
                return
    finally:
        if camera is not None:
            camera.release()
        if args.show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
