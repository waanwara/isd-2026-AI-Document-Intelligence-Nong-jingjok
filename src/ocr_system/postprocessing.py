import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


@dataclass
class PostProcessConfig:
    enable_normalization: bool = True
    enable_common_ocr_fix: bool = True
    enable_llm: bool = False
    llm_caller: Callable[[str], str] | None = None


class OCRTextPostProcessor:
    """Apply a small OCR cleanup pipeline for Thai-English text."""

    def __init__(self, config: PostProcessConfig | None = None) -> None:
        self.config = config or PostProcessConfig()

    def process(self, text: str) -> str:
        if not text:
            return ""

        cleaned = text
        if self.config.enable_normalization:
            cleaned = self.normalize_text(cleaned)
        if self.config.enable_common_ocr_fix:
            cleaned = self.fix_common_ocr_artifacts(cleaned)
        if self.config.enable_llm and self.config.llm_caller is not None:
            cleaned = self.config.llm_caller(cleaned)
        return cleaned.strip()

    def normalize_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def fix_common_ocr_artifacts(self, text: str) -> str:
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                lines.append("")
                continue

            line = line.replace("“", '"').replace("”", '"').replace("’", "'")
            line = re.sub(r"([ก-๙])\s+([ก-๙])", r"\1\2", line)
            line = re.sub(r"([A-Za-z])\s+([A-Za-z])", r"\1\2", line)
            line = re.sub(r"([0-9])\s+([0-9])", r"\1\2", line)
            line = re.sub(r"\s+([,.;:!?%])", r"\1", line)
            line = re.sub(r"([,.;:!?])(?=[^\s])", r"\1 ", line)
            line = re.sub(r"\s{2,}", " ", line)
            lines.append(line)

        return "\n".join(lines).strip()


def llm_correction(text: str, model: str | None = None) -> str:
    """Optional LLM-based post-processing using OpenAI-compatible APIs."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return text
    if OpenAI is None:
        return text

    try:
        client = OpenAI(api_key=api_key)
        prompt = (
            "Correct OCR artifacts in the following text without changing the meaning. "
            "Preserve Thai and English terms, codes, and numbers. Return only the corrected text.\n\n"
            f"{text}"
        )
        response = client.responses.create(
            model=model or os.getenv("LLM_MODEL", "gpt-4o-mini"),
            input=[{"role": "user", "content": prompt}],
        )
        corrected = getattr(response, "output_text", None)
        if corrected:
            return corrected.strip()
    except Exception:
        pass
    return text
