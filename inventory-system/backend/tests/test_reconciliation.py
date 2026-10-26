import camera_worker
import database


def _stable(reconciler, counts):
    results = []
    for _ in range(3):
        results.append(reconciler.reconcile(counts))
    return results


def test_camera_movements_persist_and_pos_sale_is_not_double_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "inventory.db"))
    database.init_db()
    database.create_product("shelf_item", "Shelf item", price=1.0)
    database.set_stock_count("shelf_item", 10)
    user_id = database.create_user("cashier", "hash", "Cashier", "sales")
    reconciler = camera_worker.ShelfReconciler()

    assert _stable(reconciler, {"shelf_item": 10}) == [{}, {}, {}]

    database.create_pos_transaction(user_id, [{"product_id": "shelf_item", "quantity": 1}], 1.0)
    assert _stable(reconciler, {"shelf_item": 9}) == [{}, {}, {}]
    assert database.get_latest_count("shelf_item") == 9

    assert _stable(reconciler, {"shelf_item": 8}) == [{}, {}, {"shelf_item": 8}]
    assert database.get_latest_count("shelf_item") == 8
    assert database.get_daily_sales("shelf_item", 1)[0][1] == 2

    assert _stable(reconciler, {"shelf_item": 9}) == [{}, {}, {"shelf_item": 9}]
    assert database.get_latest_count("shelf_item") == 9


def test_first_stable_camera_count_receives_opening_stock_from_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "inventory.db"))
    database.init_db()
    database.create_product("shelf_item", "Shelf item", price=1.0)
    database.set_stock_count("shelf_item", 0)
    reconciler = camera_worker.ShelfReconciler()

    assert _stable(reconciler, {"shelf_item": 4}) == [{}, {}, {"shelf_item": 4}]
    assert database.get_latest_count("shelf_item") == 4
    with database.get_conn() as conn:
        movement = conn.execute(
            "SELECT quantity, movement_type FROM stock_movements "
            "WHERE product_id = ? AND movement_type = 'camera_receipt'",
            ("shelf_item",),
        ).fetchone()
    assert movement["quantity"] == 4
    assert movement["movement_type"] == "camera_receipt"
    assert _stable(reconciler, {"shelf_item": 3}) == [{}, {}, {"shelf_item": 3}]
    assert database.get_latest_count("shelf_item") == 3


def test_region_maps_hyphenated_id_to_normalized_product_id(monkeypatch):
    monkeypatch.setattr(database, "get_all_products", lambda: [
        {"product_id": "gloria_biscuits", "name": "Gloria Biscuits", "camera_label": None},
    ])
    monkeypatch.setattr(camera_worker.config, "SHELF_REGIONS", {
        "gloria-biscuits": {"box": (0, 0, 100, 100), "model_labels": ["Gloria_biscuits"]},
    })

    assert camera_worker._registered_shelf_regions() == {
        "gloria_biscuits": {"box": (0, 0, 100, 100), "model_labels": ["Gloria_biscuits"]},
    }