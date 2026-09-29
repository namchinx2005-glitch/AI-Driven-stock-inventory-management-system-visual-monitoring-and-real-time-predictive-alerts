"""Interactive, privacy-safe shelf-region calibration.

Run locally, draw one rectangle, then copy the printed box into SHELF_REGIONS.
No screenshot or video is saved.
"""
from camera_worker import calibrate_region


if __name__ == "__main__":
    product_id = input("Product ID (for example salt_1kg): ").strip()
    label = input("Display label: ").strip() or product_id
    if not product_id:
        raise SystemExit("A product ID is required.")
    box = calibrate_region(product_id, label)
    if box:
        print(f"Add this to config.SHELF_REGIONS:\n    {product_id!r}: {{'box': {box!r}, 'label': {label!r}}},")
    else:
        print("Calibration cancelled; no region was changed.")
