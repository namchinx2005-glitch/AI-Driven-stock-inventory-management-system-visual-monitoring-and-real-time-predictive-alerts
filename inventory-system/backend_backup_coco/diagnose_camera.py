"""Inspect low-confidence webcam detections without changing inventory.

Stop the browser camera first, then run ``python diagnose_camera.py --show``.
The script draws detections at 5% confidence and prints them to the terminal.
It never writes frames or stock records to disk.
"""
import argparse

import config


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose YOLO webcam detections")
    parser.add_argument("--camera-index", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--confidence", type=float, default=0.05,
                        help="Minimum confidence to display (default: 0.05)")
    parser.add_argument("--show", action="store_true",
                        help="Show annotated live video; press q or Esc to stop")
    return parser.parse_args()


def main():
    args = parse_args()
    if not 0 < args.confidence < 1:
        raise SystemExit("--confidence must be between 0 and 1")

    import cv2
    from ultralytics import YOLO

    model = YOLO(config.YOLO_MODEL_PATH)
    print(f"Model: {config.YOLO_MODEL_PATH}")
    print(f"Classes: {model.names}")
    print(f"Displaying detections at confidence >= {args.confidence:.0%}")

    camera = cv2.VideoCapture(args.camera_index)
    if not camera.isOpened():
        camera.release()
        raise SystemExit(f"Could not open camera index {args.camera_index}. Stop the browser camera and try again.")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                raise SystemExit("Camera did not return a frame")
            result = model(frame, conf=args.confidence, verbose=False)[0]
            found = []
            for box in result.boxes:
                label = str(result.names[int(box.cls[0])])
                confidence = float(box.conf[0])
                found.append(f"{label} ({confidence:.1%})")
            print("Detections: " + (", ".join(found) if found else "none"))

            if not args.show:
                return
            cv2.imshow("YOLO camera diagnostic — q/Esc to close", result.plot())
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                return
    finally:
        camera.release()
        if args.show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
