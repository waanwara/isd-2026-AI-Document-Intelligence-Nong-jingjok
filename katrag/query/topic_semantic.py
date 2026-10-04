"""Semantic topic path — ตอบคำถาม "วิชาเกี่ยวกับ X มีกี่วิชา/อะไรบ้าง".

ปัญหาเดิม: keyword matching เปราะ — ถาม "วิชาคณิต" ไม่ได้ "ความน่าจะเป็นและสถิติ"
เพราะชื่อวิชาไม่มีคำว่า คณิต/MATH/แคลคูลัส

วิธีแก้ (3 ขั้น):
  1. RECALL   — ค้นเชิงความหมายด้วย bge-m3 (course embeddings) ∪ keyword matching
  2. FILTER   — ให้ LLM ตัดสินว่าวิชาไหน "เกี่ยวจริง" โดยตอบกลับเป็น *รหัสวิชา* เท่านั้น
                (output สั้น → โอกาสที่ LLM ตกหล่น/ตัดคำตอบต่ำมาก)
  3. FORMAT   — เราจัดรูปคำตอบเองแบบ deterministic จากรหัสที่ LLM เลือก
                → ได้ชื่อไทย+อังกฤษ, หน่วยกิต, ชั้นปี/ภาค, ยอดรวม ครบทุกครั้ง

ถ้า LLM ล้มเหลว → fallback ใช้ score gate (ยังตอบได้ ไม่ล่ม)
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from katrag.query.course_semantic import CourseHit, CourseSemanticIndex, current_version_ids

# ── คำถาม/คำกริยาที่ไม่ใช่ "หัวข้อวิชา" — ตัดออกก่อน embed เพื่อลด noise ──
_QUESTION_NOISE = [
    # ถามชื่อ/รายละเอียดของวิชา — ต้องตัดก่อน ไม่งั้น "ภาษาอังกฤษ" กลายเป็นหัวข้อ
    # แล้วไปดึงวิชา "ภาษาอังกฤษพื้นฐาน" มาเป็นคำตอบ
    "ชื่อภาษาอังกฤษว่าอะไร", "ชื่อภาษาอังกฤษคืออะไร", "ชื่อภาษาอังกฤษ",
    "ชื่ออังกฤษว่าอะไร", "ชื่ออังกฤษคืออะไร", "ชื่ออังกฤษ",
    "ชื่อภาษาไทยว่าอะไร", "ชื่อภาษาไทย", "ชื่อไทย",
    "ภาษาอังกฤษว่าอะไร", "ภาษาอังกฤษเรียกว่าอะไร",
    "ว่าอะไร", "คืออะไร", "แปลว่าอะไร", "เรียกว่าอะไร",
    "มีกี่หน่วยกิต", "กี่หน่วยกิต", "มีกี่วิชา", "กี่วิชา", "มีกี่ตัว", "กี่ตัว",
    "มีอะไรบ้าง", "อะไรบ้าง", "มีวิชาอะไร", "ได้บ้าง", "บ้าง",
    "เรียนปีไหน", "เรียนตอนไหน", "ปีไหน", "เทอมอะไร", "เทอมไหน",
    "อยากทราบ", "ช่วยบอก", "บอกหน่อย", "ตอบหน่อย", "หน่อย",
    "ครับ", "ค่ะ", "คะ", "ทั้งหมด", "รวม", "จำนวน",
    "ที่เกี่ยวข้องกับ", "ที่เกี่ยวกับ", "เกี่ยวข้องกับ", "เกี่ยวกับ",
    "รายวิชา", "วิชา", "หลักสูตร", "ของ", "ใน", "มี", "?", "？",
]

# คำที่บ่งชี้ว่าเป็นคำถามหัวข้อวิชา (ไม่ใช่คำถามชั้นปี/แผน)
_TOPIC_TRIGGER = ["วิชา", "รายวิชา", "หน่วยกิต", "course", "subject"]

# คำถามเชิง "โครงสร้าง/เกณฑ์หลักสูตร" — ไม่ใช่การถามรายชื่อวิชาตามหัวข้อ
# (เช่น "หมวดวิชาเฉพาะเลือกเก็บกี่หน่วยกิต") ต้องปล่อยให้ retrieval ปกติจัดการ
_STRUCTURE_MARKERS = [
    "หมวดวิชา", "หมวดศึกษาทั่วไป", "หมวดเลือกเสรี", "โครงสร้างหลักสูตร",
    "หน่วยกิตรวม", "หน่วยกิตทั้งหมด", "รวมทั้งหลักสูตร", "ตลอดหลักสูตร",
    "เกณฑ์", "เงื่อนไขการจบ", "จบการศึกษา", "สำเร็จการศึกษา", "ไม่น้อยกว่า",
    # ระเบียบ/กฎการลงทะเบียนและสถานะนักศึกษา — ไม่ใช่การถามรายชื่อวิชา
    # (เช่น "หนึ่งเทอมลงทะเบียนได้กี่หน่วยกิต" มีคำว่า "หน่วยกิต" จึงเคยถูก
    # is_topic_question ดักไปค้นชื่อวิชาที่คล้ายคำถามผิด ๆ)
    "ลงทะเบียนได้", "ลงทะเบียนเรียนได้", "ลงทะเบียนไม่เกิน", "ลงทะเบียนต่ำสุด",
    "ลงทะเบียนสูงสุด", "ถอนรายวิชา", "ถอนวิชา", "เกียรตินิยม", "เกรดเฉลี่ย",
    "แต้มเฉลี่ย", "พ้นสภาพ", "วิทยฐานะ", "ภาคทัณฑ์",
    # คำถามภาพรวม "มีกี่ X" — ไม่ใช่การถามหาชื่อวิชา แต่เป็น count ของหมวด/แขนง
    # (เช่น "IT 2565 มีกี่แขนงวิชา" ต้องไปหาจำนวน specialization ไม่ใช่ค้นชื่อวิชา)
    "กี่แขนง", "มีแขนง", "กี่โมดูล", "มีโมดูล", "กี่สาขา", "มีสาขา",
    # คำถามเรื่องประเภทแผนการเรียน (แผนปกติ/สหกิจ, แผน ก/ข, วิชาการ/วิชาชีพ)
    # และหลักสูตรบัณฑิตศึกษา — ถามโครงสร้างของแผน ไม่ใช่รายชื่อวิชาตามหัวข้อ
    "แผนสหกิจ", "แผนปกติ", "สหกิจศึกษา", "เข้าโครงการ", "แผนการศึกษา", "แผนการเรียน",
    "แผนวิชาการ", "แผนวิชาชีพ", "แผน ก", "แผน ข", "ปริญญาโท", "ปริญญาเอก",
    "กี่กลุ่มวิชา", "กี่แนว", "กี่หมวด", "กี่ทาง", "กี่ track", "กี่ Track",
]

# วิชา "ปลอกเปล่า" — ชื่อไม่บอกเนื้อหา (หัวข้อพิเศษ/โครงงาน/สัมมนา/ฝึกงาน)
# embedding ของวิชากลุ่มนี้ใกล้กับทุกหัวข้อ → เป็น noise หลัก
# จะรับเข้า candidate เฉพาะเมื่อชื่อวิชามีคำของหัวข้อปรากฏตรง ๆ
_PLACEHOLDER_RE = re.compile(
    r"หัวข้อพิเศษ|หัวข้อคัดสรร|หัวข้อเฉพาะ|ปฏิบัติการพิเศษ|สัมมนา|โครงงาน|ปริญญานิพนธ์"
    r"|สหกิจ|ฝึกงาน|เตรียมความพร้อม|การศึกษาเอกเทศ|วิชาเลือก"
    r"|SPECIAL\s+TOPIC|SELECTED\s+TOPIC|SPECIAL\s+WORKSHOP|SEMINAR|PROJECT"
    r"|COOPERATIVE|INTERNSHIP|INDEPENDENT\s+STUD",
    re.IGNORECASE,
)

# หลักสูตรที่เลิกรับแล้ว (BIT = ชื่อเดิมของ AIT) — ไม่นับในคำถามแบบ "ทุกหลักสูตร"
LEGACY_PROGRAMS = {"BIT"}

# คำบ่งชี้ว่าคำถามต้องการ "หลายวิชา" — ห้ามเข้าเส้นทางตอบวิชาเดียว
# เช่น "วิชาเกี่ยวกับปัญญาประดิษฐ์มีอะไรบ้าง" มีวิชาชื่อ "ปัญญาประดิษฐ์" ตรงตัว
# แต่ผู้ถามต้องการรายการทั้งหมด ไม่ใช่วิชานั้นวิชาเดียว
_PLURAL_MARKERS = [
    "มีอะไรบ้าง", "อะไรบ้าง", "บ้าง", "กี่วิชา", "กี่ตัว", "กี่หน่วยกิต",
    "ทั้งหมด", "รายการ", "มีอะไร", "เกี่ยวกับ", "เกี่ยวข้อง", "กลุ่ม",
]


def wants_multiple(question: str) -> bool:
    """คำถามนี้ต้องการรายการหลายวิชาหรือไม่."""
    return any(m in question for m in _PLURAL_MARKERS)

_PROGRAM_CODES = ["AITBA", "DSBA", "AIT", "BIT", "IT"]


def detect_program_code(question: str) -> str | None:
    """ตรวจรหัสหลักสูตรจากคำถาม — เฉพาะรหัสตรง ๆ เท่านั้น.

    ต่างจาก structured_query.detect_program ที่ map คำไทย ("ปัญญาประดิษฐ์" → AIT)
    ซึ่งผิดในบริบทนี้ เพราะ "วิชาเกี่ยวกับปัญญาประดิษฐ์" คือ *หัวข้อ* ไม่ใช่หลักสูตร
    """
    up = question.upper()
    for code in _PROGRAM_CODES:
        if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", up):
            return code
    return None


@dataclass
class TopicResult:
    matched: bool = False
    context: str = ""
    version_label: str = ""
    intent: str = "none"
    topic: str = ""
    candidates: list[CourseHit] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# 0. Topic extraction
# ══════════════════════════════════════════════════════════════════════


def clean_topic(question: str, program: str | None = None) -> str:
    """ตัดคำถาม/ชื่อหลักสูตรออก เหลือเฉพาะ 'หัวข้อ' เพื่อ embed.

    "หลักสูตร DSBA: มีวิชาเขียนโปรแกรมกี่หน่วยกิต" → "เขียนโปรแกรม"
    """
    q = re.sub(r"หลักสูตร\s+[A-Za-z]+\s*[:：]", " ", question)
    if program:
        q = re.sub(rf"(?i)\b{re.escape(program)}\b", " ", q)
    for w in _QUESTION_NOISE:
        q = q.replace(w, " ")
    q = re.sub(r"\s+", " ", q).strip()
    # ถ้าตัดจนเหลือน้อยเกินไป ใช้คำถามเดิม (embedding ยังพอเข้าใจ)
    if len(q) < 2:
        q = re.sub(r"หลักสูตร\s+[A-Za-z]+\s*[:：]", " ", question).strip()
    return q


def is_topic_question(question: str, program: str | None = None) -> bool:
    """คำถามนี้เป็นการถามรายชื่อวิชาตามหัวข้อหรือไม่.

    ต้องเข้าเงื่อนไขทั้งสาม:
      1. มีคำที่บ่งชี้ว่าถามถึงรายวิชา/หน่วยกิต
      2. ไม่ใช่คำถามโครงสร้าง/เกณฑ์หลักสูตร
      3. เหลือ "หัวข้อ" ที่มีเนื้อความพอจะค้นได้หลังตัดคำถามออก
    """
    ql = question.lower()
    if not any(t in ql for t in _TOPIC_TRIGGER):
        return False
    if any(m in question for m in _STRUCTURE_MARKERS):
        return False
    return len(clean_topic(question, program)) >= 3


# ══════════════════════════════════════════════════════════════════════
# 1. RECALL — semantic ∪ keyword
# ══════════════════════════════════════════════════════════════════════


def _keyword_hits(
    conn: sqlite3.Connection, topic: str, version_ids: list[int]
) -> list[CourseHit]:
    """ค้นตรงจากชื่อวิชา — เพิ่ม recall สำหรับคำที่ปรากฏในชื่อจริง ๆ."""
    from katrag.query.structured_query import _extract_topic_keywords

    kws = [k for k in _extract_topic_keywords(topic, None) if len(k) >= 3]
    if not kws or not version_ids:
        return []
    where_kw = " OR ".join(["c.name_th LIKE ? OR c.name_en LIKE ?"] * len(kws))
    ph = ",".join("?" * len(version_ids))
    params: list = []
    for k in kws:
        params.extend([f"%{k}%", f"%{k}%"])
    params.extend(version_ids)
    rows = conn.execute(
        f"SELECT c.code, c.name_th, c.name_en, c.credits_raw, c.year, c.semester, "
        f"       c.version_id, cv.program, cv.curriculum_year "
        f"FROM course c JOIN curriculum_version cv ON cv.version_id = c.version_id "
        f"WHERE ({where_kw}) AND c.version_id IN ({ph}) ORDER BY c.code",
        params,
    ).fetchall()
    return [
        CourseHit(
            code=r["code"], name_th=r["name_th"], name_en=r["name_en"],
            credits_raw=r["credits_raw"], program=r["program"],
            curriculum_year=r["curriculum_year"], score=1.0,
            year=r["year"], semester=r["semester"], version_id=r["version_id"],
        )
        for r in rows
    ]


def _topic_keywords(topic: str) -> list[str]:
    from katrag.query.structured_query import _extract_topic_keywords

    return [k for k in _extract_topic_keywords(topic, None) if len(k) >= 3]


def _norm_name(s: str | None) -> str:
    return "".join((s or "").split()).lower()


def find_exact_course(
    conn: sqlite3.Connection, topic: str, version_ids: list[int]
) -> list[CourseHit]:
    """ตรวจว่าคำถามชี้ถึง *วิชาเดียว* ชัดเจนหรือไม่.

    เช่น "วิชาระบบข้อมูลมหัต ชื่อภาษาอังกฤษว่าอะไร" → topic = "ระบบข้อมูลมหัต"
    ซึ่งตรงกับชื่อวิชา 06026213 แบบเต็ม ๆ ไม่ใช่การถามหัวข้อกว้าง

    ถ้าเข้าเงื่อนไขนี้ต้องตอบและอ้างอิงเฉพาะวิชานั้น ไม่ใช่ดึงวิชาที่มีคำร่วมกันมาทั้งหมด
    (เดิมคำว่า "ระบบ"/"ข้อมูล" ทำให้ได้วิชาอื่นมาอีก 11 วิชา)

    คืน list ว่างถ้าไม่ใช่คำถามเจาะวิชาเดียว
    """
    if not topic or not version_ids or len(topic) < 6:
        return []
    conn.row_factory = sqlite3.Row
    ntopic = _norm_name(topic)

    ph = ",".join("?" * len(version_ids))
    rows = conn.execute(
        f"SELECT c.code, c.name_th, c.name_en, c.credits_raw, c.year, c.semester, "
        f"       c.version_id, cv.program, cv.curriculum_year "
        f"FROM course c JOIN curriculum_version cv ON cv.version_id = c.version_id "
        f"WHERE c.version_id IN ({ph})",
        version_ids,
    ).fetchall()

    exact: list[CourseHit] = []
    for r in rows:
        nth = _norm_name(r["name_th"])
        nen = _norm_name(r["name_en"])
        # ชื่อวิชาตรงกับ topic ทั้งชื่อ หรือ topic ครอบชื่อวิชาไว้ทั้งชื่อ
        if not nth and not nen:
            continue
        hit = (
            (nth and (nth == ntopic or ntopic == nth))
            or (nth and len(nth) >= 6 and nth in ntopic)
            or (nen and len(nen) >= 6 and nen in ntopic)
        )
        if hit:
            exact.append(
                CourseHit(
                    code=r["code"], name_th=r["name_th"], name_en=r["name_en"],
                    credits_raw=r["credits_raw"], program=r["program"],
                    curriculum_year=r["curriculum_year"], score=1.0,
                    year=r["year"], semester=r["semester"], version_id=r["version_id"],
                )
            )

    # ต้องชี้ชัดจริง — ถ้าตรงหลายวิชาข้ามหลายรหัส ถือว่าเป็นคำถามกว้าง
    if len({h.code for h in exact}) > 3:
        return []
    return exact


def _literal_match(hit: CourseHit, keywords: list[str]) -> bool:
    """ชื่อวิชามีคำของหัวข้อปรากฏตรง ๆ หรือไม่."""
    blob = f"{hit.name_th} {hit.name_en}".lower()
    return any(k.lower() in blob for k in keywords)


def gather_candidates(
    conn: sqlite3.Connection,
    index: CourseSemanticIndex,
    question: str,
    program: str | None,
    *,
    min_score: float = 0.48,
    rel_margin: float = 0.15,
    per_program_cap: int = 18,
) -> tuple[str, list[CourseHit], dict[int, str]]:
    """สร้าง candidate pool = semantic hits ∪ keyword hits (จำกัดเวอร์ชัน current)."""
    conn.row_factory = sqlite3.Row
    version_ids, labels = current_version_ids(conn, program)
    if not version_ids:
        return "", [], {}

    topic = clean_topic(question, program)
    sem = index.search(
        topic, version_ids=version_ids, top_k=80,
        min_score=min_score, rel_margin=rel_margin,
    )
    kw = _keyword_hits(conn, topic, version_ids)

    # union — key ด้วย (version_id, code); keyword hit ได้ score สูงสุด
    merged: dict[tuple[int, str], CourseHit] = {}
    for h in sem + kw:
        key = (h.version_id, h.code)
        prev = merged.get(key)
        if prev is None or h.score > prev.score:
            merged[key] = h

    # ตัดวิชา placeholder ที่ชื่อไม่บอกเนื้อหา (เว้นแต่ชื่อมีคำของหัวข้อตรง ๆ)
    kws = _topic_keywords(topic)
    filtered = [
        h for h in merged.values()
        if not _PLACEHOLDER_RE.search(f"{h.name_th} {h.name_en}")
        or _literal_match(h, kws)
    ]

    # จำกัดจำนวนต่อหลักสูตร (เรียงตาม score) กัน prompt ยาวเกิน
    by_prog: dict[str, list[CourseHit]] = {}
    for h in sorted(filtered, key=lambda x: -x.score):
        bucket = by_prog.setdefault(h.program, [])
        if len(bucket) < per_program_cap:
            bucket.append(h)

    out: list[CourseHit] = []
    for prog in sorted(by_prog):
        out.extend(by_prog[prog])
    return topic, out, labels


# ══════════════════════════════════════════════════════════════════════
# 2. FILTER — LLM เลือกรหัสวิชาที่เกี่ยวจริง
# ══════════════════════════════════════════════════════════════════════

_FILTER_PROMPT = """คุณเป็นผู้เชี่ยวชาญหลักสูตรวิทยาการคอมพิวเตอร์ หน้าที่ของคุณคือ *คัดเลือก* รายวิชา

