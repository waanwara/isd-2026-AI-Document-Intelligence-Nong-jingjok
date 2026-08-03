from pathlib import Path
from pdf2image import convert_from_path
import cv2
from PIL import Image
import fitz
from .utils.io import ensure_dir

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_pdf(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def pdf_to_images(pdf_path: str | Path, output_dir: str | Path, dpi: int = 300) -> list[Path]:
    output_dir = ensure_dir(output_dir)
    image_paths: list[Path] = []
    try:
        pages = convert_from_path(str(pdf_path), dpi=dpi)
    except Exception:
        pages = []

    if not pages:
        doc = fitz.open(str(pdf_path))
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
            out = output_dir / f"{Path(pdf_path).stem}_page_{idx:03d}.jpg"
            pix.save(out)
            image_paths.append(out)
        doc.close()
        return image_paths

    for idx, page in enumerate(pages, start=1):
        out = output_dir / f"{Path(pdf_path).stem}_page_{idx:03d}.jpg"
        page.save(out, "JPEG")
        image_paths.append(out)
    return image_paths


def load_document_pages(input_path: str | Path, output_dir: str | Path, dpi: int = 300) -> list[Path]:
    input_path = Path(input_path)
    if is_pdf(input_path):
        return pdf_to_images(input_path, output_dir, dpi=dpi)
    if is_image(input_path):
        return [input_path]
    raise ValueError(f"Unsupported file type: {input_path.suffix}")
