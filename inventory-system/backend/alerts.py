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


def _dispatch_sms(product_id: str, current_stock: int) -> bool:
    label = _label_for(product_id)
    message = f"[Inventory Alert] {label} is critically low: {current_stock} units remaining."

    dry_run = not (config.TEXTBEE_API_KEY and config.TEXTBEE_DEVICE_ID and config.ALERT_PHONE_NUMBER)
    if dry_run:
        log.info("DRY-RUN SMS (Textbee not configured): %s", message)
        return True  # counted as "sent" for demo/testing purposes; message is logged, not delivered

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


def _dispatch_email(product_id: str, current_stock: int) -> bool:
    """Send the same critical alert by email, or log it while unconfigured."""
    label = _label_for(product_id)
    message = f"Inventory alert: {label} is critically low ({current_stock} units remaining)."
    if not (
        config.SMTP_HOST
        and config.ALERT_EMAIL_TO
        and config.SMTP_USERNAME
        and config.SMTP_PASSWORD
    ):
        log.info("DRY-RUN email: %s", message)
        return True
    try:
        email = EmailMessage()
        email["Subject"] = f"Critical inventory alert — {label}"
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
        safety, buffer = _thresholds_for(product_id)

        if current_stock <= safety:
            level = "CRITICAL"
        elif current_stock <= safety + buffer:
            level = "WARNING"
        else:
            continue

        label = _label_for(product_id)
        message = f"{label}: {current_stock} units ({level})"

        sms_sent = False
        if level == "CRITICAL":
            last_sent = database.get_last_sms_timestamp(product_id)
            if datetime.utcnow() - last_sent >= timedelta(seconds=config.ALERT_COOLDOWN_SECONDS):
                sms_sent = _dispatch_sms(product_id, current_stock)
                _dispatch_email(product_id, current_stock)
                if sms_sent:
                    database.update_sms_timestamp(product_id)

        database.record_alert(product_id, level, message, sms_sent)
