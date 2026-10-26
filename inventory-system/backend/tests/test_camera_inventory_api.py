import auth
import database
import app as app_module


def _manager_token():
    user_id = database.create_user("manager", "unused-hash", "Store Manager", "manager")
    return auth.generate_jwt_token({
        "id": user_id,
        "username": "manager",
        "role": "manager",
    })


def test_new_camera_product_starts_at_zero_even_if_quantity_is_submitted(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "inventory.db"))
    database.init_db()
    token = _manager_token()
    client = app_module.app.test_client()

    response = client.post(
        "/api/products",
        json={
            "name": "Apples",
            "price": 0.5,
            "camera_label": "apple",
            "initial_stock": 25,
            "quantity": 25,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.get_json()["product_id"] == "apple"
    assert database.get_latest_count("apple") == 0


def test_product_creation_requires_camera_class(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "inventory.db"))
    database.init_db()
    token = _manager_token()
    client = app_module.app.test_client()

    response = client.post(
        "/api/products",
        json={"name": "Untracked item", "price": 2.0},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "camera class" in response.get_json()["error"]


def test_manual_stock_receipts_and_counts_are_disabled():
    client = app_module.app.test_client()
    token = auth.generate_jwt_token({"id": 1, "username": "manager", "role": "manager"})
    headers = {"Authorization": f"Bearer {token}"}

    receipt = client.post(
        "/api/inventory/receive",
        json={"product_id": "apple", "quantity": 8, "source": "manual"},
        headers=headers,
    )
    count = client.put(
        "/api/inventory/apple/count",
        json={"count": 8},
        headers=headers,
    )

    assert receipt.status_code == 403
    assert count.status_code == 403
