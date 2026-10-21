"""Create the apple, banana, and orange SKUs supported by the COCO model.

Run once before calibrating the fruit shelf regions. Existing products and
stock counts are left untouched.
"""
import database


FRUIT_PRODUCTS = (
    ("apple", "Apples", "Fresh apples — camera-counted in the Apple bin", 0.50, "Fruit"),
    ("banana", "Bananas", "Fresh bananas — camera-counted in the Banana bin", 0.30, "Fruit"),
    ("orange", "Oranges", "Fresh oranges — camera-counted in the Orange bin", 0.45, "Fruit"),
)


def main():
    database.init_db()
    for product_id, name, description, price, category in FRUIT_PRODUCTS:
        if database.get_product(product_id):
            print(f"Keeping existing {product_id} product and stock.")
            continue
        database.create_product(product_id, name, description, price, category)
        database.set_stock_count(product_id, 0, note="Fruit demo product created")
        print(f"Created {product_id}.")
    print("Fruit setup complete. Calibrate apple, banana, and orange regions in config.py before camera counting.")


if __name__ == "__main__":
    main()
