"""Run the Lab 7B -> Lab 8B workflow on Windows, macOS, or Linux."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LAB7 = ROOT / "src" / "ocr_system" / "lab7b_curriculum.py"
LAB8 = ROOT / "src" / "ocr_system" / "lab8b_curriculum_db.py"
LAB7_OUT = ROOT / "work" / "lab7b_run"
LAB8_OUT = ROOT / "work" / "lab8b_run"


def run(*args: object) -> None:
    subprocess.run([sys.executable, *(str(x) for x in args)], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-lab7", action="store_true")
    args = parser.parse_args()

    os.environ.update({
        "PYTHONUTF8": "1",
        "LAB7_CHUNK": "1",
        "LAB7B_NUM_CTX": "4096",
        "LAB7B_NUM_PREDICT": "2000",
        "LAB7B_OCR_NUM_CTX": "4096",
        "LAB7B_OCR_NUM_PREDICT": "1200",
    })
    LAB7_OUT.mkdir(parents=True, exist_ok=True)
    LAB8_OUT.mkdir(parents=True, exist_ok=True)

    if not args.skip_lab7:
        run(LAB7, "-i", "data/input_C",
            "-g", "data/ground_truth_C/DSBA_academic_plan_coop.json",
            "-p", "vlm", "-o", LAB7_OUT)

    predictions = [LAB7_OUT / "pred_vlm.json", LAB7_OUT / "pred_markdown.json"]
    prediction = next((p for p in predictions if p.exists()), None)
    if prediction is None:
        raise SystemExit("ไม่พบ pred_vlm.json หรือ pred_markdown.json ใน work/lab7b_run")

    run(LAB8, "schema", "-o", LAB8_OUT / "schema")
    run(LAB8, "import-lab7b", "-i", prediction,
        "-o", LAB8_OUT / "curriculum.json",
        "--program-id", "DSBA-coop",
        "--program-name", "วิทยาการข้อมูลและการวิเคราะห์เชิงธุรกิจ (สหกิจศึกษา)",
        "--total-credits", 135, "--years", 4)
    run(LAB8, "load", "-i", LAB8_OUT / "curriculum.json",
        "-d", LAB8_OUT / "curriculum.db", "--replace")
    run(LAB8, "verify", "-d", LAB8_OUT / "curriculum.db",
        "-o", LAB8_OUT / "verify.json")

    gold = LAB8_OUT / "gold_questions.json"
    sample = LAB7_OUT / "gold_questions_gt.json"
    if not gold.exists() and sample.exists():
        shutil.copyfile(sample, gold)
    if not gold.exists() or len(json.loads(gold.read_text(encoding="utf-8"))) < 30:
        print(f"\nเพิ่มคำถามใน {gold} ให้ครบ 30 ข้อ แล้วรัน:")
        print("python run_lab8b.py --skip-lab7")
        return

    run(LAB8, "eval", "-d", LAB8_OUT / "curriculum.db",
        "-q", gold, "-o", LAB8_OUT / "eval_result.json")
    print(f"\nเสร็จแล้ว: {LAB8_OUT}")


if __name__ == "__main__":
    main()
