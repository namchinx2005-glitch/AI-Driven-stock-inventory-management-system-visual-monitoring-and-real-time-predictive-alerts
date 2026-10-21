"""
Model: fine-tuned custom shelf-product detector.
Interval: 2 seconds, per Ch1 §1.5 Objective 1.
"""

import os
from dotenv import load_dotenv


# Keep deployment-provided variables authoritative while loading backend/.env
# automatically for local development.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)

DETECTION_MODEL_NAME = "Custom shelf-product detector + COCO fruits"
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_MODEL_PATH = os.getenv("CUSTOM_MODEL_PATH", os.path.join(BACKEND_DIR, "best.pt"))
COCO_MODEL_PATH = os.getenv("COCO_MODEL_PATH", os.path.join(BACKEND_DIR, "yolo26n.pt"))
# Compatibility alias for integrations that still use the old setting.
YOLO_MODEL_PATH = CUSTOM_MODEL_PATH

# --- Timing ---
DETECTION_INTERVAL_SECONDS = 2      # camera capture / detection cycle interval (Objective 1)
DETECTION_INTERVAL = DETECTION_INTERVAL_SECONDS  # worker-specification alias
# A count must be seen in this many consecutive frames before it is treated as
# a real shelf change. This prevents an occluded item causing a stock adjustment.
STABLE_COUNT_CYCLES = 3
UNKNOWN_ITEM_ALERT_COOLDOWN_SECONDS = 300
DASHBOARD_POLL_SECONDS = 5          # frontend polling interval
SMS_DISPATCH_BUDGET_SECONDS = 10    # target ceiling for Objective 4

# --- Detection ---
CUSTOM_CONFIDENCE_THRESHOLD = 0.35
COCO_CONFIDENCE_THRESHOLD = 0.40
CONFIDENCE_THRESHOLD = CUSTOM_CONFIDENCE_THRESHOLD
CUSTOM_MODEL_CLASSES = ("Gloria_biscuits", "Gunanzi_snack", "Mirinda_apple")
COCO_ALLOWED_CLASSES = {"apple", "banana", "orange"}
ALLOW_GENERIC_COCO_COUNTING = False
# --- Shelf regions: pixel-space rectangles mapped to product IDs ---
# Coordinates are in a 1280x720 frame (720p, matching Ch3 Table 3.1's camera spec).
# Draw actual shelf boxes with calibrate_regions.py. Region keys are product IDs;
# model_labels maps a product to one or more unchanged model class names.
SHELF_REGIONS = {
	"gloria-biscuits": {
		"box": (66, 2, 569, 224),
		"model_labels": ["gloria_biscuits"],
	},
	"gunanzi-snacks": {
		"box": (106, 233, 546, 474),
		"model_labels": ["gunanzi_snack"],
	},
	"mirinda-apple": {
		"box": (78, 496, 558, 720),
		"model_labels": ["mirinda_apple"],
	},
	"apple": {
		"box": (587, 24, 1034, 258),
		"model_labels": ["apple"],
	},
	"banana": {
		"box": (580, 264, 910, 476),
		"model_labels": ["banana"],
	},
	"orange": {
		"box": (593, 493, 1002, 713),
		"model_labels": ["orange"],
	},
}

# --- Forecasting ---
BURN_RATE_WINDOW_DAYS = 7
LSTM_WINDOW_SIZE = 5
LSTM_MIN_DAYS_REQUIRED = 10

# --- Restock intelligence ---
# Reorder targets cover supplier lead time plus a safety buffer. Seasonal
# beverage adjustments are evidence-based and remain neutral until enough
# observed sales data exists for a comparison.
RESTOCK_LOOKBACK_DAYS = 30
RESTOCK_LEAD_TIME_DAYS = 7
RESTOCK_SAFETY_DAYS = 5
SEASONAL_VALIDATION_MIN_ACTIVE_DAYS = 14

# --- Alerting thresholds (per product; falls back to DEFAULT if not listed) ---
DEFAULT_SAFETY_THRESHOLD = 3
DEFAULT_WARNING_BUFFER = 3
# A completely empty shelf is an urgent risk alert.  Low (but non-zero) stock
# remains a warning.  These are deliberately separate so a critical alert is
# not delayed by a prior warning for the same SKU.
CRITICAL_ALERT_REMINDER_SECONDS = int(os.getenv("CRITICAL_ALERT_REMINDER_SECONDS", "600"))
WARNING_ALERT_REMINDER_SECONDS = int(os.getenv("WARNING_ALERT_REMINDER_SECONDS", "1800"))
# Check persisted inventory even when no POS sale or camera detection occurs;
# this makes reminder delivery independent of user activity.
LOW_STOCK_ALERT_SCAN_SECONDS = int(os.getenv("LOW_STOCK_ALERT_SCAN_SECONDS", "60"))

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

# Authentication --- set this in .env for every non-development deployment.
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-this-secret")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# --- Detection source: "simulated" (no camera needed) or "camera" (real webcam + YOLO) ---
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
