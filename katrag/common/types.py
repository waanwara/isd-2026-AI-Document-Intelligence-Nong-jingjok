"""ชนิดข้อมูลร่วมของ Jingjok-Thorius (design §4.1).

ทุกชนิดเป็น frozen + slots เพื่อให้การเปรียบเทียบและการ hash เป็น deterministic
ซึ่งจำเป็นต่อ property ด้าน determinism และ cache key ที่ต้องตรงทุกค่า
"""

from __future__ import annotations

from dataclasses import dataclass
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from typing import Literal

EditionStatus = Literal["old", "current"]
DegreeLevel = Literal["bachelor", "master", "doctoral"]
ExtractionMethod = Literal[
    "text_layer",
    "ocr_tesseract",
    "ocr_typhoon",
    "ocr_adjudicated",
    "table_cell",
    "derived",
]
ProvenanceSource = Literal["document_text", "filename"]
QuestionLevel = Literal["L1", "L2", "L3", "L4"]
PageStatus = Literal["page_pending", "page_complete", "page_error"]


class ComputePath(StrEnum):
    """เส้นทางประมวลผลของหน้า (R4.7) — แนวคิดปรับจาก katgpt-rs percept_router."""

    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class HaltDecision(StrEnum):
    HALT = "halt"
    CONTINUE = "continue"


class HaltReason(StrEnum):
    """เหตุผลการหยุดที่ต้องบันทึกลง store หรือ query_trace."""

    OSCILLATION = "oscillation"
    NAN_GUARD = "nan_guard"
    GAIN_BELOW_COST = "gain_below_cost"
    MAX_HOPS_REACHED = "max_hops_reached"
    NO_NEW_EVIDENCE = "no_new_evidence"
    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"


