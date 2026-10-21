"""
Burn Rate and Depletion Forecasting (Ch3 §3.5.2 / §3.6.2).

Primary model: trailing moving average (no training phase, always available).
Secondary model: single-feature LSTM, retrained fresh per request, comparison only.
"""
from datetime import date, timedelta
import math

import config
import database


def compute_burn_rate(product_id: str) -> float:
    daily = database.get_daily_sales(product_id, config.BURN_RATE_WINDOW_DAYS)
    if not daily:
        return 0.0
    total = sum(qty for _, qty in daily)
    return round(total / config.BURN_RATE_WINDOW_DAYS, 2)


def predict_depletion(product_id: str) -> dict:
    """Direct implementation of Ch3 §3.6.2 predict_depletion()."""
    current_stock = database.get_latest_count(product_id) or 0
    burn_rate = compute_burn_rate(product_id)
    if burn_rate <= 0:
        return {
            "current_stock": current_stock,
            "burn_rate": 0,
            "days_remaining": None,
            "depletion_date": None,
        }
    days_remaining = round(current_stock / burn_rate, 1)
    depletion_date = (date.today() + timedelta(days=days_remaining)).isoformat()
    return {
        "current_stock": current_stock,
        "burn_rate": burn_rate,
        "days_remaining": days_remaining,
        "depletion_date": depletion_date,
    }


def _season_for(month: int) -> tuple[str | None, tuple[int, ...]]:
    if month in (9, 10, 11):
        return "hot", (9, 10, 11)
    if month in (12, 1, 2):
        return "warm/rainy", (12, 1, 2)
    if month in (5, 6, 7):
        return "cold", (5, 6, 7)
    return None, ()


def beverage_seasonal_multiplier(category: str, month: int | None = None) -> dict:
    """Use actual beverage sales to validate any seasonal demand adjustment.

    A neutral factor is returned until both the current seasonal period and
    neutral months have enough observed sales days. This deliberately avoids
    applying a guessed Zimbabwe weather uplift to purchase quantities.
    """
    if category != "Beverages":
        return {"multiplier": 1.0, "validated": False, "reason": None}
    season, target_months = _season_for(month or date.today().month)
    if not season:
        return {"multiplier": 1.0, "validated": False, "reason": "Neutral season"}
    observations = database.get_beverage_seasonal_observations(target_months, (3, 4, 8))
    minimum = config.SEASONAL_VALIDATION_MIN_ACTIVE_DAYS
    if observations["target_days"] < minimum or observations["baseline_days"] < minimum:
        return {
            "multiplier": 1.0, "validated": False,
            "reason": f"Needs {minimum} observed beverage-sales days in both {season} and neutral periods",
            **observations,
        }
    target_daily = observations["target_units"] / observations["target_days"]
    baseline_daily = observations["baseline_units"] / observations["baseline_days"]
    if baseline_daily <= 0:
        return {"multiplier": 1.0, "validated": False, "reason": "Neutral-period beverage demand is zero", **observations}
    # Bound a data anomaly without turning the factor into a hard-coded uplift.
    multiplier = round(max(0.70, min(1.75, target_daily / baseline_daily)), 2)
    return {"multiplier": multiplier, "validated": True, "season": season,
            "target_daily_sales": round(target_daily, 2), "baseline_daily_sales": round(baseline_daily, 2),
            **observations}


def restock_recommendation(product: dict) -> dict:
    """Calculate a reviewable reorder target from live stock and real sales."""
    product_id = product["product_id"]
    prediction = predict_depletion(product_id)
    trend = database.get_sales_trend(product_id)
    quality = database.get_restock_data_quality(product_id, config.RESTOCK_LOOKBACK_DAYS)
    base_daily_demand = max(
        quality["sales_units"] / config.RESTOCK_LOOKBACK_DAYS,
        trend["recent"] / 7,
    )
    seasonal = beverage_seasonal_multiplier(product.get("category", ""))
    adjusted_daily_demand = base_daily_demand * seasonal["multiplier"]
    target_stock = adjusted_daily_demand * (config.RESTOCK_LEAD_TIME_DAYS + config.RESTOCK_SAFETY_DAYS)
    suggested_quantity = max(0, math.ceil(target_stock - prediction["current_stock"]))
    trend_up = trend["recent"] > trend["previous"] and trend["recent"] > 0
    if prediction["current_stock"] == 0:
        action = "Restock immediately — out of stock"
    elif suggested_quantity:
        action = "Reorder now" if trend_up or (prediction["days_remaining"] is not None and prediction["days_remaining"] <= config.RESTOCK_LEAD_TIME_DAYS) else "Plan a reorder"
    else:
        action = "Monitor"
    data_quality = (
        f"{quality['sales_active_days']}/{quality['lookback_days']} sales days; "
        + ("stock count current" if quality["stock_current"] else "stock count needs confirmation")
    )
    return {
        "product_id": product_id, "label": product["name"], "category": product.get("category"),
        "current_stock": prediction["current_stock"], "days_remaining": prediction["days_remaining"],
        "depletion_date": prediction["depletion_date"], "recent_sales": trend["recent"],
        "previous_sales": trend["previous"], "daily_burn_rate": round(base_daily_demand, 2),
        "seasonal_multiplier": seasonal["multiplier"], "seasonal_validation": seasonal,
        "adjusted_daily_demand": round(adjusted_daily_demand, 2), "target_stock": math.ceil(target_stock),
        "suggested_quantity": suggested_quantity, "suggested_action": action,
        "data_quality": data_quality, "stock_current": quality["stock_current"],
    }


def _lstm_predict(series: list) -> float | None:
    """
    Trains a tiny LSTM (8 hidden units) on sliding windows of `series` and predicts
    the next value. Returns None if TensorFlow isn't installed — the API layer
    handles that gracefully (moving average still works with zero dependencies).
    """
    try:
        import numpy as np
        from tensorflow import keras
    except ImportError:
        return None

    window = config.LSTM_WINDOW_SIZE
    if len(series) < window + 1:
        return None

    X, y = [], []
    for i in range(len(series) - window):
        X.append(series[i : i + window])
        y.append(series[i + window])
    X = np.array(X).reshape((-1, window, 1))
    y = np.array(y)

    model = keras.Sequential(
        [
            keras.layers.Input(shape=(window, 1)),
            keras.layers.LSTM(8),
            keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse")
    model.fit(X, y, epochs=50, verbose=0)

    last_window = np.array(series[-window:]).reshape((1, window, 1))
    prediction = float(model.predict(last_window, verbose=0)[0][0])
    return round(max(prediction, 0.0), 2)


def forecast_comparison(product_id: str) -> dict:
    """Powers GET /api/forecast-comparison/<id> (Ch3 Table 3.3)."""
    daily = database.get_daily_sales(product_id, days=60)
    series = [qty for _, qty in daily]
    non_zero_days = len(series)

    moving_average = compute_burn_rate(product_id)

    if non_zero_days < config.LSTM_MIN_DAYS_REQUIRED:
        lstm_result = {
            "predicted_units_sold": None,
            "note": f"needs {config.LSTM_MIN_DAYS_REQUIRED}+ days of sales history ({non_zero_days} available)",
        }
    else:
        prediction = _lstm_predict(series)
        lstm_result = (
            {"predicted_units_sold": prediction, "note": None}
            if prediction is not None
            else {"predicted_units_sold": None, "note": "TensorFlow not installed in this environment"}
        )

    return {
        "product_id": product_id,
        "days_of_history": non_zero_days,
        "moving_average": {"burn_rate_per_day": moving_average},
        "lstm": lstm_result,
    }
