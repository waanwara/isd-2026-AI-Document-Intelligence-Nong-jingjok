"""Lightweight lexical retriever สำหรับ curriculum Q&A.

ออกแบบสำหรับข้อความภาษาไทย (ไม่มีช่องว่างระหว่างคำ) จึงใช้ LIKE substring
แทน FTS5 tokenizer ที่แยกคำไทยไม่ได้ดี พร้อมกลยุทธ์:

1. ตรวจจับ program (DSBA/IT/AIT/BIT/AITBA) จากคำถาม → filter เฉพาะ version
2. ตรวจจับปีหลักสูตร (พ.ศ. 25xx) → filter เพิ่ม
3. ตัด stopword ไทย → เหลือ content words
4. ให้คะแนนแบบ OR (นับจำนวน keyword ที่ match) + bonus เมื่อ match ในหัวข้อ
   และ bonus เมื่อคำถามถามเรื่องแผนการเรียน/ชั้นปี
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

try:
    from pythainlp.tokenize import word_tokenize as _thai_tokenize

    _HAS_PYTHAINLP = True
except Exception:  # pragma: no cover
    _HAS_PYTHAINLP = False

# ── Thai stopwords — คำที่ไม่ควรใช้เป็น search term ──
THAI_STOPWORDS: set[str] = {
    "อะไร", "เรียน", "บ้าง", "มี", "คือ", "ของ", "ที่", "การ", "และ", "ใน",
    "ต้อง", "ได้", "ให้", "จะ", "เป็น", "กี่", "ไหน", "อย่างไร", "ยังไง",
    "ทำไม", "หรือ", "ก็", "แล้ว", "ด้วย", "จาก", "โดย", "เพื่อ", "ตาม",
    "นี้", "นั้น", "ช่วย", "บอก", "หน่อย", "ครับ", "ค่ะ", "คะ", "จ๊ะ",
    "เท่าไหร่", "เท่าไร", "ควร", "อยาก", "รู้", "ดู", "ขอ", "ทั้งหมด",
    "ราย", "วิชา", "ปี",
}

# ── Program aliases — คำที่บ่งบอกหลักสูตร ──
# ตรวจ code ยาวก่อนสั้น (AITBA ก่อน AIT, DSBA ก่อน ...)
PROGRAM_CODES: list[str] = ["AITBA", "DSBA", "AIT", "BIT", "IT"]

PROGRAM_KEYWORDS: dict[str, list[str]] = {
    "DSBA": ["วิทยาการข้อมูล", "วิเคราะห์เชิงธุรกิจ", "ดาต้า", "data science"],
    "AIT": ["ปัญญาประดิษฐ์", "เทคโนโลยีปัญญาประดิษฐ์"],
    "AITBA": ["ปัญญาประดิษฐ์ทางธุรกิจ"],
    "BIT": ["เทคโนโลยีสารสนเทศทางธุรกิจ"],
    "IT": ["เทคโนโลยีสารสนเทศ"],
}

# ── คำที่บ่งบอกว่าถามเรื่องแผนการเรียน/รายวิชาตามชั้นปี ──
STUDY_PLAN_HINTS = ["แผนการศึกษา", "แผนการเรียน", "ชั้นปีที่", "ปีที่", "รายวิชา"]

# ── รหัสวิชา 8 หลัก — ใช้ระบุ chunk ที่เป็นตารางรายวิชาจริง ──
_COURSE_CODE_RE = re.compile(r"\b\d{8}\b")

# ── Thai combining marks ที่ text layer บางเอกสารตกหล่น ──
# ตัดออกก่อนเทียบ เพื่อให้ "หน่วยกิต" match "หนวยกิต", "ข้อมูล" match "ขอมูล"
_THAI_TONE_MARKS = "\u0e48\u0e49\u0e4a\u0e4b\u0e4c"  # ่ ้ ๊ ๋ ์
_TONE_TABLE = {ord(c): None for c in _THAI_TONE_MARKS}


def normalize(text: str) -> str:
    """ตัดวรรณยุกต์/ทัณฑฆาตไทยออก เพื่อการเทียบแบบทนต่อ glyph ที่ตกหล่น."""
    return text.translate(_TONE_TABLE)


@dataclass
class RetrievedChunk:
    chunk_id: int
    page_number: int
    heading: str
    text: str
    program: str
    curriculum_year: int
    edition_status: str
    score: float
    # เอกสารต้นทาง — ใช้สร้าง citation ที่ตรวจย้อนกลับได้
    document_id: str = ""


def detect_program(question: str) -> str | None:
    """ตรวจจับ program code จากคำถาม (case-insensitive, word boundary)."""
    upper = question.upper()
    for code in PROGRAM_CODES:
        # word boundary — ไม่ match กลางคำ
        if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            return code
    # fallback: keyword ภาษาไทย
    for prog, kws in PROGRAM_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in question.lower():
                return prog
    return None


def detect_year(question: str) -> int | None:
    """ตรวจจับปีหลักสูตร พ.ศ. (2560-2599) จากคำถาม."""
    m = re.search(r"\b(25\d\d)\b", question)
    if m:
        return int(m.group(1))
    return None


def detect_year_level(question: str) -> int | None:
    """ตรวจจับชั้นปี (ปี 1-4) เช่น 'ปีหนึ่ง' 'ปี 1' 'ชั้นปีที่ 2'."""
    thai_num = {"หนึ่ง": 1, "สอง": 2, "สาม": 3, "สี่": 4}
    for word, n in thai_num.items():
        if f"ปี{word}" in question or f"ปีที่{word}" in question:
            return n
    m = re.search(r"ปี(?:ที่)?\s*([1-4])", question)
    if m:
        return int(m.group(1))
    return None


def _tokenize(question: str) -> list[str]:
    """ตัดคำ — ใช้ pythainlp ถ้ามี (แยกคำไทยที่ติดกัน), ไม่งั้น fallback regex."""
    if _HAS_PYTHAINLP:
        toks = _thai_tokenize(question, keep_whitespace=False)
        out: list[str] = []
        for t in toks:
            t = t.strip()
            if not t:
                continue
            # แยก latin/ตัวเลขที่อาจติดมา
            out.extend(re.findall(r"[ก-๙]+|[A-Za-z]+|\d+", t) or [t])
        return out
    return re.findall(r"[ก-๙]+|[A-Za-z]+|\d+", question)


def extract_keywords(question: str, program: str | None) -> list[str]:
    """แยก content keywords: ตัดคำไทย, ตัด stopword, program code, และคำสั้นเกินไป.

    รวม synonym expansion สำหรับกลุ่มคำที่ใช้เป็นชื่อหมวดวิชาในหลักสูตร
    """
    raw = _tokenize(question)
    keywords: list[str] = []
    prog_upper = (program or "").upper()
    seen: set[str] = set()
    for tok in raw:
        if tok.upper() == prog_upper:
            continue
        if tok in THAI_STOPWORDS:
            continue
        if len(tok) < 2:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        keywords.append(tok)

    # ── Synonym expansion ──
    # คำว่า "เขียนโปรแกรม/coding/programming" ใช้ค้นวิชาทั้งหมดที่เกี่ยวกับ programming
    # ตรวจจาก combination ของ keywords (เช่น "เขียน"+"โปรแกรม" หรือ "โปรแกรม" เดี่ยว)
    raw_joined = "".join(raw).lower()
    programming_signals = ["เขียนโปรแกรม", "โปรแกรมมิ่ง", "programming", "coding"]
    has_programming = any(s in raw_joined for s in programming_signals) or (
        "เขียน" in seen and "โปรแกรม" in seen
    )
    if has_programming:
        # ลบ "เขียน" ออก (มันไม่ช่วย match) เพิ่ม "โปรแกรม" ให้มีอยู่แน่ ๆ
        keywords = [k for k in keywords if k != "เขียน"]
        if "โปรแกรม" not in [k for k in keywords]:
            keywords.insert(0, "โปรแกรม")

    return keywords


def search(
    conn: sqlite3.Connection,
    question: str,
    limit: int = 6,
    *,
    version_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    """ค้น chunks ที่เกี่ยวข้องที่สุดกับคำถาม."""
    conn.row_factory = sqlite3.Row

    program = detect_program(question)
    year = detect_year(question)
    year_level = detect_year_level(question)
    keywords = extract_keywords(question, program)

    # ── กำหนดขอบเขต version จาก program (+ year ถ้ามี) ──
    # ผู้เรียกระบุเวอร์ชันมาเองได้ (คำถามที่อ้างหลายเวอร์ชัน/หลายหลักสูตร)
    version_ids = list(version_ids or [])
    if program and not version_ids:
        if year:
            rows = conn.execute(
                "SELECT version_id FROM curriculum_version WHERE program=? AND curriculum_year=?",
                (program, year),
            ).fetchall()
            version_ids = [r[0] for r in rows]
        if not version_ids:
            rows = conn.execute(
                "SELECT version_id, edition_status FROM curriculum_version WHERE program=?",
                (program,),
            ).fetchall()
            current = [r["version_id"] for r in rows if r["edition_status"] == "current"]
            version_ids = current or [r["version_id"] for r in rows]

    # ── ดึง candidate chunks ──
    # ถ้ารู้ program → ดึงทุก chunk ใน version scope มา score ใน Python
    # ถ้าไม่รู้ → ใช้ keyword OR match เพื่อจำกัดจำนวน candidate
    where_parts: list[str] = []
    params: list[object] = []

    if version_ids:
        placeholders = ",".join("?" for _ in version_ids)
        where_parts.append(f"c.version_id IN ({placeholders})")
        params.extend(version_ids)
    else:
        kw_for_sql = keywords[:8]
        if kw_for_sql:
            or_clause = " OR ".join("c.text LIKE ?" for _ in kw_for_sql)
            where_parts.append(f"({or_clause})")
            params.extend(f"%{kw}%" for kw in kw_for_sql)

    # กัน chunk ที่เป็นหัว/ท้ายกระดาษซ้ำทุกหน้า (boilerplate) ออกจากผลค้น
    # chunk พวกนี้มีคำสำคัญของหลักสูตรครบแต่ไม่มีสาระ ทำให้ citation precision ตก
    # (คอลัมน์อาจไม่มีในฐานเก่า → ใช้ COALESCE กันพัง)
    where_parts.append("COALESCE(c.is_boilerplate, 0) = 0")

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"

    # version-scoped: ดึงทุก chunk ใน scope (มีขอบเขตจำกัดต่อหลักสูตรอยู่แล้ว)
    # ไม่ใส่ LIMIT ต่ำ มิฉะนั้นตารางแผนการศึกษาท้ายเล่มจะถูกตัดก่อน scoring
    limit_sql = "" if version_ids else "LIMIT 800"
    rows = conn.execute(
        f"SELECT c.chunk_id, c.document_id, c.page_number, c.heading, c.text, "
        f"cv.program, cv.curriculum_year, cv.edition_status "
        f"FROM chunk c JOIN curriculum_version cv ON cv.version_id = c.version_id "
        f"WHERE {where_sql} {limit_sql}",
        params,
    ).fetchall()

    asks_study_plan = any(h in question for h in STUDY_PLAN_HINTS) or year_level is not None
    # คำถามที่ต้องการ "รายวิชา" จริง (ไม่ใช่ภาพรวม) — บ่งด้วย เรียน/วิชา/รายวิชา + ชั้นปี
    asks_courses = year_level is not None and any(
        w in question for w in ["เรียน", "วิชา", "รายวิชา", "อะไร"]
    )
    # คำถามเรื่อง "วิชา" โดยทั่วไป (ไม่จำเป็นต้องระบุปี) — ใช้ให้ bonus chunk ที่มีรหัสวิชาหลายตัว
    asks_about_subjects = any(
        w in question for w in ["วิชา", "รายวิชา", "เรียน"]
    )
    norm_keywords = [(kw, normalize(kw)) for kw in keywords]
    norm_hints = [normalize(h) for h in STUDY_PLAN_HINTS]

    scored: list[RetrievedChunk] = []
    for r in rows:
        text = r["text"] or ""
        heading = r["heading"] or ""
        ntext = normalize(text)
        nheading = normalize(heading)
        score = 0.0
        for _kw, nkw in norm_keywords:
            if nkw in ntext:
                score += 1.0
            if nkw in nheading:
                score += 1.5  # bonus: อยู่ในหัวข้อ
        # bonus: คำถามเรื่องแผนการเรียน + chunk มีเนื้อหาแผน/ชั้นปี
        if asks_study_plan:
            for hint in norm_hints:
                if hint in ntext or hint in nheading:
                    score += 0.8
                    break
        # bonus: ชั้นปีตรงกับที่ถาม (เทียบกับ raw text — วรรณยุกต์ใน "ที่" ครบ)
        if year_level is not None:
            if f"ปีที่ {year_level}" in text or f"ชั้นปีที่ {year_level}" in text:
                score += 2.0
        # bonus: คำถามอยากได้รายวิชา + chunk เป็นตารางแผนการศึกษาที่มีรหัสวิชาจริง
        # (รหัสวิชา 8 หลัก + "ภาคการศึกษา") — ให้ตารางรายวิชาชนะ chunk ภาพรวม
        if asks_courses and "ภาคการศึกษา" in text and _COURSE_CODE_RE.search(text):
            score += 3.0
            # ตรงชั้นปีในตาราง เช่น "ปีที่ 1 ภาคการศึกษาที่ 1"
            if year_level is not None and f"ปีที่ {year_level} ภาคการศึกษา" in text:
                score += 3.0
        # bonus: chunk ที่มีรหัสวิชาหลายตัว = comprehensive course listing
        # ให้คะแนนเมื่อคำถามถามเรื่องวิชา (ไม่ว่าระบุปีหรือไม่)
        if asks_about_subjects and score > 0:
            n_codes = len(_COURSE_CODE_RE.findall(text))
            if n_codes >= 3:
                score += min(n_codes * 0.3, 3.0)  # bonus สูงสุด 3.0
        # ไม่มี keyword เลยแต่อยู่ใน version scope → ให้คะแนนน้อย ๆ
        if score == 0.0 and version_ids and not keywords:
            score = 0.1
        if score > 0.0:
            scored.append(
                RetrievedChunk(
                    chunk_id=r["chunk_id"],
                    page_number=r["page_number"],
                    heading=heading,
                    text=text,
                    program=r["program"] or "",
                    curriculum_year=r["curriculum_year"] or 0,
                    edition_status=r["edition_status"] or "",
                    score=score,
                    document_id=r["document_id"] or "",
                )
            )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]
