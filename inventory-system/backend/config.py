"""
Central configuration for the inventory system.

Model: fine-tuned YOLO26 Nano shelf-product model.
Interval: 2 seconds, per Ch1 §1.5 Objective 1.
"""

import os


def _load_local_env() -> None:
    """Load backend/.env for local development without overriding real env vars."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


_load_local_env()

DETECTION_MODEL_NAME = "YOLO26n / custom shelf dataset"
# Put the fine-tuned `yolo26n.pt` in backend/ before enabling camera inference.
# COCO weights alone cannot identify salt or other branded groceries; train the
# model using your labelled shelf-product dataset before production use.
YOLO_MODEL_PATH = os.path.join(os.path.dirname(__file__), "yolo26n.pt")
COCO_CLASSES_PATH = "coco_classes.txt"  # COCO dataset classes file

# --- Timing ---
DETECTION_INTERVAL_SECONDS = 2      # camera capture / detection cycle interval (Objective 1)
DETECTION_INTERVAL = DETECTION_INTERVAL_SECONDS  # worker-specification alias
# A count must be seen in this many consecutive frames before it is treated as
# a real shelf change. This prevents a person or an occluded item causing a
# stock adjustment.
STABLE_COUNT_CYCLES = 3
UNKNOWN_ITEM_ALERT_COOLDOWN_SECONDS = 300
DASHBOARD_POLL_SECONDS = 5          # frontend polling interval
SMS_DISPATCH_BUDGET_SECONDS = 10    # target ceiling for Objective 4

# --- Detection ---
CONFIDENCE_THRESHOLD = 0.35
# Expanded COCO classes relevant for retail inventory
COUNTABLE_COCO_CLASSES = {
    "bottle", "cup", "wine glass", "cup", "fork", "knife", "spoon", "bowl", 
    "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", 
    "pizza", "donut", "cake", "book", "cell phone", "box", "backpack", "handbag", 
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", 
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket"
}
# Automatic stock movements should normally use a fine-tuned model whose class
# labels match a region's product ID/model_labels. Leave this false so a COCO
# class such as "bottle" is never mistaken for a specific SKU.
ALLOW_GENERIC_COCO_COUNTING = False

# --- Shelf regions: pixel-space rectangles mapped to product IDs ---
# Add ``model_labels`` when the training label differs from product_id, e.g.:
# "salt_1kg": {"box": (40, 40, 400, 680), "label": "Salt 1kg",
#              "model_labels": ["Salt 1kg", "salt_1kg"]}
# Coordinates are in a 1280x720 frame (720p, matching Ch3 Table 3.1's camera spec).
# These are placeholder boxes for a 3-lane shelf — walk through the calibration
# steps in the README before your first real run to set these to your actual shelf.
SHELF_REGIONS = {
    "sugar_2kg":   {"box": (40, 40, 400, 680), "label": "Sugar 2kg"},
    "salt_1kg":    {"box": (440, 40, 800, 680), "label": "Salt 1kg"},
    "cooking_oil": {"box": (840, 40, 1200, 680), "label": "Cooking Oil 2L"},
    "minute_maid_400ml": {'box': (862, 8, 1279, 249), 'label': 'Minute Maid 400ml'},
    "rice 2kg": {"box": (0, 1, 1280, 720), 'label': "rice 2kg32"},
}

# --- Forecasting ---
BURN_RATE_WINDOW_DAYS = 7
LSTM_WINDOW_SIZE = 5
LSTM_MIN_DAYS_REQUIRED = 10

# --- Alerting thresholds (per product; falls back to DEFAULT if not listed) ---
DEFAULT_SAFETY_THRESHOLD = 3
DEFAULT_WARNING_BUFFER = 3
ALERT_COOLDOWN_SECONDS = 1800  # 30 minutes between repeat alerts for the same product

# --- Alert delivery ---
# Textbee sends SMS through the registered Android device and its SIM.  Keep
# the API key in the environment instead of committing it to source control.
# Without it, the SMS channel stays in dry-run mode and is only logged.
TEXTBEE_API_KEY = os.getenv("TEXTBEE_API_KEY", "")
TEXTBEE_DEVICE_ID = os.getenv("TEXTBEE_DEVICE_ID", "6abb8cb6842e7dc338d8ffc1")
ALERT_PHONE_NUMBER = os.getenv("ALERT_PHONE_NUMBER", "+263784005655")
TEXTBEE_API_URL = "https://api.textbee.dev/api/v1/gateway/send-sms"

# Gmail is the default email provider.  Set SMTP_PASSWORD to a Gmail App
# Password (not the normal Gmail password) before email delivery is enabled.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").strip().lower() in {"1", "true", "yes", "on"}
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "namchinx2005@gmail.com")
# Google displays App Passwords in groups of four. Strip display spaces so
# either the grouped or plain 16-character form works when set in the shell.
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "namchinx2005@gmail.com")

# --- Detection source: "simulated" (no camera needed) or "camera" (real webcam + YOLO26) ---
DETECTION_SOURCE = "camera"
CAMERA_INDEX = 0
CAMERA_FALLBACK_INDICES = [0, 1, 2]
# Browser Camera Monitor owns the laptop webcam by default. Enable this only
# for a dedicated, server-side shelf camera that is not used by the browser.
# Keep a dedicated shelf camera running whenever the backend is running.
# Do not open the same physical camera in the browser Camera Monitor as well.
# The Jinja dashboard owns the webcam by default.  This prevents the backend
# and browser fighting over one laptop camera.  Set this to True only when a
# separate dedicated shelf camera is attached to the backend machine.
START_CAMERA_WORKER_ON_BOOT = False
