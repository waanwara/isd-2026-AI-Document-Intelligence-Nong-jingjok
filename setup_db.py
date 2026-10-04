"""Extract artifacts/katrag.sqlite3.gz -> artifacts/katrag.sqlite3 (skipped if it already exists)."""
import gzip
import shutil
import sys
from pathlib import Path

ART = Path(__file__).resolve().parent / "artifacts"
SRC = ART / "katrag.sqlite3.gz"
DST = ART / "katrag.sqlite3"


def main() -> int:
    if DST.exists() and DST.stat().st_size > 0:
        print(f"[OK] database already present: {DST}")
        return 0
    if not SRC.exists():
        print(f"[ERROR] {SRC} not found - make sure the repo was cloned completely (git pull)")
        return 1
    print("[INFO] extracting database (~110 MB) ...")
    tmp = DST.with_suffix(".tmp")
    with gzip.open(SRC, "rb") as f_in, open(tmp, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.replace(DST)
    print(f"[OK] database ready: {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
