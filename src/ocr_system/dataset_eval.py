import json
import re
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def compute_score(matches: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(matches / total, 4)


def compute_average_score(scores: list[float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())


def tokenize(text: str | None) -> list[str]:
    return re.findall(r"\w+|[\u0E00-\u0E7F]+", normalize_text(text).lower())


def similarity_score(a: str | None, b: str | None) -> float:
    left = tokenize(a)
    right = tokenize(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    overlap = len(set(left) & set(right))
    union = len(set(left) | set(right))
    if union == 0:
        return 1.0
    return round(overlap / union, 4)


def exact_match(a: str | None, b: str | None) -> bool:
    return similarity_score(a, b) >= 1.0


def compare_field_level(prediction: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    results = {}
    total = 0
    scores = []
    for key in sorted(set(prediction) | set(reference)):
        pred_val = prediction.get(key)
        ref_val = reference.get(key)
        score = similarity_score(str(pred_val), str(ref_val))
        is_match = score >= 1.0
        scores.append(score)
        total += 1
        results[key] = {
            "pred": pred_val,
            "ref": ref_val,
            "exact_match": is_match,
            "similarity": score,
        }
    results["__score__"] = compute_average_score(scores)
    return results


def compare_page_level(prediction_pages: list[dict[str, Any]], reference_pages: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    scores = []
    for idx, (pred, ref) in enumerate(zip(prediction_pages, reference_pages), start=1):
        score = similarity_score(pred.get("text", ""), ref.get("text", ""))
        is_match = score >= 1.0
        scores.append(score)
        results.append({
            "page": idx,
            "pred": pred.get("text", ""),
            "ref": ref.get("text", ""),
            "exact_match": is_match,
            "similarity": score,
        })
    matched_pages = sum(1 for item in results if item["exact_match"])
    return {
        "pages": results,
        "matched_pages": matched_pages,
        "score": compute_average_score(scores),
    }


def compare_category_level(prediction: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    categories = sorted(set(prediction) | set(reference))
    results = {}
    scores = []
    for category in categories:
        pred_val = prediction.get(category)
        ref_val = reference.get(category)
        score = similarity_score(str(pred_val), str(ref_val))
        is_match = score >= 1.0
        scores.append(score)
        results[category] = {
            "exact_match": is_match,
            "similarity": score,
            "pred": pred_val,
            "ref": ref_val,
        }
    results["__score__"] = compute_average_score(scores)
    return results


def evaluate_dataset(dataset_dir: str | Path, prediction_dir: str | Path) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    prediction_dir = Path(prediction_dir)

    field_results = []
    page_results = []
    category_results = []

    for gt_file in sorted(dataset_dir.glob("*.json")):
        pred_file = prediction_dir / gt_file.name
        if not pred_file.exists():
            continue

        gt = load_json(gt_file)
        pred = load_json(pred_file)

        if isinstance(gt, dict) and isinstance(pred, dict):
            field_compare = compare_field_level(pred, gt)
            page_compare = compare_page_level(pred.get("pages", []), gt.get("pages", []))
            category_compare = compare_category_level(pred.get("categories", {}), gt.get("categories", {}))

            field_results.append({
                "file": gt_file.name,
                "field_level": field_compare,
                "field_score": field_compare.get("__score__", 0.0),
            })
            page_results.append({
                "file": gt_file.name,
                "page_level": page_compare,
                "page_score": page_compare.get("score", 0.0),
            })
            category_results.append({
                "file": gt_file.name,
                "category_level": category_compare,
                "category_score": category_compare.get("__score__", 0.0),
            })

    field_score = compute_average_score(
        [item.get("field_score", 0.0) for item in field_results]
    )
    page_score = compute_average_score(
        [item.get("page_score", 0.0) for item in page_results]
    )
    category_score = compute_average_score(
        [item.get("category_score", 0.0) for item in category_results]
    )

    return {
        "field_level": field_results,
        "page_level": page_results,
        "category_level": category_results,
        "summary": {
            "field_score": field_score,
            "page_score": page_score,
            "category_score": category_score,
        },
    }
