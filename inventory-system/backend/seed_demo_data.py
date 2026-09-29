"""
seed_demo_data.py — Enhanced version with users, products, and POS data.
Generates a realistic daily sales history so /api/burn-rate and
/api/forecast-comparison have something to show immediately, without
waiting for the (simulated or real) detection loop to accumulate history.
"""
import random
from datetime import datetime, timedelta

import config
import database
import auth


def seed_users():
    """Create demo users."""
    print("Seeding users...")
    
    # Manager
    manager_password = auth.hash_password("manager123")
    database.create_user(
        username="manager",
        password_hash=manager_password,
        full_name="Store Manager",
        role="manager"
    )
    
    # Sales persons
    sales_password = auth.hash_password("sales123")
    database.create_user(
        username="sales1",
        password_hash=sales_password,
        full_name="John Sales",
        role="sales"
    )
    database.create_user(
        username="sales2", 
        password_hash=sales_password,
        full_name="Jane Sales",
        role="sales"
    )
    
    print("✓ Users created: manager (manager123), sales1 (sales123), sales2 (sales123)")


def seed_products():
    """Create demo products matching shelf regions."""
    print("Seeding products...")
    
    products_data = [
        {
            "product_id": "sugar_2kg",
            "name": "Sugar 2kg",
            "description": "Premium white sugar 2kg package",
            "price": 5.99,
            "category": "Pantry",
            "sku": "SUG-002KG",
            "barcode": "1234567890123"
        },
        {
            "product_id": "salt_1kg", 
            "name": "Salt 1kg",
            "description": "Iodized table salt 1kg package",
            "price": 2.49,
            "category": "Pantry",
            "sku": "SAL-001KG",
            "barcode": "1234567890124"
        },
        {
            "product_id": "cooking_oil",
            "name": "Cooking Oil 2L",
            "description": "Vegetable cooking oil 2 liter bottle",
            "price": 8.99,
            "category": "Cooking",
            "sku": "OIL-002L",
            "barcode": "1234567890125"
        }
    ]
    
    for product in products_data:
        database.create_product(**product)
    
    print(f"✓ Products created: {len(products_data)} products")


def seed_sales_history(days: int = 21, mean_units_per_day: int = 3, seed_value: int = 42):
    """Generate historical sales data."""
    random.seed(seed_value)
    
    print(f"Seeding {days} days of sales history...")
    
    # Get users for POS transactions
    users = database.get_all_users()
    sales_users = [u for u in users if u['role'] in ('sales', 'sales_person')]
    
    for pid, region in config.SHELF_REGIONS.items():
        stock = 90
        for day_offset in range(days, 0, -1):
            day = datetime.utcnow() - timedelta(days=day_offset)
            qty_sold = max(0, round(random.gauss(mean_units_per_day, 1.2)))
            qty_sold = min(qty_sold, stock)
            stock -= qty_sold

            ts = day.replace(hour=18, minute=0, second=0).isoformat()
            
            # Mix of auto-detection and POS sales
            if qty_sold > 0:
                if random.random() < 0.3:  # 30% chance of POS sale
                    user = random.choice(sales_users) if sales_users else None
                    database.log_sales_event(pid, qty_sold, ts, sale_type='pos', user_id=user['id'] if user else None)
                else:
                    database.log_sales_event(pid, qty_sold, ts, sale_type='auto')
            
            database.write_stock_log(pid, stock, ts)

        print(f"✓ Seeded {pid}: {days} days, ending stock={stock}")


def seed_pos_transactions():
    """Create some sample POS transactions."""
    print("Seeding POS transactions...")
    
    users = database.get_all_users()
    sales_users = [u for u in users if u['role'] in ('sales', 'sales_person')]
    
    if not sales_users:
        print("⚠ No sales users found, skipping POS transactions")
        return
    
    products = database.get_all_products()
    
    # Create 5 sample transactions
    for i in range(5):
        user = random.choice(sales_users)
        num_items = random.randint(1, 3)
        items = []
        total = 0.0
        
        for _ in range(num_items):
            product = random.choice(products)
            qty = random.randint(1, 2)
            price = product['price']
            item_total = qty * price
            total += item_total
            
            items.append({
                'product_id': product['product_id'],
                'quantity': qty,
                'unit_price': price
            })
        
        database.create_pos_transaction(
            user_id=user['id'],
            items=items,
            total_amount=total,
            payment_method=random.choice(['cash', 'card'])
        )
    
    print(f"✓ Created 5 sample POS transactions")


def seed(days: int = 21, mean_units_per_day: int = 3, seed_value: int = 42):
    """Main seed function."""
    random.seed(seed_value)
    database.init_db()
    
    print("=== Starting database seeding ===\n")
    
    seed_users()
    seed_products()
    seed_sales_history(days, mean_units_per_day, seed_value)
    seed_pos_transactions()
    
    print("\n=== Database seeding complete ===")
    print("\nDemo credentials:")
    print("  Manager: username='manager', password='manager123'")
    print("  Sales:   username='sales1', password='sales123'")
    print("  Sales:   username='sales2', password='sales123'")


if __name__ == "__main__":
    seed()
