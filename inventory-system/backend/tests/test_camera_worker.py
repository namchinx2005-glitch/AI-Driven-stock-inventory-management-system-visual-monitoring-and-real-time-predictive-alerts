import camera_worker
import config


def test_custom_model_classes_count_in_matching_regions(monkeypatch):
    products = [
        {"product_id": "gloria_biscuits", "camera_label": None},
        {"product_id": "gunanzi_snack", "camera_label": None},
        {"product_id": "mirinda_apple", "camera_label": None},
    ]
    monkeypatch.setattr(camera_worker.database, "get_all_products", lambda: products)
    monkeypatch.setattr(config, "SHELF_REGIONS", {
        "gloria_biscuits": {"box": (0, 0, 400, 720), "model_labels": ["GLORIA BISCUITS"]},
        "gunanzi_snack": {"box": (400, 0, 800, 720), "model_labels": ["Gunanzi-snack"]},
        "mirinda_apple": {"box": (800, 0, 1280, 720), "model_labels": ["mirinda apple"]},
    })
    detections = [
        {"label": "Gloria_biscuits", "conf": 0.9, "box": [50, 50, 150, 150], "source": "custom"},
        {"label": "Gunanzi_snack", "conf": 0.9, "box": [500, 50, 600, 150], "source": "custom"},
        {"label": "Mirinda_apple", "conf": 0.9, "box": [900, 50, 1000, 150], "source": "custom"},
    ]

    assert camera_worker.count_detections_per_region(detections, (720, 1280, 3)) == {
        "gloria_biscuits": 1, "gunanzi_snack": 1, "mirinda_apple": 1,
    }


def test_fruit_detections_count_and_unknown_alerts_are_custom_only(monkeypatch):
    monkeypatch.setattr(camera_worker.database, "get_all_products", lambda: [
        {"product_id": "apple", "camera_label": "apple"},
    ])
    monkeypatch.setattr(config, "SHELF_REGIONS", {
        "apple": {"box": (0, 0, 500, 500), "model_labels": ["apple"]},
    })
    detections = [
        {"label": "apple", "conf": 0.9, "box": [20, 20, 100, 100], "source": "coco"},
        {"label": "mystery snack", "conf": 0.9, "box": [120, 20, 200, 100], "source": "custom"},
        {"label": "banana", "conf": 0.9, "box": [220, 20, 300, 100], "source": "coco"},
    ]

    assert camera_worker.count_detections_per_region(detections) == {"apple": 1}
    unknown = camera_worker.unknown_detections_per_region(detections)
    assert [(item["label"], item["source"]) for item in unknown] == [("mystery snack", "custom")]


def test_no_regions_is_safe(monkeypatch):
    monkeypatch.setattr(config, "SHELF_REGIONS", {})
    monkeypatch.setattr(camera_worker.database, "get_all_products", lambda: [])

    assert camera_worker.count_detections_per_region([]) == {}
    assert camera_worker.unknown_detections_per_region([]) == []


def test_region_crop_detection_counts_in_assigned_zone_even_if_box_crosses_edge(monkeypatch):
    monkeypatch.setattr(camera_worker.database, "get_all_products", lambda: [
        {"product_id": "mirinda_apple", "camera_label": "Mirinda_apple"},
    ])
    monkeypatch.setattr(config, "SHELF_REGIONS", {
        "mirinda-apple": {"box": (400, 300, 800, 600), "model_labels": ["Mirinda_apple"]},
    })
    detection = {
        "label": "Mirinda_apple", "conf": 0.28, "source": "custom",
        "box": [370, 350, 410, 390], "region_id": "mirinda-apple",
    }

    assert camera_worker.count_detections_per_region([detection]) == {"mirinda_apple": 1}


def test_explain_detection_reports_discarded_coco_and_label_mismatch(monkeypatch):
    monkeypatch.setattr(camera_worker.database, "get_all_products", lambda: [
        {"product_id": "apple", "camera_label": "apple"},
    ])
    monkeypatch.setattr(config, "SHELF_REGIONS", {
        "apple": {"box": (0, 0, 500, 500), "model_labels": ["apple"]},
    })

    discarded = {"label": "person", "conf": 0.9, "box": [20, 20, 100, 100], "source": "coco"}
    mismatch = {"label": "Gloria_biscuits", "conf": 0.9, "box": [20, 20, 100, 100], "source": "custom"}
    counted, why = camera_worker.explain_detection(discarded)
    assert not counted and "discarded COCO class" in why
    counted, why = camera_worker.explain_detection(mismatch)
    assert not counted and "label mismatch" in why
