"""Populate หน่วยกิตตามโครงสร้างหลักสูตร (หมวด/กลุ่มวิชา) ลงตาราง `rule`.

ทุกค่าอ่านจากหน้า "โครงสร้างหลักสูตร" (3.1.2) ในเล่ม มคอ.2 โดยตรง เช่น DSBA 2565
หน้า 15: ก. หมวดวิชาศึกษาทั่วไป 30 / ข. หมวดวิชาเฉพาะ 96 / ค. เลือกเสรี 6
แล้วตัวตรวจ `verify_seed` ยืนยันซ้ำว่า "ชื่อกลุ่ม ... ตัวเลข หน่วยกิต" ปรากฏจริงในข้อความ
ของหน้านั้น (ข้ามบรรทัดได้) ก่อนจะเขียนลงฐาน — ตัวเลขที่ตรวจไม่ผ่านจะไม่ถูกบันทึก

โครงสร้างตาราง: ใช้ rule_kind='graduation' (schema จำกัดค่าไว้ ไม่เพิ่ม enum ใหม่)
attribute ขึ้นต้นด้วย `credits.` ระดับความลึกของ attribute (นับจุด) คือระดับกลุ่มย่อย
`value_text` เก็บชื่อกลุ่มตามที่เล่มเรียก + หมายเหตุ (เช่น ตัวเลขของแผนสหกิจ)

Usage:
    python -m katrag.ingest.populate_structure_rules
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# (attribute, ชื่อกลุ่มตามเล่ม, หน่วยกิต, หน้า, หมายเหตุ)
Row = tuple[str, str, float, int, str]

G = "credits.general_education"
S = "credits.specific"

STRUCTURE: dict[tuple[str, int], list[Row]] = {
    ("DSBA", 2565): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 15, ""),
        (G + ".basic", "กลุ่มวิชาพื้นฐาน", 6, 15, ""),
        (G + ".language", "กลุ่มวิชาด้านภาษาและการสื่อสาร", 9, 15, ""),
        (G + ".faculty", "กลุ่มวิชาตามเกณฑ์ของคณะ", 9, 15, ""),
        (G + ".elective", "กลุ่มวิชาเลือกหมวดวิชาการศึกษาทั่วไป", 6, 15, ""),
        (S, "หมวดวิชาเฉพาะ", 96, 15, ""),
        (S + ".core", "กลุ่มวิชาแกน", 45, 15, ""),
        (S + ".core.math_stat", "กลุ่มคณิตศาสตร์และสถิติ", 15, 15, ""),
        (S + ".core.it", "กลุ่มเทคโนโลยีสารสนเทศ", 30, 15, ""),
        (S + ".foundation", "กลุ่มพื้นฐานวิชาชีพ", 33, 15, ""),
        (S + ".professional", "กลุ่มวิชาชีพเฉพาะด้าน", 12, 15, "เลือกลงทะเบียนกลุ่มใดกลุ่มหนึ่ง รวม 12 หน่วยกิต"),
        (S + ".professional.data_science", "กลุ่มวิทยาการข้อมูล", 12, 15, "1 ใน 3 กลุ่มที่ให้เลือก"),
        (S + ".professional.statistics", "กลุ่มการวิเคราะห์เชิงสถิติ", 12, 15, "1 ใน 3 กลุ่มที่ให้เลือก"),
        (S + ".professional.data_engineering", "กลุ่มวิศวกรรมข้อมูล", 12, 15, "1 ใน 3 กลุ่มที่ให้เลือก"),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 6, 15, "แผนปกติ: กลุ่มวิชาเลือกหรือกลุ่มวิชาชีพเฉพาะด้าน 6 · แผนสหกิจ: สหกิจศึกษา 6"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 15, ""),
    ],
    ("IT", 2565): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 20, ""),
        (G + ".basic", "กลุ่มวิชาพื้นฐาน", 6, 20, ""),
        (G + ".language", "กลุ่มวิชาด้านภาษาและการสื่อสาร", 9, 20, ""),
        (G + ".faculty", "กลุ่มวิชาตามเกณฑ์ของคณะ", 9, 20, ""),
        (G + ".elective", "กลุ่มวิชาเลือกหมวดวิชาศึกษาทั่วไป", 6, 20, ""),
        (S, "หมวดวิชาเฉพาะ", 93, 20, ""),
        (S + ".core", "กลุ่มวิชาแกน", 12, 20, ""),
        (S + ".core.math_stat", "กลุ่มคณิตศาสตร์และสถิติ", 9, 20, ""),
        (S + ".core.it", "พื้นฐานเทคโนโลยีสารสนเทศ", 3, 20, ""),
        (S + ".professional", "กลุ่มวิชาเฉพาะด้าน", 57, 21, ""),
        (S + ".professional.org_systems", "กลุ่มประเด็นด้านองค์การและระบบสารสนเทศ", 9, 21, ""),
        (S + ".professional.applied_tech", "กลุ่มเทคโนโลยีเพื่องานประยุกต์", 27, 21, ""),
        (S + ".professional.software", "กลุ่มเทคโนโลยีและวิธีการทางซอฟต์แวร์", 12, 21, ""),
        (S + ".professional.infrastructure", "กลุ่มโครงสร้างพื้นฐานของระบบ", 9, 21, ""),
        (S + ".required_track", "กลุ่มวิชาบังคับเฉพาะสาขา", 15, 21, "เลือก 1 ใน 3 โมดูลวิชาสาขา ตอนขึ้นปี 3 ภาค 1"),
        (S + ".elective_it", "กลุ่มวิชาเลือกทางเทคโนโลยีสารสนเทศ", 9, 21, ""),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 6, 21, "สหกิจศึกษา 6 หน่วยกิต (เฉพาะผู้เลือกโครงการสหกิจศึกษา)"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 21, ""),
    ],
    ("BIT", 2565): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 18, ""),
        (G + ".basic", "กลุ่มวิชาพื้นฐาน", 6, 18, ""),
        (G + ".language", "กลุ่มวิชาด้านภาษาและการสื่อสาร", 9, 18, ""),
        (G + ".faculty", "กลุ่มวิชาตามเกณฑ์ของคณะ", 9, 18, ""),
        (G + ".elective", "กลุ่มวิชาเลือกหมวดวิชาการศึกษาทั่วไป", 6, 18, ""),
        (S, "หมวดวิชาเฉพาะ", 90, 18, ""),
        (S + ".core", "กลุ่มวิชาแกน", 12, 18, ""),
        (S + ".core.it", "กลุ่มพื้นฐานเทคโนโลยีสารสนเทศ", 3, 18, ""),
        (S + ".core.math_stat", "กลุ่มคณิตศาสตร์และสถิติสำหรับนักเทคโนโลยีสารสนเทศ", 9, 18, ""),
        (S + ".professional", "กลุ่มวิชาชีพเฉพาะด้าน", 72, 18, "แผนที่เข้าโครงการสหกิจศึกษา 66"),
        (S + ".professional.org_systems", "กลุ่มประเด็นด้านองค์การและระบบสารสนเทศ", 24, 18, "แผนสหกิจ 24"),
        (S + ".professional.applied_tech", "กลุ่มเทคโนโลยีเพื่องานประยุกต์", 24, 18, "แผนสหกิจ 18"),
        (S + ".professional.software", "กลุ่มเทคโนโลยีและวิธีการทางซอฟต์แวร์", 18, 18, "แผนสหกิจ 18"),
        (S + ".professional.infrastructure", "กลุ่มโครงสร้างพื้นฐานของระบบ", 6, 18, "แผนสหกิจ 6"),
        (S + ".elective_it", "กลุ่มวิชาเลือกทางเทคโนโลยีสารสนเทศทางธุรกิจ", 6, 19, "เลือก 6 หน่วยกิตจากกลุ่มวิชาต่าง ๆ"),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 6, 19, "สหกิจศึกษา 6 หน่วยกิต (เฉพาะแผนที่เข้าโครงการสหกิจศึกษา)"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 19, ""),
    ],
    ("AIT", 2566): [
        (G, "หมวดวิชาศึกษาทั่วไป", 24, 18, ""),
        (S, "หมวดวิชาเฉพาะ", 90, 18, ""),
        (S + ".math_stat", "กลุ่มวิชาพื้นฐานคณิตศาสตร์และสถิติ", 15, 18, ""),
        (S + ".cs_foundation", "กลุ่มวิชาพื้นฐานวิทยาศาสตร์คอมพิวเตอร์", 15, 18, ""),
        (S + ".ai_foundation", "กลุ่มวิชา พื้นฐานปัญญาประดิษฐ์", 33, 18, ""),
        (S + ".ai_elective", "กลุ่มวิชาเลือกปัญญาประดิษฐ์เฉพาะทาง", 12, 18, ""),
        (S + ".project_seminar", "กลุ่มวิชาโครงงานและสัมมนา", 15, 18, ""),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 18, ""),
    ],
    ("IT", 2560): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 18, ""),
        (G + ".humanities", "กลุ่มวิชามนุษย์ศาสตร์", 6, 18, ""),
        (G + ".social", "กลุ่มวิชาสังคมศาสตร์", 6, 18, ""),
        (G + ".language", "กลุ่มวิชาภาษา", 12, 18, ""),
        (G + ".science_math", "กลุ่มวิชาวิทยาศาสตร์กับคณิตศาสตร์", 6, 18, ""),
        (S, "หมวดวิชาเฉพาะ", 94, 18, ""),
        (S + ".core", "กลุ่มวิชาแกน", 12, 18, ""),
        (S + ".professional", "กลุ่มวิชาเฉพาะด้าน", 46, 18, ""),
        (S + ".required_track", "กลุ่มวิชาบังคับเฉพาะแขนง", 30, 18, "เลือก 1 ใน 3 แขนง ตอนขึ้นปี 2 ภาค 2"),
        (S + ".elective_it", "กลุ่มวิชาเลือกทางเทคโนโลยีสารสนเทศ", 6, 18, ""),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 6, 18, "โครงงานพิเศษ / สหกิจศึกษา / ฝึกงานต่างประเทศ"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 18, ""),
    ],
    ("BIT", 2560): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 17, ""),
        (G + ".language", "กลุ่มวิชาภาษา", 12, 17, ""),
        (G + ".science_math", "กลุ่มวิชาวิทยาศาสตร์กับคณิตศาสตร์", 6, 17, ""),
        (G + ".humanities", "กลุ่มวิชามนุษยศาสตร์", 6, 17, ""),
        (G + ".social", "กลุ่มวิชาสังคมศาสตร์", 6, 17, ""),
        (S, "หมวดวิชาเฉพาะ", 90, 17, ""),
        (S + ".core", "กลุ่มวิชาแกน", 9, 17, ""),
        (S + ".professional", "กลุ่มวิชาเฉพาะด้าน", 75, 17, ""),
        (S + ".elective_it", "กลุ่มวิชาเลือกทางเทคโนโลยีสารสนเทศทางธุรกิจ", 6, 17, ""),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 6, 17, "โครงการพิเศษ / สหกิจศึกษา / ฝึกงานต่างประเทศ"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 17, ""),
    ],
    ("DSBA", 2560): [
        (G, "หมวดวิชาศึกษาทั่วไป", 30, 17, ""),
        (S, "หมวดวิชาเฉพาะ", 90, 18, ""),
        (S + ".core", "กลุ่มวิชาแกน", 12, 18, ""),
        (S + ".professional", "กลุ่มวิชาเฉพาะด้าน", 69, 18, ""),
        (S + ".elective", "กลุ่มวิชาเลือก", 6, 18, "แผนที่เข้าโครงการสหกิจศึกษา 3"),
        (S + ".alternative", "กลุ่มวิชาการศึกษาทางเลือก", 3, 18, "แผนที่เข้าโครงการสหกิจศึกษา 6"),
        ("credits.free_elective", "หมวดวิชาเลือกเสรี", 6, 18, ""),
    ],
}


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def verify_seed(page_text: str, label: str, value: float) -> bool:
    """ชื่อกลุ่มตามเล่ม (ไม่สนใจช่องว่าง/ขึ้นบรรทัด) ตามด้วยตัวเลข + 'หน่วยกิต' ภายใน 160 ตัวอักษร."""
    squash = lambda s: re.sub(r"[\s|]+", "", s)  # noqa: E731
    text, lab = squash(page_text), squash(label)
    # ชื่อบางกลุ่มซ้ำหลายที่ (เช่น กลุ่มวิชาพื้นฐาน) ตรวจทุกตำแหน่งที่พบ
    for m in re.finditer(re.escape(lab), text):
        window = text[m.end(): m.end() + 160]
        if re.search(rf"(?<!\d){re.escape(_num(value))}(?:\*)?หน่วยกิต", window):
            return True
    return False


def populate(db_path: Path | str) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    inserted = rejected = missing = 0
    rejects: list[str] = []
    for (program, year), rows in STRUCTURE.items():
        v = conn.execute(
            "SELECT version_id FROM curriculum_version WHERE program=? AND curriculum_year=?", (program, year)
        ).fetchone()
        if not v:
            missing += len(rows)
            continue
        version_id = v[0]
        doc = conn.execute(
            "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (version_id,)
        ).fetchone()
        for attr, label, value, page, note in rows:
            text_row = conn.execute(
                "SELECT page_text FROM page WHERE document_id=? AND page_number=?", (doc[0], page)
            ).fetchone()
            prov = conn.execute(
                "SELECT provenance_id FROM provenance WHERE document_id=? AND page_number=? ORDER BY provenance_id LIMIT 1",
                (doc[0], page),
            ).fetchone()
            if not text_row or not prov or not verify_seed(text_row[0], label, value):
                rejected += 1
                rejects.append(f"{program} {year} หน้า {page}: {label} = {_num(value)}")
                continue
            value_text = label + (f" | {note}" if note else "")
            conn.execute(
                "INSERT OR REPLACE INTO rule (version_id, rule_kind, attribute, comparator, value_numeric, value_text, provenance_id) "
                "VALUES (?, 'graduation', ?, '=', ?, ?, ?)",
                (version_id, attr, value, value_text, prov[0]),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return {"inserted": inserted, "rejected": rejected, "missing_version": missing, "rejects": rejects}  # type: ignore[dict-item]


def main() -> None:
    db = Path(__file__).resolve().parent.parent.parent / "artifacts" / "katrag.sqlite3"
    r = populate(db)
    print(f"structure rules inserted: {r['inserted']}, rejected: {r['rejected']}, missing version: {r['missing_version']}")
    for line in r["rejects"]:  # type: ignore[union-attr]
        print("  REJECT", line)


if __name__ == "__main__":
    main()
