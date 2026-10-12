"""Explain why the shelf camera is not counting a product.

Run from the backend folder, with Flask stopped and the browser camera off
(only one program can use the webcam at a time):

    python diagnose_camera.py                  # grab one frame from the webcam
    python diagnose_camera.py --image shelf.jpg
    python diagnose_camera.py --show           # also draw regions + boxes in a window

It prints, in order: which weights file the app loads, what classes that model
knows, whether each shelf region's label and product exist, and for every
object the model sees (even at very low confidence) whether the app would
count it and, if not, exactly why.  Nothing is saved to disk and inventory is
never changed.
"""
import argparse
import difflib
import os
import sys
import time

import config
import database
from camera_worker import _name_for, point_in_region

try:  # newer camera_worker: ignores case, spaces, hyphens and underscores
    from camera_worker import label_matches, normalize_label
    TOLERANT_LABELS = True
except ImportError:  # older camera_worker: the label must match exactly
    TOLERANT_LABELS = False

    def normalize_label(label):
        return str(label)

    def label_matches(label, expected):
        return label in set(expected)

PRETRAINED_WEIGHTS = {"yolo26n.pt", "yolo11n.pt", "yolov8n.pt", "yolo11s.pt", "yolov8s.pt"}
FRAME_W, FRAME_H = 1280, 720   # the space shelf regions are stored in
LOW_CONFIDENCE = 0.05          # shown for diagnosis only; counting uses config


def results_to_detections(results):
    """Turn Ultralytics results into plain dicts (keeps analyse() testable)."""
    detections = []
    for box in results.boxes:
        coords = box.xyxy[0]
        x1, y1, x2, y2 = coords.tolist() if hasattr(coords, "tolist") else coords
        detections.append({"label": _name_for(results, int(box.cls[0])),
                           "conf": float(box.conf[0]), "box": (x1, y1, x2, y2)})
    return detections


def analyse(detections, frame_shape, regions, threshold):
    """One row per detection: would the app count it, and if not, why not."""
    height, width = frame_shape[:2]
    rows = []
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        cx, cy = (x1 + x2) / 2 * FRAME_W / width, (y1 + y2) / 2 * FRAME_H / height
        region_id = next((pid for pid, region in regions.items() if point_in_region(cx, cy, region)), None)
        row = {**det, "cx": cx, "cy": cy, "region": region_id, "counted": False}
        if det["conf"] < threshold:
            row["reason"] = f"confidence {det['conf']:.2f} is below CONFIDENCE_THRESHOLD ({threshold})"
        elif region_id is None:
            row["reason"] = f"its centre ({cx:.0f}, {cy:.0f}) is outside every shelf region"
        else:
            expected = list(regions[region_id].get("model_labels", [region_id]))
            if label_matches(det["label"], expected):
                row["counted"] = True
                row["reason"] = f"COUNTED for {region_id}"
            else:
                row["reason"] = f"label '{det['label']}' does not match region {region_id} (expects {expected})"
        rows.append(row)
    return rows


def verdict(rows, threshold):
    if not rows:
        return ["Nothing was detected, even at a very low confidence. The model is not recognising the "
                "product in this frame: check the weights file above, the lighting, and that the "
                "product is clearly in view."]
    confident = [r for r in rows if r["conf"] >= threshold]
    if not confident:
        best = max(r["conf"] for r in rows)
        return [f"Objects were detected, but the best confidence is {best:.2f}, below "
                f"CONFIDENCE_THRESHOLD ({threshold}). More and more varied training images are the real "
                "fix; lowering the threshold in config.py is only a stopgap."]
    if any(r["counted"] for r in rows):
        return ["At least one detection is counted, so the model and region are working. Note the first "
                "stable reading only sets a baseline; stock changes when the count changes afterwards."]
    hints = []
    if any(r["region"] is not None for r in confident):
        hints.append("A confident detection is inside a region but its label does not match. Set "
                     "\"model_labels\" for that region to the exact class name printed above.")
    if any(r["region"] is None for r in confident):
        hints.append("A confident detection is outside every region. Redraw the region where the product "
                     "really appears (use --show to see both).")
    return hints


def label_problems(names, regions):
    class_names = list(names.values()) if hasattr(names, "values") else list(names)
    problems = []
    for pid, region in regions.items():
        expected = list(region.get("model_labels", [pid]))
        if any(label_matches(name, expected) for name in class_names):
            continue
        close = difflib.get_close_matches(normalize_label(pid), [normalize_label(n) for n in class_names], n=1, cutoff=0.5)
        hint = f" Closest model class: '{close[0]}'." if close else ""
        problems.append(f"Region '{pid}' expects {expected} but the model has no such class.{hint} "
                        "Add the model's exact class name to \"model_labels\".")
    return problems


def product_problems(regions):
    problems = []
    for pid in regions:
        try:
            exists = bool(database.get_product(pid))
        except Exception as exc:  # unreadable DB should not hide the other checks
            return [f"Could not read inventory.db ({exc}). Run this from the backend folder."]
        if not exists:
            problems.append(f"Region '{pid}' has no product with that product_id in the database, so "
                            "counts for it are ignored. Create the product with exactly this ID.")
    return problems