หัวข้อที่ผู้ใช้ถาม: "{topic}"

รายการด้านล่างเป็นวิชาที่ *ชื่อวิชาไม่มีคำว่า "{topic}" ปรากฏตรง ๆ* แต่ระบบค้นเชิงความหมาย
พบว่าอาจเกี่ยวข้อง คุณต้องตัดสินว่าวิชาใด "เป็นวิชาในสาขา {topic}" จริง

เกณฑ์:
- เลือกวิชาที่เนื้อหาหลักของวิชาอยู่ในสาขา {topic} แม้ชื่อจะใช้คำอื่น
- ห้ามเลือกวิชาที่เพียง *นำ* {topic} ไปใช้เป็นเครื่องมือในสาขาอื่น

ตัวอย่างการตัดสิน:
- หัวข้อ "คณิตศาสตร์" → เลือก "ความน่าจะเป็นและสถิติ", "สถิติเชิงเบย์", "พีชคณิตเชิงเส้น"
  (เป็นวิชาคณิตศาสตร์/สถิติ) แต่ไม่เลือก "การเรียนรู้ของเครื่อง", "พื้นฐานวิทยาการข้อมูล",
  "การวิเคราะห์ด้านการตลาด" (ใช้คณิตศาสตร์ แต่ไม่ใช่วิชาคณิตศาสตร์)
