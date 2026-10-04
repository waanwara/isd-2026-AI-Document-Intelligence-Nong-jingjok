"""แตกไฟล์ฐานข้อมูล artifacts/katrag.sqlite3.gz -> artifacts/katrag.sqlite3 (ข้ามถ้ามีอยู่แล้ว)."""
import gzip
import shutil
import sys
from pathlib import Path

ART = Path(__file__).resolve().parent / "artifacts"
SRC = ART / "katrag.sqlite3.gz"
DST = ART / "katrag.sqlite3"


def main() -> int:
    if DST.exists() and DST.stat().st_size > 0:
        print(f"[OK] พบฐานข้อมูลแล้ว: {DST}")
        return 0
    if not SRC.exists():
        print(f"[ERROR] ไม่พบ {SRC} — ดึงไฟล์จาก git ให้ครบก่อน (git pull)")
        return 1
    print("[INFO] กำลังแตกไฟล์ฐานข้อมูล (~110 MB) ...")
    tmp = DST.with_suffix(".tmp")
    with gzip.open(SRC, "rb") as f_in, open(tmp, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.replace(DST)
    print(f"[OK] สร้างฐานข้อมูลเรียบร้อย: {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
