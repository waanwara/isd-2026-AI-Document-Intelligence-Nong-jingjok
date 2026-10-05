"""รายชื่ออาจารย์ผู้รับผิดชอบ/อาจารย์ประจำหลักสูตร อ่านจากหัวข้อ 3.2.1 / 3.2.2 ในเล่ม มคอ.2.

ตาราง `person` มีข้อมูลไม่ครบ (DSBA/BIT มีแต่ผู้รับผิดชอบ, IT ปริญญาตรีไม่มีเลย) ทั้งที่เล่มมีหัวข้อ
"3.2.2 อาจารย์ประจำหลักสูตร" ครบ รายชื่อในเล่มเรียงเป็น "1. รศ.ดร.ชื่อ นามสกุล" ตามด้วยเลขประจำตัว
ประชาชนและประวัติ — เก็บเฉพาะลำดับและชื่อ ไม่เก็บเลขประจำตัว
"""

from __future__ import annotations

import re
import sqlite3
from functools import lru_cache

_SECTION = {
    "responsible": re.compile(r"3\.\d\.1\s*อาจารย์ผู้รับผิดชอบหลักสูตร"),
    "regular": re.compile(r"3\.\d\.2\s*อาจารย์ประจำหลักสูตร"),
    "teaching": re.compile(r"3\.\d\.3\s*อาจารย์ผู้สอน"),
}
_SECTION_END = re.compile(r"3\.\d\.[3-9]\s*อาจารย์|3\.\d\.[3-9]\s|อาจารย์พิเศษ|หมวดที่\s*4|4\.\s*องค์ประกอบ")
_TITLE = r"(?:ศาสตราจารย์|รองศาสตราจารย์|ผู้ช่วยศาสตราจารย์|ศ\.|รศ\.|ผศ\.|อ\.|ดร\.|Asst\.|Assoc\.|Prof\.|Dr\.)"
_ENTRY = re.compile(rf"(?:^|\n|\|)\s*(\d{{1,2}})\.\s*({_TITLE}[^\n|()\d]{{2,60}})(?:\s*\|?\s*\n?\s*([ก-๙]{{2,30}})(?=\s*(?:\n|\||\()))?")


@lru_cache(maxsize=32)
def _cached(db_file: str, version_id: int) -> tuple[tuple[str, tuple[tuple[int, str, int], ...]], ...]:
    conn = sqlite3.connect(db_file)
    try:
        return tuple((k, tuple(v)) for k, v in _parse(conn, version_id).items())
    finally:
        conn.close()


def faculty_lists(conn: sqlite3.Connection, version_id: int) -> dict[str, list[tuple[int, str, int]]]:
    """{'responsible'|'regular': [(ลำดับ, ชื่อ, หน้า), ...]} จากเล่มของเวอร์ชันนี้."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if row and row[2]:
        return {k: list(v) for k, v in _cached(row[2], version_id)}
    return _parse(conn, version_id)


def _parse(conn: sqlite3.Connection, version_id: int) -> dict[str, list[tuple[int, str, int]]]:
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? ORDER BY document_id LIMIT 1", (version_id,)
    ).fetchone()
    if not doc:
        return {}
    pages = conn.execute(
        "SELECT page_number, page_text FROM page WHERE document_id=? AND page_number BETWEEN 20 AND 80 ORDER BY page_number",
        (doc[0],),
    ).fetchall()
    out: dict[str, list[tuple[int, str, int]]] = {}
    for role, start_re in _SECTION.items():
        names: list[tuple[int, str, int]] = []
        active = False
        for page_no, text in pages:
            seg = text
            if not active:
                m = start_re.search(text)
                if not m:
                    continue
                active = True
                seg = text[m.end():]
            end = _SECTION_END.search(seg)
            if end:
                seg = seg[: end.start()]
            for m in _ENTRY.finditer(seg):
                n = int(m.group(1))
                if names and n != names[-1][0] + 1:
                    continue
                if not names and n != 1:
                    continue
                name = re.sub(r"\s+", " ", m.group(2)).strip()
                if m.group(3) and not re.search(r"สาขา|วิชา", m.group(3)):
                    # ชื่อที่ขึ้นบรรทัดใหม่กลางนามสกุล (นามสกุลไทยไม่มีเว้นวรรค) — ต่อกันโดยไม่เว้น
                    name = f"{name}{m.group(3)}"
                names.append((n, name, page_no))
            if end:
                break
        if names:
            out[role] = names
    return out
