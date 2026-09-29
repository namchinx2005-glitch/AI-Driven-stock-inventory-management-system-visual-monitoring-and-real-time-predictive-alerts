"""
Burn Rate and Depletion Forecasting (Ch3 §3.5.2 / §3.6.2).

Primary model: trailing moving average (no training phase, always available).
Secondary model: single-feature LSTM, retrained fresh per request, comparison only.
"""
from datetime import date, timedelta

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
