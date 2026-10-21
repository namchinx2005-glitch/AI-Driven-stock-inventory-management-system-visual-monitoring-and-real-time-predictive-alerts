import config
from detector import DualModelDetector


class FakeBox:
    def __init__(self, class_id, confidence, coordinates):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [coordinates]


class FakeResult:
    def __init__(self, names, boxes):
        self.names = names
        self.boxes = boxes


class FakeModel:
    def __init__(self, names, boxes):
        self.names = names
        self.result = FakeResult(names, boxes)

    def __call__(self, frame, conf, verbose):
        return [self.result]


def test_coco_filters_everything_except_allowed_fruit():
    names = {0: "person", 1: "bottle", 2: "cell phone", 3: "donut",
             4: "apple", 5: "banana", 6: "orange"}
    boxes = [FakeBox(class_id, 0.9, [class_id * 10, 10, class_id * 10 + 8, 20])
             for class_id in names]
    coco = FakeModel(names, boxes)
    custom = FakeModel({0: "Gloria_biscuits", 1: "Gunanzi_snack", 2: "Mirinda_apple"}, [])

    found = DualModelDetector(custom_model=custom, coco_model=coco).detect(object())

    assert [item["label"] for item in found] == ["apple", "banana", "orange"]
    assert all(item["source"] == "coco" for item in found)


def test_custom_classes_are_not_filtered_by_coco_allowlist():
    names = {0: "Gloria_biscuits", 1: "Gunanzi_snack", 2: "Mirinda_apple"}
    custom = FakeModel(names, [FakeBox(class_id, 0.8, [0, 0, 20, 20])
                               for class_id in names])

    found = DualModelDetector(custom_model=custom, coco_model=None).detect(object())

    assert [item["label"] for item in found] == list(names.values())
    assert all(item["source"] == "custom" for item in found)


def test_overlapping_coco_fruit_is_deduplicated_in_favor_of_custom():
    custom = FakeModel({0: "Mirinda_apple"}, [FakeBox(0, 0.9, [100, 100, 200, 200])])
    coco = FakeModel({0: "apple"}, [FakeBox(0, 0.95, [105, 105, 195, 195])])

    found = DualModelDetector(custom_model=custom, coco_model=coco).detect(object())

    assert len(found) == 1
    assert found[0]["label"] == "Mirinda_apple"
    assert found[0]["source"] == "custom"


def test_missing_coco_model_does_not_block_custom_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKEND_DIR", str(tmp_path))
    custom = FakeModel({0: "Gunanzi_snack"}, [FakeBox(0, 0.8, [0, 0, 20, 20])])

    detector = DualModelDetector(custom_model=custom,
                                 custom_path=str(tmp_path / "best.pt"),
                                 coco_path=str(tmp_path / "missing-coco.pt"))
    found = detector.detect(object())

    assert len(found) == 1
    assert found[0]["label"] == "Gunanzi_snack"
    assert found[0]["source"] == "custom"
    assert detector.coco_model is None


def test_each_model_uses_its_own_confidence_threshold():
    custom = FakeModel({0: "Gloria_biscuits"}, [FakeBox(0, 0.36, [0, 0, 20, 20])])
    coco = FakeModel({0: "apple"}, [FakeBox(0, 0.39, [30, 0, 50, 20])])

    found = DualModelDetector(custom_model=custom, coco_model=coco).detect(object())

    assert [(item["label"], item["source"]) for item in found] == [("Gloria_biscuits", "custom")]
