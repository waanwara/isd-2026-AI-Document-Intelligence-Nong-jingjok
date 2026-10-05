"""Populate ตาราง `rule` (เกณฑ์สำเร็จการศึกษา/เกียรตินิยม) จาก provenance จริงในเล่ม.

ตอนแรกมีแค่ 2 rows (IT graduation, AIT graduation) ด้วยเหตุผลด้านล่าง ภายหลังพบว่า
DSBA/BIT มีวลี "จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร" พร้อมตัวเลขในเล่มจริง จึงเพิ่ม
หน่วยกิตรวมของทุกหลักสูตรปริญญาตรี รวมฉบับเก่า (ดู SEEDS) — เกณฑ์อื่นยังเหมือนเดิม
--------------------------------------------------------------
`rules_ground_truth.json` (จากอาจารย์) มีทั้ง 4 หลักสูตร แต่เล่ม มคอ.2 ที่ ingest
เข้าระบบจริงมีตัวเลขกฎอยู่ในเนื้อหา *ไม่ครบทุกหลักสูตรและไม่ครบทุก category*:

- DSBA / BIT: ค้นทั้งฐานไม่พบ chunk ที่มีคำว่า "สำเร็จการศึกษาตามหลักสูตร" เลย
  แม้แต่ตัวเดียว (ไม่ใช่แค่ถูกสารบัญบัง) และคำว่า "เกียรตินิยม" ที่เจอทั้งหมด
  เป็นวุฒิการศึกษาของอาจารย์ ("ปริญญาตรี...เกียรตินิยม") ไม่ใช่กฎของหลักสูตร
- IT / AIT: พบ "จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร 129/120 หน่วยกิต" ตรงตาม GT
  ทั้งสองทาง (เล่มมีตัวเลข + GT ยืนยันตัวเลขเดียวกัน) — เก็บทั้งคู่
- AIT มีตัวเลขเกียรตินิยมจริงในเล่ม (หัวข้อ 4.9.1/4.9.2 "ไม่ต่ำกว่า 3.55"
  อันดับ 1 / "3.50" อันดับ 2) แต่ `rules_ground_truth.json` ของ AIT ระบุ
  category เกียรตินิยมเป็น present=true, values=[] (อาจารย์ยังไม่กรอกตัวเลข)
  จึงไม่มีการตรวจทานไขว้ระหว่างเล่มกับ GT — **ไม่เก็บ** เพื่อกันข้อมูลที่ไม่มี
  ใครยืนยันซ้ำ ต่างจาก graduation ที่ทั้งสองแหล่งตรงกัน
- IT ไม่มีตัวเลขเกียรตินิยมในเล่มเลย (มีแต่ referrer ไปข้อบังคับสถาบัน)
- เกณฑ์ GPA ขั้นต่ำ (2.00) และเกณฑ์ลงทะเบียน (9/22/27) ไม่มีตัวเลขในเล่มเลย
  ทั้ง 4 หลักสูตร — เล่มเขียนแค่ "เป็นไปตามข้อบังคับสถาบันฯ" ลอย ๆ

`rule.provenance_id` เป็น NOT NULL (บังคับต้องมีหลักฐานจริงในเล่ม) จึงใส่เฉพาะ
2 rows ที่ยืนยันแล้วว่า provenance ชี้ไปยัง chunk ที่มีตัวเลขนั้นปรากฏจริง
*และ* ตรงกับ GT อาจารย์ — ไม่ยัด GT เข้าไปตรง ๆ (จะกลายเป็น circular — วัดตัวเอง
ด้วยข้อมูลที่มาจาก GT) และไม่ใส่ข้อมูลที่มีแหล่งยืนยันแหล่งเดียว

เกณฑ์การลงทะเบียน (9/22/27 หน่วยกิต) ไม่ทำในรอบนี้เพราะ schema `rule_kind`
CHECK จำกัดแค่ ('graduation','honors','dismissal','probation','grading')
ไม่มี 'registration' — ยืนยันแล้วว่า CHECK constraint enforce จริงใน SQLite
การเพิ่ม enum ใหม่เข้า schema ที่ออกแบบไว้แล้วเป็นความเสี่ยงที่ไม่จำเป็นสำหรับ
ขอบเขตงานนี้ (เอกสาร design.md ระบุเจตนาของตารางนี้ไว้ชัดว่าเพื่อ
"เกณฑ์สำเร็จการศึกษา / เกียรตินิยม / พ้นสภาพ" เท่านั้น)

Usage:
    python -m katrag.ingest.populate_rules
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuleSeed:
    program: str
    rule_kind: str          # ต้องอยู่ใน CHECK ของ schema
    attribute: str
    comparator: str
    value_numeric: float
    # เงื่อนไขค้นหา chunk ต้นฉบับที่มีตัวเลขนี้ปรากฏจริง — แยกเป็นหลาย keyword ที่
    # ต้องเจอ *ทั้งหมด* ใน chunk เดียวกัน (AND) เพราะข้อความจริงมี \n / เว้นวรรค
    # หลายจุดคั่นระหว่างวลีกับตัวเลข ทำให้ LIKE '%A%B%' ตัวเดียวไม่ match ข้าม \n
    provenance_keywords: tuple[str, ...]
    # ปีหลักสูตรที่ต้องการ (None = เวอร์ชัน current ที่มีวิชามากสุด)
    # ใช้กับฉบับเก่า เพื่อให้เทียบหน่วยกิตรวมข้ามเวอร์ชันได้
    year: int | None = None


# ยืนยันด้วยการอ่าน chunk จริงแล้วว่าตัวเลขปรากฏในเนื้อหา ไม่ใช่แค่ GT ลอย ๆ
SEEDS: tuple[RuleSeed, ...] = (
    RuleSeed(
        program="IT", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=129.0,
        provenance_keywords=("จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร", "129"),
    ),
    RuleSeed(
        program="AIT", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=120.0,
        provenance_keywords=("จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร", "120"),
    ),
    # หน่วยกิตรวมตลอดหลักสูตรของเวอร์ชันอื่น (เพิ่ม ต.ค. 2569) — ทุกค่าอ่านจากเล่ม
    # (หน้าโครงสร้างหลักสูตร) และ provenance ต้องหา chunk ที่มีวลี + ตัวเลขนั้นจริง
    # ฉบับปัจจุบันของ DSBA (132) และ BIT (126) ตรงกับ rules_ground_truth.json ด้วย
    # ฉบับเก่า (IT 2560 = 130, DSBA 2560 = 126, BIT 2560 = 126) ไม่มี GT ยืนยัน
    # มีแต่หลักฐานในเล่ม (DSBA/BIT 2560 หน้า 17, IT 2560 หน้า 18)
    RuleSeed(
        program="DSBA", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=132.0,
        provenance_keywords=("จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร", "132"),
    ),
    RuleSeed(
        program="BIT", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=126.0,
        provenance_keywords=("จำนวนหน่วยกิตที่เรียนตลอดหลักสูตร", "126"),
    ),
    RuleSeed(
        program="IT", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=130.0,
        provenance_keywords=("หน่วยกิตรวมตลอดหลักสูตร", "130"), year=2560,
    ),
    RuleSeed(
        program="DSBA", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=126.0,
        provenance_keywords=("หน่วยกิตรวมตลอดหลักสูตร", "126"), year=2560,
    ),
    RuleSeed(
        program="BIT", rule_kind="graduation", attribute="min_total_credits",
        comparator=">=", value_numeric=126.0,
        provenance_keywords=("หน่วยกิตรวมตลอดหลักสูตร", "126"), year=2560,
    ),
    # หมายเหตุ: ไม่เก็บ honors ของ AIT ทั้งที่เล่มมีตัวเลขจริง (3.55 อันดับ 1,
    # 3.50 อันดับ 2 ที่หัวข้อ 4.9.1/4.9.2) เพราะ rules_ground_truth.json ของ AIT
    # ระบุ category เกียรตินิยม เป็น present=true แต่ values=[] (ไม่มีตัวเลข)
    # ตัวเลขที่เล่มมีจึงไม่มี GT อื่นมายืนยันไขว้ ใส่เข้าไปเสี่ยงเป็นข้อมูลที่ไม่มี
    # การตรวจทานสองทาง — ต่างจาก IT/AIT graduation ที่ทั้งเล่มและ GT ตรงกัน
)


def _resolve_current_version(conn: sqlite3.Connection, program: str) -> int | None:
    """เลือก version 'current' ที่มีจำนวนวิชามากสุด — เดียวกับ build_gold_set.py.

    IT มี 3 แถวที่ edition_status='current' พร้อมกัน (v7/2565=315 วิชา,
    v10/2566=27, v13/2568=75) ซึ่งเป็นข้อจำกัดที่รู้ตัวอยู่แล้วของข้อมูล
    (บันทึกไว้ก่อนหน้านี้) เรียงตามปีล่าสุดอย่างเดียวจะได้ v13 ที่มีแค่ 75 วิชา
    และไม่มี chunk ที่มีตัวเลขเกณฑ์จบ ต้องใช้ตรรกะเดียวกับส่วนอื่นของระบบเพื่อ
    ไม่ให้ query คนละที่เห็นข้อมูลของคนละเวอร์ชัน
    """
    row = conn.execute(
        "SELECT cv.version_id, COUNT(c.course_id) n "
        "FROM curriculum_version cv "
        "LEFT JOIN course c ON c.version_id = cv.version_id "
        "WHERE cv.program=? AND cv.edition_status='current' "
        "GROUP BY cv.version_id ORDER BY n DESC, cv.curriculum_year DESC LIMIT 1",
        (program,),
    ).fetchone()
    return row[0] if row else None


def _find_provenance(
    conn: sqlite3.Connection, version_id: int, keywords: tuple[str, ...]
) -> int | None:
    """หา provenance_id ของ chunk แรกที่มี *ทุก* keyword ปรากฏจริง ไม่ใช่ boilerplate.

    ใช้ AND ของหลาย LIKE แยกกัน (ไม่ใช่ LIKE '%A%B%' ตัวเดียว) เพราะข้อความจริง
    มี \\n และเว้นวรรคหลายจุดคั่นระหว่างวลีกับตัวเลข ซึ่ง SQLite LIKE ไม่ข้ามให้
    """
    clauses = " AND ".join("text LIKE ?" for _ in keywords)
    params = [f"%{kw}%" for kw in keywords]
    row = conn.execute(
        f"SELECT provenance_id FROM chunk "
        f"WHERE version_id=? AND {clauses} AND COALESCE(is_boilerplate, 0) = 0 "
        f"ORDER BY page_number LIMIT 1",
        (version_id, *params),
    ).fetchone()
    return row[0] if row else None


def populate(db_path: Path | str) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    inserted = 0
    skipped_no_version = 0
    skipped_no_provenance = 0

    for seed in SEEDS:
        if seed.year is not None:
            row = conn.execute(
                "SELECT version_id FROM curriculum_version WHERE program=? AND curriculum_year=?",
                (seed.program, seed.year),
            ).fetchone()
            version_id = row[0] if row else None
        else:
            version_id = _resolve_current_version(conn, seed.program)
        if version_id is None:
            skipped_no_version += 1
            continue

        provenance_id = _find_provenance(conn, version_id, seed.provenance_keywords)
        if provenance_id is None:
            skipped_no_provenance += 1
            continue

        conn.execute(
            "INSERT OR REPLACE INTO rule "
            "(version_id, rule_kind, attribute, comparator, value_numeric, provenance_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, seed.rule_kind, seed.attribute, seed.comparator,
             seed.value_numeric, provenance_id),
        )
        inserted += 1

    conn.commit()
    conn.close()
    # หน่วยกิตรายหมวด/กลุ่มวิชา (credits.*) — อ่านจากหน้าโครงสร้างหลักสูตร ตรวจเทียบหน้าก่อนบันทึก
    from katrag.ingest.populate_structure_rules import populate as populate_structure

    populate_structure(db_path)
    conn = sqlite3.connect(str(db_path))
    total = conn.execute("SELECT COUNT(*) FROM rule").fetchone()[0]
    conn.close()
    return {
        "inserted": inserted,
        "skipped_no_version": skipped_no_version,
        "skipped_no_provenance": skipped_no_provenance,
        "total_in_db": total,
    }


def main() -> None:
    db = Path(__file__).resolve().parent.parent.parent / "artifacts" / "katrag.sqlite3"
    print(f"Populating rules: {db}")
    result = populate(db)
    print(f"Done! Inserted: {result['inserted']}, "
          f"skipped (no version): {result['skipped_no_version']}, "
          f"skipped (no provenance): {result['skipped_no_provenance']}, "
          f"total in DB: {result['total_in_db']}")


if __name__ == "__main__":
    main()
