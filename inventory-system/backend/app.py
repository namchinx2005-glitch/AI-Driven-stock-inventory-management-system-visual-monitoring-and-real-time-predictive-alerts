"""
API Gateway & Dispatch Layer (Ch3 §3.3.1, §3.6.3, Table 3.3).
Enhanced with POS, User Management, and Analytics endpoints.
Run: python app.py
Dashboard (dev) then talks to this on http://localhost:5000
"""
import logging
import threading
import base64
import binascii
import os
import math
from datetime import date, timedelta
from functools import wraps

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

import config
import database
import forecasting
import auth
from camera_worker import (
    ShelfReconciler,
    count_detections_per_region,
    run_detection_loop,
    unknown_detections_per_region,
)
from alerts import evaluate_alerts, evaluate_current_inventory_alerts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]}})

_stop_event = threading.Event()
# Used when the browser owns the camera. It gives the visible Camera Monitor
# the same stable-count reconciliation as the dedicated background worker.
_browser_shelf_reconciler = ShelfReconciler()


def _low_stock_reminder_loop():
    """Keep sending due low-stock reminders even when inventory is idle."""
    log.info("Low-stock email reminder worker started (checking every %s seconds).",
             config.LOW_STOCK_ALERT_SCAN_SECONDS)
    while not _stop_event.is_set():
        try:
            evaluate_current_inventory_alerts()
        except Exception:  # Keep the reminder worker alive after a transient failure.
            log.exception("Low-stock reminder scan failed")
        _stop_event.wait(config.LOW_STOCK_ALERT_SCAN_SECONDS)


@app.route("/")
def dashboard():
    """Server-rendered application shell.

    Views are switched client-side inside this one Jinja document.  Keeping
    the camera element outside the views is intentional: a running browser
    camera is not interrupted when an operator opens POS, inventory, or
    analytics.
    """
    return render_template("dashboard.html", poll_seconds=config.DASHBOARD_POLL_SECONDS,
                           detection_seconds=config.DETECTION_INTERVAL_SECONDS)


