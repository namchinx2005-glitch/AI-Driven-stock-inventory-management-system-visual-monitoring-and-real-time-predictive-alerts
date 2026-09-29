# AI-Driven Inventory Management System — Prototype

Implements the architecture in Chapter 3: a Flask + SQLite backend (detection worker,
moving-average + LSTM forecasting, multi-level alerting) and a Flask/Jinja dashboard.

## Quick start — real camera + YOLO26 (this must run on your own laptop)

**Important: this runs locally on your machine, not in a cloud sandbox.** I (Claude) can
write and test this code, but I have no access to your laptop's webcam — you need to run
these steps yourself, in a normal terminal on the machine with the camera attached.

**1. Install dependencies**
```bash
cd backend
pip install -r requirements.txt      # now includes opencv-python + ultralytics
```

**2. Calibrate your shelf regions** — the placeholder boxes in `config.py` almost
certainly don't match your real shelf. Run:
```bash
python calibrate_regions.py
```
This opens your webcam, grabs one frame with a coordinate grid drawn over it, and saves
`calibration_frame.jpg`. Open that image, read off the (x1, y1, x2, y2) pixel box around
each product's shelf spot, and paste those numbers into `SHELF_REGIONS` in `config.py`.

**3. Seed sales history and start the backend**
```bash
python seed_demo_data.py
python app.py
```
The dashboard owns the laptop webcam continuously after **Start camera** is selected. It keeps
the camera stream and its two-second scan loop running when the operator switches between
Dashboard, POS, Inventory, and Analytics; a small live preview remains visible off the Camera
page. It establishes a three-frame baseline, then applies stable additions and removals to
inventory. For an unattended shelf camera independent of a browser tab, attach a separate
camera and set `START_CAMERA_WORKER_ON_BOOT = True`; do not have the browser and worker open
the same physical camera. The first run will download the YOLO26 Nano weights automatically (`yolo26n.pt`, a few MB) —
that needs an internet connection once, then it's cached locally. If `cap.isOpened()` fails,
check `CAMERA_INDEX` in `config.py` (0 is the default/built-in camera; try 1 if you have an
external webcam plugged in), close any other app using the camera, and check your OS's
camera permission settings for your terminal/Python.

**4. Open the Jinja dashboard**

Open http://localhost:5000 in a modern browser on the same machine. The dashboard is served
directly by Flask; Vite, Node, and the old React build are no longer required. Browser camera
permission normally requires `localhost` or HTTPS, so use `http://localhost:5000` rather than
a LAN IP when using the laptop webcam. The dashboard refreshes inventory and alerts every five
seconds and scans camera frames every two seconds.

## If you just want to demo the UI without a camera

Set `DETECTION_SOURCE = "simulated"` in `config.py` — no webcam, no `opencv-python`/
`ultralytics` needed, everything else works identically.

## Switching on SMS and email alerts

Critical low-stock alerts are sent to `+263784005655` by Textbee and to
`namchinx2005@gmail.com` by email. They are triggered after a POS sale, a stock-count update,
or a confirmed camera count, and repeat no more than once an hour per product.

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
