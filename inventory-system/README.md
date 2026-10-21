# AI-Driven Inventory Management System — Prototype

Implements the architecture in Chapter 3: a Flask + SQLite backend (detection worker,
moving-average + LSTM forecasting, multi-level alerting) and a Flask/Jinja dashboard.

## Quick start — dual-model shelf detection

Run the app locally on the machine that has the webcam. `best.pt` must be your
custom Roboflow-trained weights and should be placed in `backend/best.pt`.
`yolo26n.pt` is the default COCO weights file; if it is not present, the backend
will try `yolo11n.pt`. Missing COCO weights disable fruit detections only;
custom-model inference continues. The COCO detector keeps only apple, banana,
and orange. The custom model keeps its original class names:
`Gloria_biscuits`, `Gunanzi_snack`, and `Mirinda_apple`.

The six region IDs are `gloria_biscuits`, `gunanzi_snack`, `mirinda_apple`,
`apple`, `banana`, and `orange`. Create matching products in the database first.
`SHELF_REGIONS` intentionally starts empty: no coordinates are guessed. Draw
and configure one region per product with `python calibrate_regions.py`, run
once for each of the six IDs. For each, enter the exact model label:
`Gloria_biscuits`, `Gunanzi_snack`, `Mirinda_apple`, `apple`, `banana`, or
`orange`. Copy each printed box and `model_labels` entry into
`backend/config.py` under `SHELF_REGIONS`. Boxes are converted into 1280x720
coordinates regardless of the camera's actual resolution.

Start the app from `backend` with `python app.py`, open `http://localhost:5000`,
and select **Start camera**. The reconciler waits for three stable readings to
establish its baseline, then stable increases add stock and stable decreases
record sales and reduce stock. To inspect detection output without changing
inventory, stop the browser camera and run `python diagnose_camera.py --show`.
Use `python diagnose_camera.py --image path/to/image.jpg` to inspect a still
image. Both diagnostics print model paths/classes and the reason a candidate is
or is not counted.

For dependencies, run `pip install -r requirements.txt` in the backend
environment. Do not enable both the browser camera and the background camera
worker on the same physical webcam. For a dedicated worker camera, set
`START_CAMERA_WORKER_ON_BOOT = True` in `config.py`.

## If you just want to demo the UI without a camera

Set `DETECTION_SOURCE = "simulated"` in `config.py` — no webcam, no `opencv-python`/
`ultralytics` needed, everything else works identically.

## Switching on SMS and email alerts

Warning and critical low-stock alerts are sent to `+263784005655` by Textbee and to
`namchinx2005@gmail.com` by email. They are triggered after a POS sale, a stock-count update,
or a confirmed camera count, and a background worker continues checking inventory every minute.
An out-of-stock (**CRITICAL/RISK**) item is re-alerted every **10 minutes**; a low-but-nonzero
(**WARNING**) item is re-alerted every **30 minutes**, per product. Entering critical stock
always sends an immediate escalation, even if a warning was sent recently.

Before starting the backend, set the delivery credentials in your terminal. Do not put these
secrets in `config.py`:

```bash
export TEXTBEE_API_KEY='your_textbee_api_key'
# Optional: this installation defaults to the registered Textbee device ID.
export TEXTBEE_DEVICE_ID='your_textbee_device_id'
# Gmail accepts the 16-character App Password with or without its display spaces.
export SMTP_PASSWORD='your_16_character_gmail_app_password'
python app.py
```

For Gmail, create an App Password after enabling two-step verification, then use that App
Password for `SMTP_PASSWORD`; do not use your normal Gmail password. You can override the
recipients or Gmail settings with `ALERT_PHONE_NUMBER`, `ALERT_EMAIL_TO`, `SMTP_HOST`,
`SMTP_PORT`, and `SMTP_USERNAME` environment variables. Textbee must have its Android device
online and enabled for a queued SMS to reach the phone.

Gmail is configured for `smtp.gmail.com` over SSL port `465`. Until the required Textbee or
SMTP credentials are set, that channel runs in **dry-run mode**:
the alert is logged and displayed in the dashboard but is not delivered.

## Automated restock intelligence

Product categories are normalized on startup; `Drinks`, `drink`, and recognised juice/water
names become **Beverages**. Reorder recommendations use the last 30 days of recorded sales,
seven supplier lead-time days, and five safety-stock days. Record every POS sale and delivery,
then check each suggestion's data-quality note before ordering.

Zimbabwe beverage seasonality is not a fixed assumption: the system applies a multiplier only
after it has at least 14 observed beverage-sales days in both the current seasonal period and
neutral months. Until then the multiplier remains 1.00 and the dashboard explains why. A manager
or administrator should use **Mark this week reviewed** after reviewing quantities each week;
the review is stored for the current Monday-to-Sunday week.

## What maps to what in Chapter 3

| Chapter 3 section | File |
|---|---|
| §3.5.1 Region-based counting | `camera_worker.py` |
| §3.5.2 Burn rate & depletion forecasting | `forecasting.py` |
| §3.5.3 Multi-level alerting | `alerts.py` |
| §3.6.3 / Table 3.3 REST API | `app.py` |
| §3.4.2 Seeded sales data | `seed_demo_data.py` |
| §3.3.1 Client presentation layer | `backend/templates/dashboard.html` + `backend/static/dashboard.js` |
| Shelf calibration (not in Ch3 — added for real-world setup) | `calibrate_regions.py` |

## Resolved decisions (update Chapter 3 to match)

- **Model:** YOLO26 Nano (`config.DETECTION_MODEL_NAME = "YOLO26n"`). Replace every
  "YOLOv8" occurrence flagged in your Ch3 corrections with "YOLO26 Nano," including the
  reference list entry.
- **Detection interval:** 2 seconds (`config.DETECTION_INTERVAL_SECONDS = 2`), matching
  Objective 1. Update Ch3 §3.3.1 and §3.4.1 from "5-second" to "2-second" to match.

## Still open

- Ch1 §1.8.1 vs Ch3 Table 3.1 hardware spec conflict (i5 vs i7) — not yet resolved.
- Chapter 4 §4.2.3's latency test (dashboard refresh, on-screen alert, SMS dispatch) can be
  run directly against this prototype once real hardware is attached — the `alerts.py`
  module logs are the place to pull actual timestamps from for that test. With a 2-second
  detection interval, the alert-latency bound quoted in the corrected §3.5.3 is now
  "2 seconds plus Textbee API latency."