- หัวข้อ "เขียนโปรแกรม" → เลือก "โครงสร้างข้อมูลและอัลกอริทึม" (เขียนโค้ดเป็นแกนของวิชา)
  แต่ไม่เลือก "การหาค่าที่เหมาะที่สุด", "ระบบฐานข้อมูล"

รายการรายวิชาที่ต้องตัดสิน:
{listing}

รูปแบบคำตอบ:
- ตอบเป็น "รหัสวิชา" ที่เลือก คั่นด้วยเครื่องหมายจุลภาค บนบรรทัดเดียว ห้ามมีข้อความอธิบายใด ๆ
- ถ้าไม่แน่ใจว่าวิชาใดเข้าเกณฑ์ ให้ *ไม่เลือก* วิชานั้น
- ถ้าไม่มีวิชาใดเข้าเกณฑ์เลย ตอบว่า NONE

รหัสวิชาที่เลือก:"""


def _listing_for_prompt(cands: list[CourseHit]) -> str:
    lines = []
    for h in cands:
        en = f" / {h.name_en}" if h.name_en else ""
        lines.append(f"{h.code} | {h.name_th}{en}")
    # unique ตามรหัส (ข้ามหลักสูตรอาจซ้ำรหัส/ชื่อ) — ให้ LLM เห็นสั้นที่สุด
    return "\n".join(dict.fromkeys(lines))


def llm_select_codes(llm, topic: str, cands: list[CourseHit]) -> set[str] | None:
    """ให้ LLM เลือกรหัสวิชาที่เกี่ยวข้อง. คืน None ถ้าล้มเหลว."""
    if not cands:
        return set()
    prompt = _FILTER_PROMPT.format(topic=topic, listing=_listing_for_prompt(cands))
    try:
        raw = llm.generate(prompt, max_tokens=400)
    except Exception:
        return None
    if not raw:
        return None
    if "NONE" in raw.upper() and not re.search(r"\d{6,}", raw):
        return set()
    codes = set(re.findall(r"\b\d{6,10}\b", raw))
    valid = {h.code for h in cands}
    picked = codes & valid
    return picked if picked else None


# ══════════════════════════════════════════════════════════════════════
# 3. FORMAT — เราจัดคำตอบเอง (ครบทุกฟิลด์ ไม่ตกหล่น)
# ══════════════════════════════════════════════════════════════════════


def _credit_num(credits_raw: str) -> int:
    m = re.match(r"\s*(\d+)", credits_raw or "")
    return int(m.group(1)) if m else 0


def format_answer(topic: str, selected: list[CourseHit], program: str | None) -> str:
    """จัดคำตอบสุดท้าย — แยกตามหลักสูตร, เรียงตามชั้นปี/ภาค, มีชื่ออังกฤษ + ยอดรวม."""
    if not selected:
        return f"ไม่พบรายวิชาที่เกี่ยวข้องกับ \"{topic}\" ในหลักสูตรที่ค้นหา"

    by_prog: dict[str, list[CourseHit]] = {}
    for h in selected:
        by_prog.setdefault(f"{h.program} {h.curriculum_year}", []).append(h)

    scope = f"หลักสูตร {program}" if program else "ทุกหลักสูตร (ที่ใช้อยู่ปัจจุบัน)"
    out = [f"วิชาที่เกี่ยวข้องกับ \"{topic}\" — {scope}", ""]

    for label in sorted(by_prog):
        rows = sorted(
            by_prog[label],
            key=lambda h: (h.year or 9, h.semester or 9, h.code),
        )
        credits = sum(_credit_num(r.credits_raw) for r in rows)
        out.append(f"■ {label} — {len(rows)} วิชา รวม {credits} หน่วยกิต")
        for r in rows:
            en = f" ({r.name_en})" if r.name_en else ""
            out.append(f"  - {r.code} {r.name_th}{en}")
            out.append(f"      หน่วยกิต {r.credits_raw} | {r.plan_label}")
        out.append("")

    if len(by_prog) > 1:
        tot_c = sum(_credit_num(h.credits_raw) for h in selected)
        out.append(f"รวมทุกหลักสูตร: {len(selected)} วิชา {tot_c} หน่วยกิต")
    return "\n".join(out).rstrip()


# ══════════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════════


def answer_topic(
    conn: sqlite3.Connection,
    index: CourseSemanticIndex,
    question: str,
    program: str | None,
    llm=None,
) -> TopicResult:
    """เส้นทางตอบคำถามหัวข้อวิชาแบบเชิงความหมาย (recall → filter → format).

    แบ่ง candidate เป็น 2 ชั้น:
      - literal tier: ชื่อวิชามีคำของหัวข้อตรง ๆ → รับทันที (ไม่ต้องให้ LLM ตัดสิน
        เพราะชัดเจนอยู่แล้ว และกัน LLM ตัดวิชาที่ควรมีทิ้ง)
      - semantic tier: ชื่อไม่มีคำนั้น แต่ embedding ว่าใกล้ → ให้ LLM ตัดสิน
        (จุดนี้คือที่ "ความเข้าใจเชิงความหมาย" สร้างค่า เช่น ความน่าจะเป็นและสถิติ ↔ คณิตศาสตร์)
    """
    topic, cands, _labels = gather_candidates(conn, index, question, program)
    if not cands:
        return TopicResult(matched=False)

    # ── ถ้าคำถามชี้วิชาเดียวชัดเจน → ตอบเฉพาะวิชานั้น ──
    # ต้องเช็คก่อน เพราะ semantic/keyword recall จะดึงวิชาที่มีคำร่วมกันมาด้วย
    # ทำให้ทั้งคำตอบและ citation กว้างเกินความจำเป็น
    # แต่ต้องไม่ทริกเกอร์เมื่อคำถามขอรายการ ("มีอะไรบ้าง", "กี่วิชา")
    version_ids, _lbl = current_version_ids(conn, program)
    exact = [] if wants_multiple(question) else find_exact_course(conn, topic, version_ids)
    if exact:
        answer = format_answer(topic, exact, program)
        return TopicResult(
            matched=True, context=answer,
            version_label=program or "ทุกหลักสูตร",
            intent="topic_semantic", topic=topic, candidates=exact,
        )

    kws = _topic_keywords(topic)
    literal = [h for h in cands if _literal_match(h, kws)]
    semantic_only = [h for h in cands if not _literal_match(h, kws)]

    picked_codes: set[str] | None = None
    if llm is not None and semantic_only:
        picked_codes = llm_select_codes(llm, topic, semantic_only)

    if picked_codes is None and semantic_only:
        # ไม่มี LLM / LLM ล้มเหลว → score gate เข้มกับชั้น semantic
        best = max(h.score for h in semantic_only)
        gate = max(0.60, best - 0.05)
        extra = [h for h in semantic_only if h.score >= gate]
    else:
        extra = [h for h in semantic_only if h.code in (picked_codes or set())]

    selected = literal + extra

    if not selected:
        return TopicResult(matched=False, topic=topic, candidates=cands)

    answer = format_answer(topic, selected, program)
    label = program or "ทุกหลักสูตร"
    return TopicResult(
        matched=True, context=answer, version_label=label,
        intent="topic_semantic", topic=topic, candidates=cands,
    )