# Authentication decorator
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid authorization header"}), 401
        
        token = auth_header.split(' ')[1]
        payload = auth.verify_jwt_token(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        request.user = payload
        return f(*args, **kwargs)
    return decorated_function


def require_manager(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Manager endpoints are also authentication endpoints.  Previously this
        # decorator only looked for request.user, which is set by require_auth,
        # but those routes did not stack both decorators and therefore always
        # returned 403 even for a valid manager token.
        if not hasattr(request, 'user'):
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({"error": "Missing or invalid authorization header"}), 401
            payload = auth.verify_jwt_token(auth_header.split(' ', 1)[1])
            if not payload:
                return jsonify({"error": "Invalid or expired token"}), 401
            request.user = payload
        if not hasattr(request, 'user') or request.user.get('role') not in ('admin', 'manager'):
            return jsonify({"error": "Administrator or manager access required"}), 403
        return f(*args, **kwargs)
    return decorated_function


@app.route("/api/stock", methods=["GET", "OPTIONS"])
def api_stock():
    """Current count, burn rate and status per product."""
    if request.method == "OPTIONS":
        return "", 200
        
    out = []
    for product in database.get_all_products():
        pid = product["product_id"]
        prediction = forecasting.predict_depletion(pid)
        safety = config.DEFAULT_SAFETY_THRESHOLD
        buffer = config.DEFAULT_WARNING_BUFFER
        count = prediction["current_stock"]
        # CRITICAL/RISK is reserved for an empty shelf. Positive low stock is
        # a warning, matching the email reminder policy.
        status = "CRITICAL" if count <= 0 else "WARNING" if count <= safety + buffer else "HEALTHY"
        out.append(
            {
                "product_id": pid,
                "label": product["name"],
                "current_stock": count,
                "burn_rate_per_day": prediction["burn_rate"],
                "days_remaining": prediction["days_remaining"],
                "depletion_date": prediction["depletion_date"],
                "status": status,
            }
        )
    return jsonify(out)


@app.route("/api/alerts", methods=["GET", "OPTIONS"])
def api_alerts():
    """Recent on-screen alerts."""
    if request.method == "OPTIONS":
        return "", 200
    return jsonify(database.get_recent_alerts(limit=20))


@app.route("/api/restock-suggestions", methods=["GET", "OPTIONS"])
def api_restock_suggestions():
    """Rank reorder advice using on-hand stock, velocity, trend and season."""
    if request.method == "OPTIONS":
        return "", 200
        
    suggestions = []
    # Zimbabwe's hot/rainy retail period runs broadly September–March. The
    # seasonal uplift is deliberately limited to beverage-like catalog items;
    # sales velocity remains the main ordering signal.
    warm_season = date.today().month in (9, 10, 11, 12, 1, 2, 3)
    for product in database.get_all_products():
        pid = product["product_id"]
        prediction = forecasting.predict_depletion(pid)
        trend = database.get_sales_trend(pid)
        recent, previous = trend["recent"], trend["previous"]
        is_beverage = any(word in f"{product['name']} {product.get('category') or ''}".lower()
                          for word in ("drink", "juice", "water", "beverage", "soda"))
        seasonal_multiplier = 1.30 if warm_season and is_beverage else 1.0
        base_weekly_demand = max(prediction["burn_rate"] * 7, float(recent))
        suggested_quantity = max(0, math.ceil(base_weekly_demand * seasonal_multiplier - prediction["current_stock"]))
        trend_up = recent > previous and recent > 0
        if prediction["current_stock"] == 0:
            action = "Restock immediately — out of stock"
        elif suggested_quantity > 0:
            action = "Reorder now" if trend_up or prediction["days_remaining"] is not None and prediction["days_remaining"] <= 3 else "Plan a reorder"
        else:
            action = "Monitor"
        if suggested_quantity or prediction["current_stock"] == 0 or trend_up:
            suggestions.append(
                {
                    "product_id": pid,
                    "label": product["name"],
                    "days_remaining": prediction["days_remaining"],
                    "depletion_date": prediction["depletion_date"],
                    "suggested_quantity": suggested_quantity,
                    "recent_sales": recent,
                    "previous_sales": previous,
                    "seasonal_factor": "Hot/rainy-season beverage uplift" if warm_season and is_beverage else None,
                    "suggested_action": action,
                }
            )
    suggestions.sort(key=lambda s: (s["suggested_action"] != "Restock immediately — out of stock", -(s["suggested_quantity"] or 0), -s["recent_sales"]))
    return jsonify(suggestions)


@app.route("/api/burn-rate/<product_id>", methods=["GET", "OPTIONS"])
def api_burn_rate(product_id):
    """7-day sold units series for the trend chart."""
    if request.method == "OPTIONS":
        return "", 200
        
    if product_id not in config.SHELF_REGIONS:
        return jsonify({"error": "unknown product_id"}), 404
    daily = database.get_daily_sales(product_id, config.BURN_RATE_WINDOW_DAYS)
    return jsonify([{"day": d, "units_sold": qty} for d, qty in daily])


@app.route("/api/forecast-comparison/<product_id>", methods=["GET"])
def api_forecast_comparison(product_id):
    """Moving average vs LSTM prediction, side by side."""
    if product_id not in config.SHELF_REGIONS:
        return jsonify({"error": "unknown product_id"}), 404
    return jsonify(forecasting.forecast_comparison(product_id))


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "detection_source": config.DETECTION_SOURCE,
                    "model": config.DETECTION_MODEL_NAME,
                    "model_ready": os.path.exists(config.YOLO_MODEL_PATH),
                    "salt_supported_by_coco": False})


