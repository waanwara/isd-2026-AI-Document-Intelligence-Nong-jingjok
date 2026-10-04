"""Pre-download the BAAI/bge-m3 embedding model (~2.3 GB) so the first question is not slow.

Safe to run repeatedly: files already in the Hugging Face cache are not downloaded again.
"""
import sys


def main() -> int:
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError:
        print("[ERROR] torch/transformers not installed - run: pip install -r requirements.txt")
        return 1
    print("[INFO] checking/downloading BAAI/bge-m3 (first run ~2.3 GB, needs internet) ...")
    try:
        AutoTokenizer.from_pretrained("BAAI/bge-m3")
        AutoModel.from_pretrained("BAAI/bge-m3")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] could not load bge-m3: {type(exc).__name__}: {exc}")
        print("[WARN] the server will still start but fall back to lexical search (lower accuracy)")
        return 1
    print("[OK] bge-m3 ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
