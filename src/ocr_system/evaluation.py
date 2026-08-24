import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from jiwer import wer
import Levenshtein


@dataclass
class EvaluationResult:
    file: str
    cer: float
    wer: float
    exact_match: bool
    reference_chars: int
    prediction_chars: int


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def char_error_rate(reference: str, prediction: str) -> float:
    ref = normalize_text(reference).replace(" ", "")
    hyp = normalize_text(prediction).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def evaluate_text(reference: str, prediction: str, file_name: str = "") -> EvaluationResult:
    ref = normalize_text(reference)
    hyp = normalize_text(prediction)
    return EvaluationResult(
        file=file_name,
        cer=char_error_rate(ref, hyp),
        wer=wer(ref, hyp) if ref else (0.0 if not hyp else 1.0),
        exact_match=ref == hyp,
        reference_chars=len(ref),
        prediction_chars=len(hyp),
    )


def extract_all_text(obj):
    if isinstance(obj, str):
        return obj + "\n"
    elif isinstance(obj, dict):
        return "".join(extract_all_text(v) for v in obj.values())
    elif isinstance(obj, list):
        return "".join(extract_all_text(v) for v in obj)
    elif obj is None:
        return ""
    else:
        return str(obj) + "\n"

def evaluate_from_files(ground_truth_json: str | Path, prediction_json: str | Path) -> dict:
    with Path(ground_truth_json).open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)
    with Path(prediction_json).open("r", encoding="utf-8") as f:
        prediction = json.load(f)

    # Handle missing source_path in prediction
    source_path = prediction.get("source_path", str(prediction_json))
    source_name = Path(source_path).name

    reference = ground_truth.get(source_name) or ground_truth.get(Path(source_name).stem)
    if reference is None:
        reference = extract_all_text(ground_truth)
    elif not isinstance(reference, str):
        reference = extract_all_text(reference)

    # Handle missing text in prediction (e.g. structured output)
    pred_text = prediction.get("text")
    if pred_text is None:
        pred_text = extract_all_text(prediction)

    result = evaluate_text(reference, pred_text, file_name=source_name)
    return asdict(result)