# ── geometry ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BBox:
    """กรอบสี่เหลี่ยมในระบบพิกัดของหน้า (จุดกำเนิดมุมซ้ายบนตาม PyMuPDF)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def is_valid(self) -> bool:
        """R9.2 บังคับ x1 > x0 และ y1 > y0 สำหรับ bbox ที่เก็บลง provenance."""
        return self.x1 > self.x0 and self.y1 > self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def iou(self, other: BBox) -> float:
        """Intersection over union — ใช้จับคู่ผลข้าม OCR engine (R5.10)."""
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        intersection = (ix1 - ix0) * (iy1 - iy0)
        union = self.area + other.area - intersection
        if union <= 0.0:
            return 0.0
        return intersection / union

    def contains_x(self, x: float, slack: float = 0.0) -> bool:
        """คืน True เมื่อพิกัด x อยู่ในช่วงแนวนอนของกรอบ (บวก slack ได้)."""
        return (self.x0 - slack) <= x <= (self.x1 + slack)

    def within(self, page_width: float, page_height: float, tolerance: float = 0.5) -> bool:
        """คืน True เมื่อกรอบอยู่ภายในขอบเขตหน้า (R9.2)."""
        return (
            self.x0 >= -tolerance
            and self.y0 >= -tolerance
            and self.x1 <= page_width + tolerance
            and self.y1 <= page_height + tolerance
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


# ── curriculum identity ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CurriculumVersion:
    """เวอร์ชันหลักสูตร — ต้องครบทั้งสามค่าเสมอ (R10.1)."""

    program: str
    curriculum_year: int
    edition_status: EditionStatus

    def __post_init__(self) -> None:
        if not self.program:
            raise ValueError("program ต้องไม่ว่าง")
        if not 2500 <= self.curriculum_year <= 2699:
            raise ValueError("curriculum_year ต้องเป็นปีพุทธศักราชสี่หลัก")
        if self.edition_status not in ("old", "current"):
            raise ValueError("edition_status ต้องเป็น old หรือ current")

    def key(self) -> tuple[str, int, str]:
        return (self.program, self.curriculum_year, self.edition_status)

    def label(self) -> str:
        """ข้อความสำหรับแสดงใน UI และในคำตอบ (R19.4)."""
        return f"{self.program} {self.curriculum_year} ({self.edition_status})"


def version_fingerprint(versions: frozenset[CurriculumVersion]) -> str:
    """ลายนิ้วมือของชุดเวอร์ชัน — ส่วนหนึ่งของ cache key (R10.10)."""
    return "|".join(f"{v.program}:{v.curriculum_year}:{v.edition_status}" for v in sorted(
        versions, key=lambda item: item.key()
    ))


# ── provenance ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Provenance:
    """ที่มาของค่าหนึ่งค่า — ทุกฟิลด์ต้องครบก่อนเขียนลง store (R9.2, R8.7)."""

    document_id: str
    page: int
    bbox: BBox
    span: tuple[int, int]
    extraction_method: ExtractionMethod

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id ต้องไม่ว่าง")
        if self.page < 1:
            raise ValueError("page ต้องเป็นจำนวนเต็มตั้งแต่ 1")
        start, end = self.span
        if start < 0 or end < start:
            raise ValueError("span ต้องเป็น (start, end) ที่ 0 <= start <= end")

    def is_complete(self) -> bool:
        """ตรวจความครบถ้วนก่อนเขียน — ผู้เรียกต้องปฏิเสธ transaction เมื่อ False."""
        return bool(self.document_id) and self.page >= 1 and self.bbox.is_valid()

    def missing_attributes(self) -> tuple[str, ...]:
        """คืนชื่อ attribute ที่ขาด เพื่อใส่ใน ProvenanceViolationError (R9.3)."""
        missing: list[str] = []
        if not self.document_id:
            missing.append("document_id")
        if self.page < 1:
            missing.append("page")
        if not self.bbox.is_valid():
            missing.append("bbox")
        if not self.extraction_method:
            missing.append("extraction_method")
        return tuple(missing)


# ── glyph / page ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CharRecord:
    """หนึ่ง glyph จาก PyMuPDF rawdict (R2.1).

    `order` คือลำดับที่ปรากฏใน input ใช้เป็น tie-break ทุกที่ที่ต้องเรียง
    เพื่อให้ผลลัพธ์ deterministic (R3.1, R3.6)
    """

    codepoint: str
    bbox: BBox
    font_name: str
    font_size: float
    baseline: float
    order: int

    def __post_init__(self) -> None:
        if len(self.codepoint) != 1:
            raise ValueError("codepoint ต้องเป็นหนึ่ง unicode scalar")
        if self.order < 0:
            raise ValueError("order ต้องไม่ติดลบ")

    @property
    def is_zero_width(self) -> bool:
        """ความกว้าง bbox ใกล้ศูนย์ — สัญญาณของ combining mark ที่ต้องผูกกับ base."""
        return self.bbox.width <= 0.5


@dataclass(frozen=True, slots=True)
class PageCharSet:
    """ผลของ Text_Extractor ต่อหนึ่งหน้า — gate ที่บังคับลำดับตาม R2.1."""

    document_id: str
    page: int
    width_pt: float
    height_pt: float
    chars: tuple[CharRecord, ...]
    image_count: int
    image_area_ratio: float

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page ต้องเป็นจำนวนเต็มตั้งแต่ 1")
        if self.width_pt <= 0 or self.height_pt <= 0:
            raise ValueError("ขนาดหน้าต้องมากกว่า 0")
        if self.image_count < 0:
            raise ValueError("image_count ต้องไม่ติดลบ")
        if not 0.0 <= self.image_area_ratio <= 1.0:
            raise ValueError("image_area_ratio ต้องอยู่ในช่วง 0.0-1.0")

    @property
    def char_count(self) -> int:
        return len(self.chars)


@dataclass(frozen=True, slots=True)
class TextLine:
    """หนึ่งบรรทัดหลังประกอบด้วย Line_Assembler (R3.6)."""

    text: str
    bbox: BBox
    baseline: float
    order: int


# ── field values ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Credits:
    """โครงสร้างหน่วยกิต — ทุกค่าอยู่ในช่วง 0-30 (R8.2)."""

    total: int
    lecture: int
    lab: int
    self_study: int

    def __post_init__(self) -> None:
        for name, value in (
            ("total", self.total),
            ("lecture", self.lecture),
            ("lab", self.lab),
            ("self_study", self.self_study),
        ):
            if not 0 <= value <= 30:
                raise ValueError(f"{name} ต้องอยู่ในช่วง 0 ถึง 30")


@dataclass(frozen=True, slots=True)
class PrereqLeaf:
    code: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("รหัสวิชาใน prerequisite ต้องไม่ว่าง")


@dataclass(frozen=True, slots=True)
class PrereqAnd:
    children: tuple["PrereqNode", ...]


@dataclass(frozen=True, slots=True)
class PrereqOr:
    children: tuple["PrereqNode", ...]


@dataclass(frozen=True, slots=True)
class PrereqEmpty:
    """เงื่อนไขว่าง — ใช้แทนกรณี "ไม่มี" (R8.5)."""


PrereqNode = PrereqLeaf | PrereqAnd | PrereqOr | PrereqEmpty


def prereq_codes(node: PrereqNode) -> tuple[str, ...]:
    """คืนรหัสวิชาทุกตัวใน expression ตามลำดับที่ปรากฏ."""
    if isinstance(node, PrereqLeaf):
        return (node.code,)
    if isinstance(node, (PrereqAnd, PrereqOr)):
        out: list[str] = []
        for child in node.children:
            out.extend(prereq_codes(child))
        return tuple(out)
    return ()


def prereq_depth(node: PrereqNode) -> int:
    """ความลึกของการซ้อน and/or — ต้องไม่เกิน 3 ระดับ (R8.5)."""
    if isinstance(node, (PrereqAnd, PrereqOr)):
        if not node.children:
            return 1
        return 1 + max(prereq_depth(child) for child in node.children)
    return 0


# ── halter ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HaltVerdict:
    """ผลการตัดสินของ Gain_Cost_Halter (R5.2-R5.5, R14.5-R14.8)."""

    decision: HaltDecision
    reason: HaltReason | None
    gain: float
    cost: float
    iterations_done: int

    @property
    def should_halt(self) -> bool:
        return self.decision is HaltDecision.HALT


# ── citation ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CitationId:
    """citation ID ที่ระบบออกให้เท่านั้น — LLM ห้ามสร้างเอง (R17.2, R17.3)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("citation id ต้องไม่ว่าง")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PageResult:
    """ผลของหนึ่งหน้าที่พร้อม commit แบบ atomic (R6.7)."""

    document_id: str
    page: int
    status: PageStatus
    text: str
    lines: tuple[TextLine, ...]
    char_count: int
    image_count: int
    quality_score: float
    compute_path: ComputePath | None
    extraction_method: ExtractionMethod
    ocr_invoked: bool

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page ต้องเป็นจำนวนเต็มตั้งแต่ 1")
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score ต้องอยู่ในช่วง 0.0-1.0")