# Authentication endpoints
@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def api_login():
    """User login endpoint."""
    if request.method == "OPTIONS":
        return "", 200
        
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        log.info(f"Login attempt for username: {username}")
        
        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        
        user_data = auth.authenticate_user(username, password)
        if not user_data:
            log.warning(f"Failed login attempt for username: {username}")
            return jsonify({"error": "Invalid credentials"}), 401
        
        log.info(f"Successful login for username: {username}")
        token = auth.generate_jwt_token(user_data)
        return jsonify({
            "token": token,
            "user": user_data
        })
    except Exception as e:
        log.error(f"Login error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def api_me():
    """Get current user info."""
    return jsonify(request.user)


# Product management endpoints
@app.route("/api/products", methods=["GET"])
def api_products():
    """Get all products."""
    products = database.get_all_products()
    return jsonify(products)


@app.route("/api/products/<product_id>", methods=["GET"])
def api_product_detail(product_id):
    """Get product details."""
    product = database.get_product(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(product)


@app.route("/api/products", methods=["POST"])
@require_manager
def api_create_product():
    """Create a new product (manager only)."""
    data = request.get_json()
    required_fields = ['product_id', 'name', 'price']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400
    
    try:
        database.create_product(
            product_id=data['product_id'],
            name=data['name'],
            description=data.get('description'),
            price=float(data['price']),
            category=data.get('category'),
            sku=data.get('sku'),
            barcode=data.get('barcode'),
            image_url=data.get('image_url')
        )
        initial_stock = int(data.get('initial_stock') or 0)
        if initial_stock > 0:
            database.receive_stock(data['product_id'], initial_stock, 'manual_receipt', request.user['user_id'], 'Initial stock')
        else:
            database.set_stock_count(data['product_id'], 0, request.user['user_id'], 'Initial stock')
        return jsonify({"message": "Product created successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/products/<product_id>", methods=["PUT"])
@require_manager
def api_update_product(product_id):
    """Update product (manager only)."""
    data = request.get_json()
    if database.update_product(product_id, **data):
        return jsonify({"message": "Product updated successfully"})
    return jsonify({"error": "Product not found or update failed"}), 404


@app.route("/api/products/<product_id>", methods=["DELETE"])
@require_manager
def api_delete_product(product_id):
    """Delete product (manager only)."""
    database.delete_product(product_id)
    return jsonify({"message": "Product deleted successfully"})


# User management endpoints
@app.route("/api/users", methods=["GET"])
@require_manager
def api_users():
    """Get all users (manager only)."""
    users = database.get_all_users()
    # Remove password hashes from response
    safe_users = [{k: v for k, v in user.items() if k != 'password_hash'} for user in users]
    return jsonify(safe_users)


@app.route("/api/users", methods=["POST"])
@require_manager
def api_create_user():
    """Create a new user (manager only)."""
    data = request.get_json()
    required_fields = ['username', 'password', 'full_name', 'role']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400
    
    if data['role'] not in ['admin', 'manager', 'sales', 'accountant']:
        return jsonify({"error": "Invalid role"}), 400
    if request.user.get('role') == 'manager' and data['role'] == 'admin':
        return jsonify({"error": "Only an admin can create another admin"}), 403
    
    try:
        password_hash = auth.hash_password(data['password'])
        user_id = database.create_user(
            username=data['username'],
            password_hash=password_hash,
            full_name=data['full_name'],
            role=data['role']
        )
        return jsonify({"message": "User created successfully", "user_id": user_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@require_manager
def api_update_user(user_id):
    """Update user (manager only)."""
    data = request.get_json()
    target = database.get_user_by_id(user_id)
    if request.user.get('role') == 'manager' and (data.get('role') == 'admin' or (target and target.get('role') == 'admin')):
        return jsonify({"error": "Only an admin can manage an admin account"}), 403
    if database.update_user(user_id, **data):
        return jsonify({"message": "User updated successfully"})
    return jsonify({"error": "User not found or update failed"}), 404


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_manager
def api_delete_user(user_id):
    """Delete an account while protecting the acting user and administrators."""
    target = database.get_user_by_id(user_id)
    if not target:
        return jsonify({"error": "User not found"}), 404
    if user_id == request.user.get("user_id"):
        return jsonify({"error": "You cannot delete your own account"}), 400
    if request.user.get("role") != "admin" and target.get("role") == "admin":
        return jsonify({"error": "Only an admin can delete an administrator"}), 403
    if not database.delete_user(user_id):
        return jsonify({"error": "User could not be deleted"}), 400
    return jsonify({"message": "User deleted"})


# POS endpoints
@app.route("/api/pos/transaction", methods=["POST"])
@require_auth
def api_pos_transaction():
    """Create a POS transaction."""
    if request.user.get('role') not in ('admin', 'manager', 'sales', 'sales_person'):
        return jsonify({"error": "This role cannot process sales"}), 403
    data = request.get_json()
    required_fields = ['items', 'total_amount']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400
    
    try:
        transaction_id = database.create_pos_transaction(
            user_id=request.user['user_id'],
            items=data['items'],
            total_amount=float(data['total_amount']),
            payment_method=data.get('payment_method', 'cash')
        )
        evaluate_alerts({item['product_id']: database.get_latest_count(item['product_id']) or 0 for item in data['items']})
        receipt_items = database.get_transaction_items(transaction_id)
        receipt_total = sum(float(item["total_price"]) for item in receipt_items)
        return jsonify({"message": "Transaction created successfully", "transaction_id": transaction_id,
                        "receipt": {"system_name": "LedgerLens Inventory", "cashier": request.user.get('full_name', request.user['username']),
                                    "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                    "items": receipt_items, "total_amount": receipt_total,
                                    "payment_method": data.get('payment_method', 'cash')}}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pos/transactions", methods=["GET"])
@require_auth
def api_pos_transactions():
    """Get POS transactions."""
    limit = request.args.get('limit', 50, type=int)
    # Sales persons can only see their own transactions
    if request.user['role'] in ('sales', 'sales_person'):
        transactions = database.get_pos_transactions(limit=limit, user_id=request.user['user_id'])
    else:
        transactions = database.get_pos_transactions(limit=limit)
    return jsonify(transactions)


@app.route("/api/pos/transactions/<transaction_id>/items", methods=["GET"])
@require_auth
def api_transaction_items(transaction_id):
    """Get items for a specific transaction."""
    items = database.get_transaction_items(transaction_id)
    return jsonify(items)


@app.route("/api/inventory/receive", methods=["POST"])
@require_auth
def api_receive_stock():
    """Manual or camera-confirmed stock receipt; both paths are auditable."""
    if request.user.get('role') not in ('admin', 'manager', 'sales', 'sales_person'):
        return jsonify({"error": "This role cannot receive stock"}), 403
    data = request.get_json() or {}
    try:
        quantity = int(data.get('quantity', 0))
        source = data.get('source', 'manual')
        kind = 'camera_receipt' if source == 'camera' else 'manual_receipt'
        count = database.receive_stock(data.get('product_id', ''), quantity, kind,
                                       request.user['user_id'], data.get('note', ''))
        evaluate_alerts({data['product_id']: count})
        return jsonify({"message": "Stock received", "current_stock": count}), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/inventory/<product_id>/count", methods=["PUT"])
@require_manager
def api_set_stock_count(product_id):
    data = request.get_json() or {}
    try:
        count = database.set_stock_count(product_id, int(data.get('count')), request.user['user_id'], data.get('note', 'Manual stock count'))
        evaluate_alerts({product_id: count})
        return jsonify({"message": "Stock count saved", "current_stock": count})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/camera/scan", methods=["POST"])
@require_auth
def api_camera_scan():
    """Run the requested local YOLO model against a browser webcam frame."""
    data = request.get_json() or {}
    image = data.get('image', '')
    if not isinstance(image, str) or ',' not in image:
        return jsonify({"error": "A webcam image is required"}), 400
    try:
        header, encoded_image = image.split(',', 1)
        if not header.startswith('data:image/') or not encoded_image.strip():
            raise ValueError
        raw = base64.b64decode(encoded_image, validate=True)
        if not raw:
            raise ValueError
    except (ValueError, binascii.Error):
        return jsonify({"error": "The webcam frame was empty or invalid. Wait for the camera preview, then try again."}), 400
    if not os.path.exists(config.YOLO_MODEL_PATH):
        return jsonify({"error": "yolo26n.pt is not installed on the server. Camera receipt is available once the model file is added.",
                        "detections": [], "model_ready": False,
                        "salt_supported": False}), 503
    try:
        import cv2
        import numpy as np
        from ultralytics import YOLO
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return jsonify({"error": "The webcam frame could not be decoded. Wait for the camera preview, then try again."}), 400
        result = YOLO(config.YOLO_MODEL_PATH)(frame, verbose=False)[0]
        names = result.names
        detections = []
        for box in result.boxes:
            confidence = float(box.conf[0])
            if confidence < config.CONFIDENCE_THRESHOLD:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append({"label": names[int(box.cls[0])], "confidence": round(confidence, 3),
                               "box": [round(x1), round(y1), round(x2), round(y2)]})
        counts = count_detections_per_region(result, frame.shape)
        updates = _browser_shelf_reconciler.reconcile(counts)
        unknown = unknown_detections_per_region(result)
        _browser_shelf_reconciler.report_unknown(unknown)
        model_labels = {str(value).lower() for value in (names.values() if hasattr(names, 'values') else names)}
        salt_supported = "salt" in model_labels
        notice = (f"{len(detections)} objects detected. Salt is available in this fine-tuned model."
                  if salt_supported else f"{len(detections)} objects detected. This model has no salt class; confirm Salt manually until custom training is added.")
        if updates:
            update_text = ", ".join(f"{product_id}: {count}" for product_id, count in updates.items())
            notice = f"{notice} Inventory updated — {update_text}."
        elif unknown:
            notice = f"{notice} Unmapped item detected; inventory was not changed."
        return jsonify({"detections": detections, "model_ready": True, "salt_supported": salt_supported,
                        "inventory_updates": updates, "unknown_items": unknown, "notice": notice})
    except Exception as exc:
        log.exception("Camera scan failed")
        return jsonify({"error": f"Scan failed: {exc}"}), 500


# Analytics endpoints
@app.route("/api/analytics/most-purchased", methods=["GET"])
@require_auth
def api_most_purchased():
    """Get most purchased products."""
    days = request.args.get('days', 30, type=int)
    limit = request.args.get('limit', 10, type=int)
    products = database.get_most_purchased_products(days=days, limit=limit)
    return jsonify(products)


@app.route("/api/analytics/sales-analysis", methods=["GET"])
@require_auth
def api_sales_analysis():
    """Return sales by day, best day and top products for an inclusive range."""
    default_end = date.today()
    default_start = default_end - timedelta(days=29)
    try:
        start = date.fromisoformat(request.args.get("from", default_start.isoformat()))
        end = date.fromisoformat(request.args.get("to", default_end.isoformat()))
    except ValueError:
        return jsonify({"error": "Dates must use YYYY-MM-DD"}), 400
    if end < start or (end - start).days > 366:
        return jsonify({"error": "Choose a date range from 1 to 366 days"}), 400
    return jsonify(database.get_sales_analysis(start.isoformat(), end.isoformat()))


@app.route("/api/analytics/sales-by-category", methods=["GET"])
@require_auth
def api_sales_by_category():
    """Get sales breakdown by category."""
    days = request.args.get('days', 30, type=int)
    sales = database.get_sales_by_category(days=days)
    return jsonify(sales)


@app.route("/api/analytics/daily-revenue", methods=["GET"])
@require_auth
def api_daily_revenue():
    """Get daily revenue data."""
    days = request.args.get('days', 30, type=int)
    revenue = database.get_daily_revenue(days=days)
    return jsonify([{"day": day, "revenue": rev} for day, rev in revenue])


@app.route("/api/analytics/user-performance/<int:user_id>", methods=["GET"])
@require_manager
def api_user_performance(user_id):
    """Get user performance metrics (manager only)."""
    days = request.args.get('days', 30, type=int)
    performance = database.get_user_performance(user_id, days=days)
    if not performance:
        return jsonify({"error": "User not found or no data"}), 404
    return jsonify(performance)


def _on_cycle(counts):
    evaluate_alerts(counts)


def start_background_worker():
    thread = threading.Thread(target=run_detection_loop, args=(_stop_event, _on_cycle), daemon=True)
    thread.start()
    return thread


def start_low_stock_reminder_worker():
    thread = threading.Thread(target=_low_stock_reminder_loop, daemon=True,
                              name="low-stock-reminder")
    thread.start()
    return thread


if __name__ == "__main__":
    database.init_db()
    start_low_stock_reminder_worker()
    if config.START_CAMERA_WORKER_ON_BOOT:
        start_background_worker()
    else:
        log.info("Camera worker disabled at boot; webcam is available to the browser Camera Monitor.")
    try:
        app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
    finally:
        _stop_event.set()
