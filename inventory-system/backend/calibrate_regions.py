"""Interactive, privacy-safe shelf-region calibration.

Run locally once for each shelf product, draw one rectangle, then copy the
printed product-ID/model-label region into config.SHELF_REGIONS.
No screenshot or video is saved.
"""
from camera_worker import calibrate_region


if __name__ == "__main__":
    product_id = input("Product ID (one of gloria_biscuits, gunanzi_snack, mirinda_apple, apple, banana, orange): ").strip()
    if not product_id:
        raise SystemExit("A product ID is required.")
    model_labels = input("Exact model class name(s), comma-separated: ").strip()
    labels = [label.strip() for label in model_labels.split(",") if label.strip()]
    if not labels:
        labels = [product_id]
    box = calibrate_region(product_id, model_labels=labels)
    if box:
        print(f"Add this to config.SHELF_REGIONS:\n    {product_id!r}: {{'box': {box!r}, 'model_labels': {labels!r}}},")
    else:
        print("Calibration cancelled; no region was changed.")