def draw(frame, rows, regions):
    import cv2
    scale_x, scale_y = frame.shape[1] / FRAME_W, frame.shape[0] / FRAME_H
    for pid, region in regions.items():
        x1, y1, x2, y2 = region.get("box", region)
        p1, p2 = (int(x1 * scale_x), int(y1 * scale_y)), (int(x2 * scale_x), int(y2 * scale_y))
        cv2.rectangle(frame, p1, p2, (255, 140, 40), 2)
        cv2.putText(frame, f"region: {pid}", (p1[0] + 4, p1[1] + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 140, 40), 2)
    for row in rows:
        x1, y1, x2, y2 = (int(v) for v in row["box"])
        color = (80, 200, 80) if row["counted"] else (60, 60, 230)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{row['label']} {row['conf']:.2f}", (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return frame


def grab_frame(cv2, args):
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            sys.exit(f"Could not read the image: {args.image}")
        return frame
    index = config.CAMERA_INDEX if args.camera is None else args.camera
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    if not cap.isOpened():
        cap.release()
        sys.exit(f"Could not open camera {index}. Stop Flask and close any browser tab using the "
                 "camera, or pass --camera 1 / --image shelf.jpg.")
    try:
        frame = None
        for _ in range(8):  # the first frames of a webcam are often dark
            ok, frame = cap.read()
            time.sleep(0.1)
            if not ok:
                sys.exit("The camera opened but returned no frame.")
        return frame
    finally:
        cap.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", help="analyse this picture instead of the webcam")
    parser.add_argument("--camera", type=int, help="camera index (default: config.CAMERA_INDEX)")
    parser.add_argument("--show", action="store_true", help="show regions and detections in a window")
    args = parser.parse_args()
    regions = config.SHELF_REGIONS

    print("== 1. Weights file ==")
    path = config.YOLO_MODEL_PATH
    print(f"The app loads: {path}")
    if not os.path.exists(path):
        sys.exit("  PROBLEM: that file does not exist. Copy your trained best.pt there or fix YOLO_MODEL_PATH in config.py.")
    stat = os.stat(path)
    print(f"  size {stat.st_size / 1e6:.1f} MB, modified {time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))}")
    if os.path.basename(path).lower() in PRETRAINED_WEIGHTS:
        print("  PROBLEM: this is a pretrained general model, not the one you trained. It cannot know your\n"
              "  products. Copy your trained best.pt into the backend folder and point YOLO_MODEL_PATH at it.")
    print(f"  label matching: {'ignores case/spaces/hyphens' if TOLERANT_LABELS else 'EXACT (older camera_worker.py)'}")

    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as exc:
        sys.exit(f"Missing package ({exc}). Run: pip install -r requirements.txt")
    model = YOLO(path)
    names = model.names
    class_names = list(names.values()) if hasattr(names, "values") else list(names)
    print(f"\n== 2. Classes in this model ({len(class_names)}) ==")
    print(", ".join(str(n) for n in class_names[:40]) + (" ..." if len(class_names) > 40 else ""))

    print("\n== 3. Shelf regions ==")
    if not regions:
        print("  PROBLEM: SHELF_REGIONS in config.py is empty, so nothing can be counted.")
    for pid, region in regions.items():
        print(f"  {pid}: box {region.get('box')}, expects {list(region.get('model_labels', [pid]))}")
    for problem in label_problems(names, regions) + product_problems(regions):
        print("  PROBLEM:", problem)

    print("\n== 4. One frame ==")
    frame = grab_frame(cv2, args)
    height, width = frame.shape[:2]
    print(f"Frame size {width}x{height}")
    if abs(width / height - FRAME_W / FRAME_H) > 0.02:
        print("  NOTE: not 16:9. Regions are scaled from a 1280x720 frame, so redraw them with the\n"
              "  current calibrate_regions.py (it now stores boxes in that space whatever the camera size).")
    result = model(frame, conf=LOW_CONFIDENCE, verbose=False)[0]
    rows = analyse(results_to_detections(result), frame.shape, regions, config.CONFIDENCE_THRESHOLD)
    if rows:
        print(f"{'label':<22}{'conf':>6}  {'centre (1280x720)':<20}{'region':<18}result")
        for r in sorted(rows, key=lambda r: -r["conf"]):
            print(f"{r['label']:<22}{r['conf']:>6.2f}  ({r['cx']:>5.0f},{r['cy']:>5.0f}){'':<7}{str(r['region']):<18}{r['reason']}")
    else:
        print("The model detected nothing, even at confidence 0.05.")

    print("\n== What this means ==")
    for line in verdict(rows, config.CONFIDENCE_THRESHOLD):
        print("-", line)

    if args.show:
        cv2.imshow("diagnose_camera: orange = regions, green = counted, red = not counted (any key to close)", draw(frame, rows, regions))
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
