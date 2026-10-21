"""Evaluate depletion-sales baseline on held-out historical sales data.

Usage: python evaluate_forecast.py
The reported accuracy is ``100 * (1 - MAPE)`` for the seven-day moving-average
daily-sales forecast. It is a measurement, not a promised outcome: the 85%
target is achieved only when this command reports >=85 on real held-out data.
"""
from datetime import datetime, timedelta

import config
import database


def evaluate(product_id, holdout_days=7):
    daily = database.get_daily_sales(product_id, config.BURN_RATE_WINDOW_DAYS + holdout_days)
    values = [float(quantity) for _, quantity in daily]
    if len(values) < config.BURN_RATE_WINDOW_DAYS + 1:
        return None
    actual = values[-holdout_days:]
    history = values[:-holdout_days]
    errors = []
    for observed in actual:
        prediction = sum(history[-config.BURN_RATE_WINDOW_DAYS:]) / config.BURN_RATE_WINDOW_DAYS
        if observed > 0:
            errors.append(abs(observed - prediction) / observed)
        history.append(observed)
    if not errors:
        return None
    mape = sum(errors) / len(errors)
    return {"product_id": product_id, "holdout_days": len(errors), "mape": round(mape * 100, 2),
            "accuracy": round(max(0, 1 - mape) * 100, 2)}


if __name__ == "__main__":
    database.init_db()
    results = [evaluate(product["product_id"]) for product in database.get_all_products()]
    for result in filter(None, results):
        print(f"{result['product_id']}: {result['accuracy']}% accuracy ({result['mape']}% MAPE, {result['holdout_days']}-day holdout)")
