import json
import tempfile
import unittest
from pathlib import Path

from src.ocr_system.dataset_eval import evaluate_dataset


class DatasetEvalScoreTests(unittest.TestCase):
    def test_evaluate_dataset_adds_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            gt_dir = tmp / "gt"
            pred_dir = tmp / "pred"
            gt_dir.mkdir()
            pred_dir.mkdir()

            gt_path = gt_dir / "sample.json"
            pred_path = pred_dir / "sample.json"
            gt_path.write_text(json.dumps({"categories": {"a": "x"}, "pages": [{"text": "hello"}]}), encoding="utf-8")
            pred_path.write_text(json.dumps({"categories": {"a": "x"}, "pages": [{"text": "hello"}]}), encoding="utf-8")

            result = evaluate_dataset(gt_dir, pred_dir)

            self.assertEqual(result["summary"]["field_score"], 1.0)
            self.assertEqual(result["summary"]["page_score"], 1.0)
            self.assertEqual(result["summary"]["category_score"], 1.0)
            self.assertEqual(result["field_level"][0]["field_score"], 1.0)
            self.assertEqual(result["page_level"][0]["page_score"], 1.0)
            self.assertEqual(result["category_level"][0]["category_score"], 1.0)

    def test_evaluate_dataset_uses_similarity_for_near_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            gt_dir = tmp / "gt"
            pred_dir = tmp / "pred"
            gt_dir.mkdir()
            pred_dir.mkdir()

            gt_path = gt_dir / "sample.json"
            pred_path = pred_dir / "sample.json"
            gt_path.write_text(json.dumps({"categories": {"a": "The quick brown fox"}, "pages": [{"text": "The quick brown fox"}]}), encoding="utf-8")
            pred_path.write_text(json.dumps({"categories": {"a": "The quick brown fox jumps"}, "pages": [{"text": "The quick brown fox jumps"}]}), encoding="utf-8")

            result = evaluate_dataset(gt_dir, pred_dir)

            self.assertGreater(result["summary"]["field_score"], 0.0)
            self.assertLess(result["summary"]["field_score"], 1.0)
            self.assertGreater(result["field_level"][0]["field_score"], 0.0)
            self.assertLess(result["field_level"][0]["field_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
