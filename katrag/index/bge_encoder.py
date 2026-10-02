"""bge-m3 local encoder (transformers + torch) — ใช้ร่วมกัน build + query.

โหลดโมเดลครั้งเดียว (singleton) encode ข้อความไทย/อังกฤษเป็น vector dim 1024
"""

from __future__ import annotations

import os
import numpy as np

os.environ.setdefault("HF_HOME", "D:\\hf_cache")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_MODEL = None
_TOKENIZER = None
_DEVICE = None


def _load():
    global _MODEL, _TOKENIZER, _DEVICE
    if _MODEL is not None:
        return
    import torch
    from transformers import AutoTokenizer, AutoModel

    _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    _TOKENIZER = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    model = AutoModel.from_pretrained("BAAI/bge-m3")
    if _DEVICE == "cuda":
        model = model.half().cuda()
    _MODEL = model.eval()


def encode(texts: list[str], batch_size: int = 32, max_length: int = 256) -> np.ndarray:
    """Encode texts → np.ndarray (n, 1024) L2-normalized."""
    import torch

    _load()
    out: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inputs = _TOKENIZER(
            batch, padding=True, truncation=True, max_length=max_length, return_tensors="pt"
        ).to(_DEVICE)
        with torch.no_grad():
            outputs = _MODEL(**inputs)
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        emb = (outputs.last_hidden_state * mask).sum(1) / mask.sum(1)
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        try:
            arr = emb.cpu().float().numpy().astype(np.float32)
        except Exception:
            arr = np.array(emb.cpu().float().tolist(), dtype=np.float32)
        out.append(arr)
    return np.vstack(out) if out else np.empty((0, 1024), dtype=np.float32)




def encode_one(text: str) -> np.ndarray:
    return encode([text])[0]
