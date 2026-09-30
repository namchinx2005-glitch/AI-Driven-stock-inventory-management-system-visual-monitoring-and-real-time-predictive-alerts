"""
Multi-Level Alerting (Ch3 §3.5.3, Algorithm 2) with the timing justification
added to the corrected §3.5.3: the check runs synchronously at the end of
every detection cycle, and dispatch (if any) happens inline in the same call —
no queue — so total latency is bounded by one detection interval (2 seconds,
per config.DETECTION_INTERVAL_SECONDS) plus Textbee API latency, comfortably
inside the 10-second budget in Objective 4 under normal network conditions.
"""
from datetime import datetime, timedelta
import json
import logging
import smtplib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from email.message import EmailMessage

import config
import database

log = logging.getLogger("alerts")

def _thresholds_for(product_id: str):
    # Per-product overrides could be added to config.SHELF_REGIONS later;
    # falls back to the defaults for now.
    return config.DEFAULT_SAFETY_THRESHOLD, config.DEFAULT_WARNING_BUFFER


def _label_for(product_id: str) -> str:
    region = config.SHELF_REGIONS.get(product_id)
    if region:
        return region["label"]
    product = database.get_product(product_id)
    return product["name"] if product else product_id


def _alert_text(product_id: str, current_stock: int, level: str) -> tuple[str, str]:
    label = _label_for(product_id)
    if level == "CRITICAL":
        return label, f"[Inventory Alert: CRITICAL] {label} has {current_stock} unit(s) remaining. Restock immediately."
    return label, f"[Inventory Alert: WARNING] {label} is low: {current_stock} unit(s) remaining. Please plan a restock."


def _reminder_interval(level: str) -> int:
    """Return the repeat interval for an alert severity."""
    if level == "CRITICAL":
        return config.CRITICAL_ALERT_REMINDER_SECONDS
    return config.WARNING_ALERT_REMINDER_SECONDS


def _dispatch_sms(product_id: str, current_stock: int, level: str) -> bool:
    _, message = _alert_text(product_id, current_stock, level)

    dry_run = not (config.TEXTBEE_API_KEY and config.TEXTBEE_DEVICE_ID and config.ALERT_PHONE_NUMBER)
    if dry_run:
        log.info("DRY-RUN SMS (Textbee not configured): %s", message)
        return False

    try:
        payload = json.dumps(
            {
                "recipients": [config.ALERT_PHONE_NUMBER],
                "message": message,
                "deviceId": config.TEXTBEE_DEVICE_ID,
            }
        ).encode("utf-8")
        request = Request(
            config.TEXTBEE_API_URL,
            data=payload,
            headers={"Content-Type": "application/json", "x-api-key": config.TEXTBEE_API_KEY},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                log.error("Textbee dispatch failed for %s: HTTP %s", product_id, response.status)
                return False
            # Textbee can accept the HTTP request but report that no recipient
            # was pushed to the Android gateway. Treat that as a failed send.
            result = json.loads(response.read().decode("utf-8") or "{}")
            result_data = result.get("data", result)
            failures = result_data.get("failureCount", 0) if isinstance(result_data, dict) else 0
            successes = result_data.get("successCount") if isinstance(result_data, dict) else None
            if failures or successes == 0:
                log.error("Textbee accepted no SMS for %s: %s", product_id, result)
                return False
        return True
    except HTTPError as exc:
        log.error("Textbee dispatch failed for %s: HTTP %s", product_id, exc.code)
        return False
    except URLError as exc:
        log.error("Textbee dispatch failed for %s: %s", product_id, exc.reason)
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Textbee dispatch failed for %s: %s", product_id, exc)
        return False


def _dispatch_email(product_id: str, current_stock: int, level: str) -> bool:
    """Send a warning or critical alert by email, or log it while unconfigured."""
    label, message = _alert_text(product_id, current_stock, level)
    if not (
        config.SMTP_HOST
        and config.ALERT_EMAIL_TO
        and config.SMTP_USERNAME
        and config.SMTP_PASSWORD
    ):
        log.info("DRY-RUN email: %s", message)
        return False
    try:
        email = EmailMessage()
        email["Subject"] = f"{level.title()} inventory alert — {label}"
        email["From"] = config.SMTP_USERNAME or "inventory@localhost"
        email["To"] = config.ALERT_EMAIL_TO
        email.set_content(message)
        smtp_class = smtplib.SMTP_SSL if config.SMTP_USE_SSL else smtplib.SMTP
        with smtp_class(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            if not config.SMTP_USE_SSL:
                smtp.starttls()
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            smtp.send_message(email)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Email dispatch failed for %s: %s", product_id, exc)
        return False


def evaluate_alerts(counts: dict):
    """
    Called once per detection cycle (see camera_worker.run_detection_loop's on_cycle
    hook), i.e. synchronously and inline — this is what gives the system its bounded
    alert latency described in the corrected Ch3 §3.5.3.
    """
    for product_id, current_stock in counts.items():
        _safety, buffer = _thresholds_for(product_id)

        # A risk/critical alert means the product is completely unavailable.
        # Any positive count inside the low-stock range is a warning instead.
        if current_stock <= 0:
            level = "CRITICAL"
        elif current_stock <= _safety + buffer:
            level = "WARNING"
        else:
            continue

        label = _label_for(product_id)
        message = f"{label}: {current_stock} units ({level})"

        # Level-specific cooldowns ensure that moving from WARNING to CRITICAL
        # always produces an immediate escalation. Critical means no units are
        # left and repeats every 10 minutes; warnings repeat every 30 minutes.
        sms_sent = False
        last_sent = database.get_last_alert_timestamp(product_id, level)
        if datetime.utcnow() - last_sent >= timedelta(seconds=_reminder_interval(level)):
            sms_sent = _dispatch_sms(product_id, current_stock, level)
            email_sent = _dispatch_email(product_id, current_stock, level)
            # Record the dispatch attempt, not just a successful response. This
            # preserves the 10/30-minute cadence if a provider is temporarily
            # unavailable instead of retrying every one-minute scan.
            database.update_alert_timestamp(product_id, level)
            database.record_alert(product_id, level, message, sms_sent)


def evaluate_current_inventory_alerts():
    """Evaluate every saved product count for the periodic reminder worker."""
    counts = {
        product["product_id"]: database.get_latest_count(product["product_id"]) or 0
        for product in database.get_all_products()
    }
    evaluate_alerts(counts)
