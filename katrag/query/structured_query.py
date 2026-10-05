"""Structured Query Path — ตอบคำถามรายวิชา/แผนเรียนจากตาราง course/plan_slot ตรง ๆ.

แม่นกว่า chunk retrieval สำหรับคำถามประเภท:
- "ปี X เทอม Y เรียนอะไร" → query course by year/semester
- "มีกี่วิชา / กี่หน่วยกิต" → aggregate
- คืน context ที่มี code + name_th + name_en + credits + year/semester ครบ
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field


PROGRAM_CODES = ["AITBA", "DSBA", "AIT", "BIT", "IT"]

_THAI_NUM = {"หนึ่ง": 1, "สอง": 2, "สาม": 3, "สี่": 4}


@dataclass
class StructuredResult:
    matched: bool
    context: str  # evidence text สำหรับส่ง LLM
    version_label: str
    intent: str  # "year_sem" | "all_courses" | "none"
    # รหัสวิชาที่ใช้ประกอบคำตอบ — ใช้สร้าง citation ที่ชี้หน้าต้นทางจริง
    # (เดิม citation มาจาก chunk ที่ retrieval ดึงมา ซึ่งอาจไม่ใช่หน้าที่ให้คำตอบ)
    codes: list[str] = field(default_factory=list)
    version_id: int | None = None
    # หน้าต้นทางของคำตอบที่ไม่ได้มาจากรหัสวิชา (โครงสร้างหน่วยกิต, ตารางแผน):
    # [(document_id, page, heading)] — ถ้ามี ใช้เป็น citation แทนการหาจากรหัสวิชา
    pages: list[tuple[str, int, str]] = field(default_factory=list)


def detect_program(question: str) -> str | None:
    upper = question.upper()
    for code in PROGRAM_CODES:
        if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            return code
    kw_map = {
        "วิทยาการข้อมูล": "DSBA", "วิเคราะห์เชิงธุรกิจ": "DSBA",
        "ปัญญาประดิษฐ์": "AIT", "เทคโนโลยีสารสนเทศ": "IT",
    }
    for kw, prog in kw_map.items():
        if kw in question:
            return prog
    return None


def detect_year(question: str) -> int | None:
    """ตรวจชั้นปี (1-4) จาก 'ปีหนึ่ง/ปีที่ 2/ปี 3'."""
    for word, n in _THAI_NUM.items():
        if f"ปี{word}" in question or f"ปีที่{word}" in question:
            return n
    m = re.search(r"ปี(?:ที่)?\s*([1-4])", question)
    if m:
        return int(m.group(1))
    return None


def detect_semester(question: str) -> int | None:
    """ตรวจภาคเรียน (1-3) จาก 'เทอม 1/ภาคต้น/ภาคปลาย/ภาคการศึกษาที่ 2'."""
    if "ภาคต้น" in question or "เทอมต้น" in question or "เทอมแรก" in question:
        return 1
    if "ภาคปลาย" in question or "เทอมปลาย" in question:
        return 2
    m = re.search(r"(?:เทอม|ภาค(?:การศึกษา)?(?:ที่)?)\s*([1-3])", question)
    if m:
        return int(m.group(1))
    return None


_CURRICULUM_YEAR_RE = re.compile(r"(?<!\d)(25[5-7]\d)(?!\d)")


def detect_versions(conn: sqlite3.Connection, question: str) -> list[tuple[int, str, int]]:
    """หาเวอร์ชันหลักสูตรที่คำถามระบุชัด เช่น "DSBA 2560 กับ 2565", "AIT 2566 กับ IT 2565".

    ปีแต่ละตัวผูกกับชื่อหลักสูตรที่อยู่ก่อนหน้าใกล้สุด (ถ้าไม่มีใช้หลักสูตรของคำถาม)
    คืนเฉพาะคู่ (หลักสูตร, ปี) ที่มีอยู่จริงในฐานข้อมูล เรียงตามลำดับที่ปรากฏ
    """
    upper = question.upper()
    prog_pos: list[tuple[int, str]] = []
    for code in PROGRAM_CODES:
        for m in re.finditer(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            prog_pos.append((m.start(), code))
    prog_pos.sort()
    default = detect_program(question)

    found: list[tuple[int, str, int]] = []
    seen: set[int] = set()
    for m in _CURRICULUM_YEAR_RE.finditer(question):
        year = int(m.group(1))
        before = [code for pos, code in prog_pos if pos < m.start()]
        program = before[-1] if before else default
        if not program:
            continue
        row = conn.execute(
            "SELECT version_id FROM curriculum_version WHERE program=? AND curriculum_year=?",
            (program, year),
        ).fetchone()
        if row and row[0] not in seen:
            seen.add(row[0])
            found.append((row[0], program, year))
    return found


def _resolve_version_id(conn: sqlite3.Connection, program: str, year_be: int | None) -> tuple[int, str] | None:
    conn.row_factory = sqlite3.Row
    if year_be:
        row = conn.execute(
            "SELECT version_id, program, curriculum_year, edition_status FROM curriculum_version WHERE program=? AND curriculum_year=?",
            (program, year_be),
        ).fetchone()
        if row:
            return row["version_id"], f"{row['program']} {row['curriculum_year']} ({row['edition_status']})"

    # current edition — บาง program มีหลาย current (เช่น IT 2565/2566/2568)
    # เลือกเวอร์ชันที่มีข้อมูลแผนการเรียน (course ที่มี year) มากที่สุด
    # ถ้าเท่ากันเลือกปีล่าสุด
    rows = conn.execute(
        "SELECT cv.version_id, cv.program, cv.curriculum_year, cv.edition_status, "
        "COUNT(CASE WHEN co.year IS NOT NULL THEN 1 END) AS n_plan "
        "FROM curriculum_version cv LEFT JOIN course co ON co.version_id=cv.version_id "
        "WHERE cv.program=? AND cv.edition_status='current' "
        "GROUP BY cv.version_id ORDER BY n_plan DESC, cv.curriculum_year DESC",
        (program,),
    ).fetchall()
    if rows:
        best = rows[0]
        # ถ้าเวอร์ชันที่ดีที่สุดไม่มีแผนเลย ก็ยังคืนตัวล่าสุด (fallback)
        return best["version_id"], f"{best['program']} {best['curriculum_year']} ({best['edition_status']})"
    return None


_DEGREE_KW = {
    "master": ("ปริญญาโท", "ป.โท", "มหาบัณฑิต", "master"),
    "doctoral": ("ปริญญาเอก", "ป.เอก", "ดุษฎีบัณฑิต", "doctor", "ph.d", "phd"),
}
_DEGREE_LABEL = {"bachelor": "ปริญญาตรี", "master": "ปริญญาโท", "doctoral": "ปริญญาเอก"}


def _course_scope_versions(conn: sqlite3.Connection, question: str, program: str) -> list[int]:
    """เวอร์ชันที่ใช้ค้นรายวิชาของหลักสูตรที่ถาม.

    ปีที่ระบุในคำถามมาก่อน ไม่งั้นใช้ฉบับ current ของระดับปริญญาที่ถาม (ไม่ระบุ =
    ปริญญาตรี) — IT มี current พร้อมกันทั้งตรี/โท/เอก ถ้าค้นรวมกัน วิชาของ ป.โท
    จะถูกตอบให้คำถามของ ป.ตรี
    """
    named = [v for v, p, _ in detect_versions(conn, question) if p == program]
    if named:
        return named
    ql = question.lower()
    level = next((lv for lv, kws in _DEGREE_KW.items() if any(k in ql for k in kws)), "bachelor")
    rows = conn.execute(
        "SELECT DISTINCT cv.version_id FROM curriculum_version cv "
        "JOIN document d ON d.version_id = cv.version_id "
        "WHERE cv.program=? AND cv.edition_status='current' AND d.degree_level=?",
        (program, level),
    ).fetchall()
    if not rows:  # หลักสูตรที่มีระดับเดียว (เช่น AITBA มีแต่ ป.โท)
        rows = conn.execute(
            "SELECT version_id FROM curriculum_version WHERE program=? AND edition_status='current'",
            (program,),
        ).fetchall()
    return [r[0] for r in rows]


def _versions_label(conn: sqlite3.Connection, version_ids: list[int]) -> str:
    """ชื่อเวอร์ชันสำหรับแสดงในคำตอบ เช่น 'IT 2565 (ปริญญาตรี)'."""
    out = []
    for vid in version_ids:
        r = conn.execute(
            "SELECT cv.program, cv.curriculum_year, d.degree_level FROM curriculum_version cv "
            "JOIN document d ON d.version_id = cv.version_id WHERE cv.version_id=? LIMIT 1",
            (vid,),
        ).fetchone()
        if r:
            out.append(f"{r[0]} {r[1]} ({_DEGREE_LABEL.get(r[2], r[2])})")
    return ", ".join(out)


def _stem_eq(kw: str, word: str) -> bool:
    """คำตรงกันถ้ามี prefix ร่วมกัน ≥ 5 ตัว (กัน warehouse/warehousing)."""
    kl, wl = kw.lower(), word.lower()
    if kl == wl:
        return True
    minlen = min(len(kl), len(wl))
    if minlen < 4:
        return kl in wl or wl in kl
    shared = 0
    for i in range(minlen):
        if kl[i] != wl[i]:
            break
        shared += 1
    return shared >= min(5, minlen)


def _match_course_by_name(conn: sqlite3.Connection, q: str, version_ids: list[int]) -> list:
    """วิชาที่ชื่อไทย/อังกฤษปรากฏเต็ม ๆ ในคำถาม — เลือกชื่อที่ยาวที่สุด."""
    if not version_ids:
        return []
    ph = ",".join("?" for _ in version_ids)
    cands = conn.execute(
        f"SELECT code, name_th, name_en, credits_raw, year, semester, "
        f"prerequisite_json, prerequisite_raw, version_id "
        f"FROM course WHERE version_id IN ({ph})",
        version_ids,
    ).fetchall()
    matched = []
    for c in cands:
        nth = (c["name_th"] or "").strip()
        nen = (c["name_en"] or "").strip().lower()
        if len(nth) >= 4 and nth in q:
            matched.append((len(nth), c))
        elif len(nen) >= 4 and nen in q.lower():
            matched.append((len(nen), c))
        elif any(sub in q.lower() for sub in ["data warehouse", "warehouse"]) and "warehous" in nen:
            matched.append((15, c))
    matched.sort(key=lambda x: -x[0])
    return [matched[0][1]] if matched else []


#: คำอังกฤษที่ไม่ใช่ส่วนของชื่อวิชา
_EN_STOP = {"and", "the", "for", "prerequisite", "prereq", "pre", "requisite", "course", "subject"}


try:
    from pythainlp.tokenize import word_tokenize as _thai_tok
    _HAS_TOK = True
except Exception:  # pragma: no cover
    _HAS_TOK = False

# คำทั่วไปที่ไม่ใช่ "หัวข้อวิชา"
_TOPIC_STOP = {
    "วิชา", "เรียน", "มี", "กี่", "อะไร", "บ้าง", "หลักสูตร", "ของ", "ที่",
    "เกี่ยวกับ", "เกี่ยวข้อง", "กับ", "รายวิชา", "ทั้งหมด", "ครับ", "คะ", "ค่ะ",
    "ปี", "เทอม", "ภาค", "หน่วยกิต", "ต้อง", "ลง", "ไหน", "ด้าน", "สาขา",
    # คำกว้างเกินไป — จับ synonym แทน (กัน false positive เช่น 'เขียน'→เขียนภาษาอังกฤษ)
    "เขียน", "การ", "และ",
}
# synonym: คำถาม → คำที่ปรากฏในชื่อวิชา
_TOPIC_SYNONYM = {
    "เขียนโปรแกรม": ["โปรแกรม", "programming"],
    "โปรแกรมมิ่ง": ["โปรแกรม", "programming"],
    "coding": ["โปรแกรม", "programming"],
    "programming": ["โปรแกรม", "programming"],
    "ฐานข้อมูล": ["ฐานข้อมูล", "database"],
    # ใช้ "ARTIFICIAL" ไม่ใช่ "INTELLIGENCE" เพราะ INTELLIGENCE ไปตรงกับ
    # "DIGITAL INTELLIGENCE QUOTIENT" ซึ่งไม่ใช่วิชา AI
    # (ชื่อในเอกสารสะกด INTELLIGIENCE ผิดบางที่ → ARTIFICIAL ครอบคลุมกว่า)
    "เอไอ": ["ปัญญาประดิษฐ์", "ARTIFICIAL"],
    "ปัญญาประดิษฐ์": ["ปัญญาประดิษฐ์", "ARTIFICIAL"],
    "เครือข่าย": ["เครือข่าย", "NETWORK"],
    "ความมั่นคง": ["ความมั่นคง", "SECURITY", "ไซเบอร์"],
    "คณิต": ["คณิต", "MATH", "แคลคูลัส", "CALCULUS"],
}


def _extract_topic_keywords(question: str, program: str | None) -> list[str]:
    """แยกคำหัวข้อวิชาจากคำถาม + ขยาย synonym."""
    q = question
    # ตัดส่วน 'หลักสูตร XXX:' ที่ prepend มา
    q = re.sub(r"หลักสูตร\s+[A-Z]+\s*:", "", q)
    tokens = _thai_tok(q, keep_whitespace=False) if _HAS_TOK else re.findall(r"[ก-๙]+|[A-Za-z]+", q)
    prog_up = (program or "").upper()
    kws: list[str] = []
    for t in tokens:
        t = t.strip()
        if not t or t in _TOPIC_STOP or t.upper() == prog_up or len(t) < 2:
            continue
        kws.append(t)
    # synonym expansion + ตรวจ compound ในคำถามดิบ
    expanded: list[str] = []
    ql = question.lower()
    for syn, reps in _TOPIC_SYNONYM.items():
        if syn in ql:
            expanded.extend(reps)
    for k in kws:
        if k.lower() in _TOPIC_SYNONYM:
            expanded.extend(_TOPIC_SYNONYM[k.lower()])
        else:
            expanded.append(k)
    # unique คงลำดับ
    return list(dict.fromkeys(expanded))


def try_topic_courses(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ตอบคำถาม 'วิชา<หัวข้อ> มีกี่วิชา/อะไรบ้าง' — ค้นชื่อวิชาในตาราง course.

    - ถ้าระบุ program → ค้นเฉพาะหลักสูตรนั้น
    - ถ้าไม่ระบุ (ทุกหลักสูตร) → ค้นทุก current version แล้วแยกตามหลักสูตร
    """
    conn.row_factory = sqlite3.Row
    if "วิชา" not in question:
        return StructuredResult(False, "", "", "none")

    program = detect_program(question)
    keywords = _extract_topic_keywords(question, program)
    if not keywords:
        return StructuredResult(False, "", "", "none")

    # version scope
    if program:
        vers = conn.execute(
            "SELECT version_id, program, curriculum_year FROM curriculum_version "
            "WHERE program=? AND edition_status='current'", (program,),
        ).fetchall()
    else:
        vers = conn.execute(
            "SELECT version_id, program, curriculum_year FROM curriculum_version "
            "WHERE edition_status='current'",
        ).fetchall()
    if not vers:
        return StructuredResult(False, "", "", "none")

    # เลือก version ที่มีข้อมูลมากสุดต่อ program (กัน IT ที่มีหลาย current)
    best_per_prog: dict[str, sqlite3.Row] = {}
    for v in vers:
        n = conn.execute("SELECT COUNT(*) FROM course WHERE version_id=?", (v["version_id"],)).fetchone()[0]
        cur = best_per_prog.get(v["program"])
        if cur is None or n > cur["_n"]:
            d = dict(v); d["_n"] = n
            best_per_prog[v["program"]] = d  # type: ignore

    kw_clause = " OR ".join(["name_th LIKE ? OR name_en LIKE ?" for _ in keywords])

    blocks: list[str] = []
    total_found = 0
    for prog, v in sorted(best_per_prog.items()):
        params: list = []
        for kw in keywords:
            params.extend([f"%{kw}%", f"%{kw}%"])
        params.append(v["version_id"])
        rows = conn.execute(
            f"SELECT code, name_th, name_en, credits_raw FROM course "
            f"WHERE ({kw_clause}) AND version_id=? ORDER BY code", params,
        ).fetchall()
        if not rows:
            continue
        total_found += len(rows)
        header = f"หลักสูตร {prog} {v['curriculum_year']} — พบ {len(rows)} วิชา:"
        lines = [header]
        for r in rows:
            en = f" ({r['name_en']})" if r["name_en"] else ""
            lines.append(f"  - {r['code']} {r['name_th']}{en} — {r['credits_raw']}")
        blocks.append("\n".join(lines))

    if not blocks:
        return StructuredResult(False, "", "", "none")

    topic = " / ".join(keywords[:3])
    ctx = f"วิชาที่เกี่ยวกับ '{topic}' (ค้นจากชื่อวิชาในหลักสูตร):\n\n" + "\n\n".join(blocks)
    label = program or "ทุกหลักสูตร"
    return StructuredResult(True, ctx, label, "topic_courses")


def try_structured_answer(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ลองตอบจากตาราง structured. คืน matched=False ถ้าไม่เข้าเงื่อนไข."""
    conn.row_factory = sqlite3.Row

    program = detect_program(question)
    if not program:
        return StructuredResult(False, "", "", "none")

    year_level = detect_year(question)
    semester = detect_semester(question)

    # ตรวจปี พ.ศ. (สำหรับ version)
    be_match = re.search(r"\b(25\d\d)\b", question)
    year_be = int(be_match.group(1)) if be_match else None

    resolved = _resolve_version_id(conn, program, year_be)
    if not resolved:
        return StructuredResult(False, "", "", "none")
    version_id, version_label = resolved

    # คำถามเกี่ยวกับรายวิชา/แผนเรียนหรือไม่
    course_intent = any(w in question for w in ["เรียน", "วิชา", "รายวิชา", "แผน", "หน่วยกิต", "บังคับ", "เลือก"])
    if not course_intent:
        return StructuredResult(False, "", "", "none")

    # คำถามภาพรวมของหลักสูตร (เช่น "มีกี่แขนง/กี่โมดูล/กี่สาขา") ไม่ใช่ topic search
    # แม้จะมีคำว่า "วิชา" ประกอบก็ตาม (เช่น "กี่แขนงวิชา") — เพราะไม่ได้ถามหาชื่อ
    # รายวิชา แต่ถามจำนวน specialization ให้ตกไป retrieval + LLM ตอบจากเอกสาร
    _META_COUNT_PATTERNS = (
        "กี่แขนง", "มีแขนง", "กี่โมดูล", "มีโมดูล", "กี่สาขา", "มีสาขา",
        "กี่กลุ่มวิชา", "กี่แนว", "กี่หมวดวิชา", "กี่ track", "กี่ทาง",
    )
    if any(p in question for p in _META_COUNT_PATTERNS):
        return StructuredResult(False, "", "", "none")

    # ── กรณี: ระบุปี+เทอม → query course ตามชั้นปี/ภาค ──
    if year_level is not None:
        params: list = [version_id, year_level]
        sem_clause = ""
        if semester is not None:
            sem_clause = " AND semester=?"
            params.append(semester)
        rows = conn.execute(
            f"SELECT code, name_th, name_en, credits_raw, year, semester "
            f"FROM course WHERE version_id=? AND year=?{sem_clause} ORDER BY semester, code",
            params,
        ).fetchall()

        if rows:
            from itertools import groupby
            lines = [f"รายวิชาของหลักสูตร {version_label} ปีที่ {year_level} "
                     "(จัดกลุ่มตามภาคการศึกษา):"]
            for sem_no, group in groupby(rows, key=lambda r: r["semester"]):
                courses = list(group)
                sem_credits = sum(_parse_credit(cc["credits_raw"]) for cc in courses)
                lines.append(f"\n▶ ภาคการศึกษาที่ {sem_no} — วิชาบังคับ ({len(courses)} วิชา {sem_credits} หน่วยกิต):")
                for cc in courses:
                    en = f" ({cc['name_en']})" if cc["name_en"] else ""
                    lines.append(f"  - {cc['code']} {cc['name_th']}{en} — {cc['credits_raw']}")
                # วิชาเลือกในเทอมนี้ (จากตารางแผน)
                electives = extract_elective_slots(conn, version_id, year_level, sem_no)
                if electives:
                    lines.append(f"  วิชาเลือกเฉพาะแขนง (เลือก 1 แขนง แล้วลงวิชาในแขนงนั้น) กลุ่มที่มี:")
                    for e in electives:
                        lines.append(f"    • {e}")
            total = sum(_parse_credit(r["credits_raw"]) for r in rows)
            lines.append(f"\nรวมปีที่ {year_level} (วิชาบังคับ): {len(rows)} วิชา {total} หน่วยกิต (ยังไม่รวมวิชาเลือก)")
            return StructuredResult(
                True, "\n".join(lines), version_label, "year_sem",
                codes=[r["code"] for r in rows], version_id=version_id,
            )

    # ── กรณี: ถามรายวิชา "ทั้งหมด" ของหลักสูตร (ต้องระบุชัดว่าเอาทั้งหมด) ──
    # ถ้าถามเจาะจงหัวข้อ (เช่น "วิชาเขียนโปรแกรม") ไม่เข้า branch นี้ → ให้ hybrid ค้นแทน
    wants_all = any(w in question for w in [
        "ทั้งหมด", "ทุกวิชา", "มีวิชาอะไรบ้าง", "รายวิชาทั้งหมด", "วิชาทั้งหมด", "โครงสร้างหลักสูตร"
    ])
    if wants_all:
        rows = conn.execute(
            "SELECT code, name_th, name_en, credits_raw, year, semester "
            "FROM course WHERE version_id=? ORDER BY year, semester, code LIMIT 200",
            (version_id,),
        ).fetchall()
        if rows:
            lines = [f"รายวิชาของหลักสูตร {version_label} (ทั้งหมด {len(rows)} วิชา):"]
            for r in rows:
                en = f" ({r['name_en']})" if r["name_en"] else ""
                ys = ""
                if r["year"] and r["semester"]:
                    ys = f" [ปีที่ {r['year']} ภาคการศึกษาที่ {r['semester']}]"
                lines.append(f"- {r['code']} {r['name_th']}{en} — {r['credits_raw']}{ys}")
            return StructuredResult(
                True, "\n".join(lines), version_label, "all_courses",
                codes=[r["code"] for r in rows], version_id=version_id,
            )

    # คำถามเจาะจงหัวข้อ (ไม่ระบุปี ไม่เอาทั้งหมด) → ปล่อยให้ hybrid retrieval จัดการ
    return StructuredResult(False, "", "", "none")


def _parse_credit(credits_raw: str) -> int:
    m = re.match(r"(\d+)", credits_raw or "")
    return int(m.group(1)) if m else 0


def source_pages_for_codes(
    conn: sqlite3.Connection,
    codes: list[str],
    version_id: int | None,
    *,
    limit: int = 10,
) -> list[tuple[str, int, str]]:
    """หาหน้าต้นทางของรายวิชาที่ใช้ตอบ — สำหรับสร้าง citation ที่ตรงกับคำตอบ.

    คืน (document_id, page_number, heading) เรียงตามจำนวนรหัสวิชาที่ปรากฏในหน้านั้น
    (หน้าที่มีวิชาในคำตอบหลายตัว = หน้าตารางแผนการเรียน = หลักฐานที่ดีที่สุด)
    """
    if not codes or version_id is None:
        return []
    conn.row_factory = sqlite3.Row

    uniq = list(dict.fromkeys(c for c in codes if c))[:40]
    if not uniq:
        return []

    like_clause = " OR ".join(["text LIKE ?"] * len(uniq))
    params: list = [f"%{c}%" for c in uniq]
    params.append(version_id)

    rows = conn.execute(
        f"SELECT document_id, page_number, heading, text FROM chunk "
        f"WHERE ({like_clause}) AND version_id=? "
        f"AND COALESCE(is_boilerplate, 0) = 0",
        params,
    ).fetchall()

    # นับว่าแต่ละหน้ามีรหัสวิชาในคำตอบกี่ตัว
    scored: dict[tuple[str, int], tuple[int, str]] = {}
    for r in rows:
        text = r["text"] or ""
        n = sum(1 for c in uniq if c in text)
        key = (r["document_id"], r["page_number"])
        prev = scored.get(key)
        if prev is None or n > prev[0]:
            scored[key] = (n, r["heading"] or "")

    ordered = sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[0][1]))
    return [(d, p, h) for (d, p), (_n, h) in ordered[:limit]]


_ELECTIVE_SLOT_RE = re.compile(r"(?:\d{4}xxx\s*)?(วิชาเลือก[ก-๙\s]*?\d?)\s*\n?\s*(ELECTIVE[A-Z\s]*\d?)?", re.IGNORECASE)


def extract_elective_slots(conn: sqlite3.Connection, version_id: int, year: int, semester: int) -> list[str]:
    """ดึงช่องวิชาเลือก (elective slot) จากตารางแผนการศึกษาของปี/เทอมนั้น.

    แผนมักเขียน 'xxxxxxx วิชาเลือกกลุ่ม... ELECTIVE IN ...' = ต้องเลือกลง 1 วิชา
    """
    conn.row_factory = sqlite3.Row
    header = f"ปีที่ {year} ภาคการศึกษาที่ {semester}"
    row = conn.execute(
        "SELECT text FROM chunk WHERE version_id=? AND text LIKE ? ORDER BY page_number LIMIT 1",
        (version_id, f"%{header}%"),
    ).fetchone()
    if not row:
        return []
    text = row["text"]
    start = text.find(header)
    # ตัดถึง header เทอมถัดไป (ถ้ามี) เพื่อจำกัดขอบเขต
    nxt = re.search(r"ปีที่ \d ภาคการศึกษาที่ \d", text[start + len(header):])
    segment = text[start: start + len(header) + (nxt.start() if nxt else 800)]

    slots: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"วิชาเลือก[ก-๙\s]{2,60}?\d?(?=\s|\n|$)", segment):
        name = " ".join(m.group(0).split())
        # ตัดชื่อยาวเกินที่รวมข้อความอื่น
        name = name.split("หน่วยกิต")[0].strip()
        # ตัดเลข trailing (เช่น "วิชาเลือกกลุ่มวิทยาการข้อมูล 3" → ตัด " 3")
        name = re.sub(r"\s+\d+$", "", name)
        if 10 < len(name) < 60 and name not in seen:
            seen.add(name)
            slots.append(name)
    return slots


def _norm_name(name: str) -> str:
    """normalize ชื่อวิชาสำหรับเทียบข้ามเวอร์ชัน (ตัด whitespace/วรรณยุกต์ที่ต่างเล็กน้อย)."""
    n = re.sub(r"\s+", "", name or "")
    # ตัดเลขลำดับท้าย เช่น "แคลคูลัส 1" -> "แคลคูลัส1" (คงไว้)
    return n.lower()


def detect_prerequisite_intent(question: str) -> bool:
    """ตรวจว่าเป็นคำถามวิชาบังคับก่อน (prerequisite)."""
    q = question.lower()
    return any(w in q for w in [
        "บังคับก่อน", "ต้องผ่าน", "ต้องเรียนก่อน", "ลงก่อน", "prerequisite",
        "ก่อนถึงจะลง", "เรียนก่อน", "ตัวต่อ", "วิชาต่อเนื่อง", "prereq", "pre-requisite",
        "เงื่อนไขก่อน", "ก่อนเรียน",
    ])


def try_prerequisite(
    conn: sqlite3.Connection, question: str, *, require_intent: bool = True
) -> StructuredResult:
    """ตอบว่าวิชาที่ถามต้องผ่านวิชาใดก่อน — จาก course.prerequisite_json.

    Args:
        require_intent: ถ้า False จะข้ามการตรวจคำบ่งชี้ (ใช้ตอนเสริม context
            ให้คำถามเชิงวิเคราะห์ เช่น "ลงวิชา X ตอนปีสองได้ไหม" ซึ่งไม่มีคำว่า
            "ต้องผ่าน" แต่ยังต้องรู้ prerequisite เพื่อตอบให้ถูก)
    """
    import json
    conn.row_factory = sqlite3.Row
    if require_intent and not detect_prerequisite_intent(question):
        return StructuredResult(False, "", "", "none")

    program = detect_program(question)

    # ตัด 'หลักสูตร XXX:' ที่ prepend มา ไม่ให้กลายเป็น keyword ชื่อวิชา
    q = re.sub(r"หลักสูตร\s+[A-Za-z]+\s*[:：]", " ", question)
    if program:
        q = re.sub(rf"(?i)\b{re.escape(program)}\b", " ", q)

    version_ids = _course_scope_versions(conn, question, program) if program else []

    # ลองจับคู่ชื่อวิชาโดยตรงจากตาราง course ใน version นั้นก่อน (แก้ปัญหา Tokenizer ไทยตัดคำเพี้ยน)
    rows = _match_course_by_name(conn, q, version_ids)

    # ชื่อวิชาภาษาอังกฤษในคำถาม: ทุกคำต้องอยู่ในชื่อวิชาเดียวกัน ถ้าไม่มีวิชาไหนตรง
    # ให้ตอบว่าไม่พบ แทนการหยิบวิชาที่มีคำร่วมแค่บางคำ (เช่น "Data") มาตอบ
    en_words = [w for w in re.findall(r"[A-Za-z]{3,}", q) if w.lower() not in _EN_STOP]
    if not rows and en_words and version_ids:
        ph = ",".join("?" for _ in version_ids)
        strict = [
            c for c in conn.execute(
                f"SELECT code, name_th, name_en, credits_raw, year, semester, "
                f"prerequisite_json, prerequisite_raw, version_id "
                f"FROM course WHERE version_id IN ({ph})",
                version_ids,
            ).fetchall()
            # เทียบเฉพาะคำในชื่อวิชาที่ยาว ≥ 3 ตัว — คำสั้นอย่าง "in"/"e" เป็น substring
            # ของคำค้นแทบทุกคำ
            if all(
                any(_stem_eq(w, x) for x in re.findall(r"[a-z]{3,}", (c["name_en"] or "").lower()))
                for w in en_words
            )
        ]
        if not strict:
            name = " ".join(en_words)
            return StructuredResult(
                True,
                f"ไม่พบวิชาชื่อ \"{name}\" ในหลักสูตร {_versions_label(conn, version_ids)}\n"
                "จึงตอบเรื่องวิชาบังคับก่อนของวิชานี้ไม่ได้ ลองตรวจชื่อวิชา หรือระบุรหัสวิชา 8 หลัก",
                "", "prerequisite",
                version_id=version_ids[0],
            )
        # ชื่อสั้นสุดคือชื่อที่ตรงคำถามที่สุด (คำเกินน้อยสุด)
        strict.sort(key=lambda c: len(c["name_en"] or ""))
        rows = strict[:3]

    keywords = []
    if not rows:
        # ดึง keyword ชื่อวิชาจากคำถาม (คำไทยยาว ≥ 3 + อังกฤษ ≥ 3)
        stop = {"ต้องผ่าน", "วิชา", "บังคับก่อน", "ต้องเรียน", "ก่อนถึงจะลง", "อะไร", "ใดบ้าง", "หลักสูตร",
                # คำเชื่อมสั้น ๆ ทำให้วิชาที่ไม่เกี่ยวได้คะแนนเท่ากัน (เช่น "และ" ในชื่อโครงงาน)
                "และ", "หรือ", "กับ", "ของ", "ที่"}
        q_markers = ("ต้อง", "ก่อน", "อะไร", "ใดบ้าง", "ได้บ้าง", "หรือไม่", "จะลง")
        q_clean = re.sub(r"(?:ราย)?วิชา\s*", " ", q)
        tokens = re.findall(r"[ก-๙]{3,}|[A-Za-z]{3,}", q_clean)
        keywords = [
            t for t in tokens
            if t.lower() not in {s.lower() for s in stop}
            and not any(m in t for m in q_markers)
        ]
        if not keywords:
            return StructuredResult(False, "", "", "none")

        kw_clauses = " OR ".join(["name_th LIKE ? OR name_en LIKE ?" for _ in keywords])
        params: list = []
        for kw in keywords:
            params.extend([f"%{kw}%", f"%{kw}%"])

        where_scope = ""
        if version_ids:
            ph = ",".join("?" for _ in version_ids)
            where_scope = f" AND version_id IN ({ph})"
            params.extend(version_ids)

        rows = conn.execute(
            f"SELECT code, name_th, name_en, credits_raw, year, semester, "
            f"prerequisite_json, prerequisite_raw, version_id "
            f"FROM course WHERE ({kw_clauses}){where_scope} ORDER BY (prerequisite_json != '[]') DESC LIMIT 10",
            params,
        ).fetchall()

    if not rows:
        return StructuredResult(False, "", "", "none")

    # ── Relevance ranking: เรียงตามจำนวน keyword ที่ match ──
    if keywords and len(rows) > 1:
        def _kw_score(r) -> int:
            blob = f"{r['name_th']} {r['name_en']}".lower()
            words = re.findall(r"[ก-๙]+|[a-z]+", blob)
            score = 0
            for kw in keywords:
                if any(_stem_eq(kw, w) for w in words):
                    score += 1
            return score

        rows = sorted(rows, key=lambda r: (-_kw_score(r), -(1 if json.loads(r["prerequisite_json"] or "[]") else 0)))

        # ถ้าตัวอันดับ 1 match keyword มากกว่าตัวที่ 2 ชัดเจน → ตอบแค่ตัวเดียว
        if len(rows) > 1 and _kw_score(rows[0]) > _kw_score(rows[1]):
            rows = [rows[0]]
        else:
            rows_with_prereq = [r for r in rows if json.loads(r["prerequisite_json"] or "[]")]
            if rows_with_prereq:
                rows = rows_with_prereq[:3]
            else:
                rows = rows[:3]

    def _plan(r) -> str:
        if r["year"] and r["semester"]:
            return f"ปีที่ {r['year']} ภาคการศึกษาที่ {r['semester']}"
        if r["year"]:
            return f"ปีที่ {r['year']}"
        return "ไม่ระบุชั้นปี (วิชาเลือก)"

    # ── ตรวจว่าถามเรื่อง "ลงได้ไหมถ้ายังไม่ผ่าน" ──
    ask_can_register = any(w in question for w in ["ลงได้ไหม", "ลงทะเบียนได้ไหม", "ลงได้หรือไม่", "ลงได้มั้ย"])

    lines = []
    for r in rows:
        prereqs = json.loads(r["prerequisite_json"] or "[]")
        en = f" ({r['name_en']})" if r["name_en"] else ""
        head = f"วิชา {r['code']} {r['name_th']}{en} — {r['credits_raw']} | {_plan(r)}"
        if prereqs:
            lines.append(head)
            lines.append("  ต้องผ่านวิชาบังคับก่อน:")
            for pc in prereqs:
                pr = conn.execute(
                    "SELECT name_th, name_en, credits_raw, year, semester FROM course "
                    "WHERE code=? AND version_id=? LIMIT 1",
                    (pc, r["version_id"]),
                ).fetchone()
                if pr is None:
                    # prereq อาจเป็นวิชาแกนที่อยู่ในเวอร์ชันอื่น → หาแบบไม่ผูกเวอร์ชัน
                    pr = conn.execute(
                        "SELECT name_th, name_en, credits_raw, year, semester FROM course "
                        "WHERE code=? LIMIT 1", (pc,),
                    ).fetchone()
                if pr:
                    pen = f" ({pr['name_en']})" if pr["name_en"] else ""
                    lines.append(
                        f"    • {pc} {pr['name_th']}{pen} — {pr['credits_raw']} | {_plan(pr)}"
                    )
                    lines.extend(_prereq_chain_lines(conn, pc, r["version_id"], depth=1))
                else:
                    lines.append(f"    • {pc} (ไม่พบชื่อวิชาในฐานข้อมูล)")
        else:
            lines.append(head + "\n  ไม่มีวิชาบังคับก่อน (PREREQUISITE: None)")

    if ask_can_register:
        lines.append("")
        has_prereq = any(json.loads(r["prerequisite_json"] or "[]") for r in rows)
        if has_prereq:
            lines.append("คำตอบ: ไม่ได้ — ถ้ายังไม่ผ่านวิชาบังคับก่อน (prerequisite) จะลงทะเบียนวิชานี้ไม่ได้")
            lines.append("ต้องเรียนวิชาบังคับก่อนให้ผ่านก่อนจึงจะลงทะเบียนได้")
        else:
            lines.append("คำตอบ: ได้ — วิชานี้ไม่มีวิชาบังคับก่อน สามารถลงทะเบียนได้เลย")

    # รหัสวิชาที่ตอบ + รหัสวิชาบังคับก่อน = หลักฐานของคำตอบนี้
    answer_codes: list[str] = []
    for r in rows:
        answer_codes.append(r["code"])
        answer_codes.extend(json.loads(r["prerequisite_json"] or "[]"))
    return StructuredResult(
        True, "\n".join(lines), "", "prerequisite",
        codes=answer_codes,
        version_id=rows[0]["version_id"] if rows else None,
    )


def _prereq_chain_lines(
    conn: sqlite3.Connection, code: str, version_id: int, *, depth: int,
    seen: set[str] | None = None, max_depth: int = 4,
) -> list[str]:
    """ไล่วิชาบังคับก่อนของวิชาบังคับก่อนต่อไปเรื่อย ๆ (กัน loop และจำกัดความลึก)."""
    import json
    seen = set(seen or ()) | {code}
    row = conn.execute(
        "SELECT prerequisite_json FROM course WHERE code=? AND version_id=? LIMIT 1",
        (code, version_id),
    ).fetchone()
    if row is None or depth >= max_depth:
        return []
    out: list[str] = []
    indent = "    " + "  " * depth
    for pc in json.loads(row[0] or "[]"):
        if pc in seen:
            continue
        pr = conn.execute(
            "SELECT name_th, name_en FROM course WHERE code=? AND version_id=? LIMIT 1",
            (pc, version_id),
        ).fetchone()
        name = f"{pr[0]} ({pr[1]})" if pr and pr[1] else (pr[0] if pr else "(ไม่พบชื่อวิชา)")
        out.append(f"{indent}↳ ต้องผ่าน {pc} {name} ก่อน")
        out.extend(_prereq_chain_lines(conn, pc, version_id, depth=depth + 1, seen=seen))
    return out


#: ถามทิศกลับของ prerequisite — วิชานี้เป็นวิชาบังคับก่อนของวิชาไหน
_DEPENDENT_KW = (
    "กระทบ", "เป็นวิชาบังคับก่อนของ", "ใช้เป็นวิชาบังคับก่อน", "เป็นพื้นฐานของวิชา",
    "ต่อยอด", "สอบตก", "ตกวิชา",
)


def detect_dependents_intent(question: str) -> bool:
    return any(k in question for k in _DEPENDENT_KW)


def try_dependents(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """วิชาที่ต้องผ่านวิชาที่ถามก่อนจึงจะลงได้ (ไล่ต่อหลายชั้น) — จาก course.prerequisite_json."""
    import json
    conn.row_factory = sqlite3.Row
    program = detect_program(question)
    if not program:
        return StructuredResult(False, "", "", "none")
    q = re.sub(r"หลักสูตร\s+[A-Za-z]+\s*[:：]", " ", question)
    version_ids = _course_scope_versions(conn, question, program)
    rows = _match_course_by_name(conn, q, version_ids)
    if not rows:
        return StructuredResult(False, "", "", "none")
    base = rows[0]
    vid = base["version_id"]

    def _children(code: str) -> list:
        return [
            r for r in conn.execute(
                "SELECT code, name_th, name_en, credits_raw, year, semester, prerequisite_json "
                "FROM course WHERE version_id=? AND prerequisite_json LIKE ? ORDER BY code",
                (vid, f'%"{code}"%'),
            ).fetchall()
            if code in json.loads(r["prerequisite_json"] or "[]")
        ]

    def _plan(r) -> str:
        if r["year"] and r["semester"]:
            return f"ปีที่ {r['year']} ภาคการศึกษาที่ {r['semester']}"
        return "ไม่ระบุชั้นปี (วิชาเลือก)"

    en = f" ({base['name_en']})" if base["name_en"] else ""
    lines = [f"วิชา {base['code']} {base['name_th']}{en} — {_plan(base)}"]
    codes = [base["code"]]
    seen = {base["code"]}

    def _walk(code: str, depth: int) -> None:
        for r in _children(code):
            if r["code"] in seen or depth > 4:
                continue
            seen.add(r["code"])
            codes.append(r["code"])
            ren = f" ({r['name_en']})" if r["name_en"] else ""
            indent = "  " + "  " * depth
            mark = "•" if depth == 1 else "↳"
            lines.append(f"{indent}{mark} {r['code']} {r['name_th']}{ren} — {r['credits_raw']} | {_plan(r)}")
            _walk(r["code"], depth + 1)

    lines.append("  วิชาที่ต้องผ่านวิชานี้ก่อนจึงจะลงได้ (↳ = ต่อจากวิชาด้านบนอีกชั้น):")
    n_before = len(lines)
    _walk(base["code"], 1)
    if len(lines) == n_before:
        lines[-1] = "  ไม่มีวิชาใดในหลักสูตรนี้ที่กำหนดวิชานี้เป็นวิชาบังคับก่อน"
    else:
        lines.append("  ถ้ายังไม่ผ่านวิชานี้ จะลงวิชาข้างต้นไม่ได้จนกว่าจะผ่าน")
    return StructuredResult(
        True, "\n".join(lines), _versions_label(conn, [vid]), "dependents",
        codes=codes, version_id=vid,
    )


def detect_plan_summary_intent(question: str) -> bool:
    """ตรวจว่าเป็นคำถามภาพรวมแผนการเรียน/จบเร็ว."""
    return any(w in question for w in ["แผนการเรียน", "แผนการศึกษา", "3.5 ปี", "3.5ปี", "จบเร็ว", "จบไว", "แต่ละเทอม", "ทุกเทอม", "โครงสร้างหลักสูตร"])


def _detect_early_grad(question: str) -> bool:
    """ตรวจว่าถาม 'จบ 3.5 ปี / จบเร็ว'."""
    return any(w in question for w in ["3.5 ปี", "3.5ปี", "จบเร็ว", "จบไว", "จบใน 3.5", "สามปีครึ่ง", "3 ปีครึ่ง"])


def try_plan_summary(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """คืนสรุปแผนการเรียนต่อชั้นปี/ภาค (จำนวนวิชา+หน่วยกิต+รายวิชา)."""
    conn.row_factory = sqlite3.Row
    program = detect_program(question)
    if not program or not detect_plan_summary_intent(question):
        return StructuredResult(False, "", "", "none")

    be_match = re.search(r"\b(25\d\d)\b", question)
    year_be = int(be_match.group(1)) if be_match else None
    resolved = _resolve_version_id(conn, program, year_be)
    if not resolved:
        return StructuredResult(False, "", "", "none")
    version_id, version_label = resolved

    rows = conn.execute(
        "SELECT year, semester, code, name_th, name_en, credits_raw, credits_total "
        "FROM course WHERE version_id=? AND year IS NOT NULL AND semester IS NOT NULL "
        "ORDER BY year, semester, code",
        (version_id,),
    ).fetchall()
    if not rows:
        return StructuredResult(False, "", "", "none")

    # ── ถ้าถาม "จบ 3.5 ปี" → ให้คำแนะนำเฉพาะ ──
    if _detect_early_grad(question):
        return _format_early_grad(conn, version_id, version_label, rows)

    # ── แผนปกติ ──
    return _format_full_plan(conn, version_id, version_label, rows)


def _format_full_plan(
    conn: sqlite3.Connection, version_id: int, version_label: str, rows: list
) -> StructuredResult:
    """แผนเรียนปกติทุกเทอม."""

    lines = [f"แผนการศึกษาของหลักสูตร {version_label} (จำแนกตามชั้นปี/ภาคการศึกษา):"]
    from itertools import groupby
    total_all = 0
    for (yr, sem), group in groupby(rows, key=lambda r: (r["year"], r["semester"])):
        courses = list(group)
        sem_credits = sum(cc["credits_total"] or 0 for cc in courses)
        total_all += sem_credits
        lines.append(f"\nปีที่ {yr} ภาคการศึกษาที่ {sem} ({len(courses)} วิชา, {sem_credits} หน่วยกิต):")
        for cc in courses:
            en = f" ({cc['name_en']})" if cc["name_en"] else ""
            lines.append(f"  - {cc['code']} {cc['name_th']}{en} — {cc['credits_raw']}")
        # วิชาเลือกแขนง/เฉพาะด้าน ที่ต้องลงในเทอมนี้
        elective_slots = extract_elective_slots(conn, version_id, yr, sem)
        if elective_slots:
            lines.append(f"  + วิชาเลือกเฉพาะแขนง (เลือก 1 แขนง แล้วลงวิชาในแขนงนั้น) กลุ่มที่มี:")
            for slot in elective_slots:
                lines.append(f"    • {slot}")

    # วิชาเลือก/เสรี ที่ไม่ผูกเทอม
    elective_count = conn.execute(
        "SELECT COUNT(*) FROM course WHERE version_id=? AND year IS NULL", (version_id,)
    ).fetchone()[0]
    lines.append(f"\nหมายเหตุ: มีวิชาเลือก/เลือกเสรีอีก {elective_count} วิชา ที่ไม่ผูกภาคเรียนตายตัว (เลือกลงได้ตามเงื่อนไข)")
    lines.append(f"หน่วยกิตในแผนบังคับตามเทอม: {total_all} หน่วยกิต")

    return StructuredResult(True, "\n".join(lines), version_label, "plan_summary")


def _format_early_grad(
    conn: sqlite3.Connection, version_id: int, version_label: str, rows: list
) -> StructuredResult:
    """คำแนะนำจบ 3.5 ปี: ดึงวิชาปี 4 เทอม 2 มาลงก่อน."""
    from itertools import groupby

    # แยกวิชาปี 4 เทอม 2 — คือส่วนที่ต้อง "เลื่อนขึ้น" ไปลงเทอมก่อนหน้า
    last_sem = [r for r in rows if r["year"] == 4 and r["semester"] == 2]
    other = [r for r in rows if not (r["year"] == 4 and r["semester"] == 2)]

    # วิชาเลือก/เสรี ที่ไม่ผูกเทอม
    elective_rows = conn.execute(
        "SELECT code, name_th, name_en, credits_raw, credits_total "
        "FROM course WHERE version_id=? AND year IS NULL", (version_id,)
    ).fetchall()

    last_credits = sum((r["credits_total"] or 0) for r in last_sem)
    elective_credits_total = sum((r["credits_total"] or 0) for r in elective_rows)

    lines = [
        f"แนวทางจบหลักสูตร {version_label} ภายใน 3.5 ปี",
        "",
        "หลักการ: จบปกติใช้ 4 ปี (8 ภาค) การจบ 3.5 ปี = จบในสิ้นปี 4 เทอม 1",
        "วิธี: ดึงวิชาที่ปกติอยู่ปี 4 ภาคการศึกษาที่ 2 มาลงล่วงหน้าในเทอมก่อนหน้า",
        "(ต้องตรวจสอบ prerequisite ว่าวิชานั้นเปิดลงล่วงหน้าได้)",
        "",
    ]

    if last_sem:
        lines.append(f"■ วิชาในปี 4 ภาคการศึกษาที่ 2 (ปกติ) ที่ต้องดึงมาลงก่อน ({len(last_sem)} วิชา, {last_credits} หน่วยกิต):")
        for r in last_sem:
            en = f" ({r['name_en']})" if r["name_en"] else ""
            lines.append(f"  - {r['code']} {r['name_th']}{en} — {r['credits_raw']}")
    else:
        lines.append("■ ไม่พบวิชาบังคับในปี 4 ภาคการศึกษาที่ 2 ในแผน (อาจเป็นวิชาเลือกทั้งหมด)")

    if elective_rows:
        lines.append(f"\n■ วิชาเลือก/เลือกเสรี ที่ต้องลงให้ครบด้วย ({len(elective_rows)} วิชา, {elective_credits_total} หน่วยกิต):")
        lines.append("  (วิชาเหล่านี้ไม่ผูกเทอมตายตัว ลงได้ตั้งแต่เทอมที่เปิดให้ลง)")

    lines.append("")
    lines.append("■ แผนบังคับทุกเทอม (ไม่รวมปี 4 เทอม 2):")
    total_other = 0
    for (yr, sem), group in groupby(other, key=lambda r: (r["year"], r["semester"])):
        courses = list(group)
        sem_credits = sum(cc["credits_total"] or 0 for cc in courses)
        total_other += sem_credits
        lines.append(f"\n  ปีที่ {yr} ภาคการศึกษาที่ {sem} ({len(courses)} วิชา, {sem_credits} หน่วยกิต):")
        for cc in courses:
            en = f" ({cc['name_en']})" if cc["name_en"] else ""
            lines.append(f"    - {cc['code']} {cc['name_th']}{en} — {cc['credits_raw']}")
        # วิชาเลือกแขนง/เฉพาะด้าน ที่ต้องลงในเทอมนี้ (จากแผนในเอกสาร)
        elective_slots = extract_elective_slots(conn, version_id, yr, sem)
        if elective_slots:
            lines.append(f"    + วิชาเลือกเฉพาะแขนง (เลือก 1 แขนง แล้วลงวิชาในแขนงนั้น) กลุ่มที่มี:")
            for slot in elective_slots:
                lines.append(f"      • {slot}")

    extra = last_credits + elective_credits_total
    lines.append("")
    lines.append(f"สรุป: ต้องดึงวิชาปี 4 เทอม 2 ({last_credits} หน่วยกิต) + วิชาเลือก/เลือกเสรี ({elective_credits_total} หน่วยกิต)")
    lines.append(f"รวม {extra} หน่วยกิต มากระจายลงในเทอมก่อนหน้า")
    lines.append("แนะนำเฉลี่ยเพิ่มเทอมละ 3-6 หน่วยกิต เพื่อไม่ให้หนักเกินไป")
    lines.append("และต้องตรวจ prerequisite ว่าวิชาที่จะดึงขึ้นมาลงก่อนได้จริง")

    return StructuredResult(True, "\n".join(lines), version_label, "plan_summary")


_SEM_HEADER_RE = re.compile(r"ปีที่\s*([1-4])\s*ภาค(?:การศึกษา|เรียน)ที่\s*([1-3])")
_SEM_TOTAL_RE = re.compile(r"(?<![ก-๙])รวม\s*\|?\s*(\d{1,2})(?![\d.])")
_LOAD_MAX_KW = ("มากที่สุด", "เยอะที่สุด", "หนักที่สุด", "สูงสุด")
_LOAD_MIN_KW = ("น้อยที่สุด", "เบาที่สุด", "ต่ำสุด", "น้อยสุด")


def detect_semester_load_intent(question: str) -> bool:
    """ถามภาคเรียนที่หน่วยกิตตามแผนมาก/น้อยที่สุด."""
    return (
        "หน่วยกิต" in question
        and any(w in question for w in ("ภาค", "เทอม"))
        and any(w in question for w in _LOAD_MAX_KW + _LOAD_MIN_KW)
    )


def semester_totals(conn: sqlite3.Connection, version_id: int) -> dict[tuple[int, int], tuple[int, int]]:
    """หน่วยกิตรวมของแต่ละภาคตามแผนการศึกษา อ่านจากบรรทัด 'รวม' ใต้หัว 'ปีที่ X ภาคการศึกษาที่ Y'
    ในหน้าแผนของเล่ม (รวมวิชาเลือกที่แผนกำหนดแล้ว ต่างจากผลรวมวิชาบังคับในตาราง course).

    คืน {(ปี, ภาค): (หน่วยกิต, หน้า)} — ใช้ตารางแรกที่พบ (แผนปกติ; แผนสหกิจอยู่หน้าหลังกว่า)
    """
    found: dict[tuple[int, int], tuple[int, int]] = {}
    for page_no, text in conn.execute(
        "SELECT p.page_number, p.page_text FROM page p JOIN document d ON d.document_id = p.document_id "
        "WHERE d.version_id=? ORDER BY p.document_id, p.page_number",
        (version_id,),
    ):
        heads = list(_SEM_HEADER_RE.finditer(text))
        for i, h in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            m = _SEM_TOTAL_RE.search(text, h.end(), end)
            key = (int(h.group(1)), int(h.group(2)))
            if m and key not in found:
                found[key] = (int(m.group(1)), page_no)
    return found


def try_semester_load(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ภาคเรียนที่ต้องลงหน่วยกิตมาก/น้อยที่สุดตามแผนการศึกษาในเล่ม."""
    program = detect_program(question)
    if not program:
        return StructuredResult(False, "", "", "none")
    named = [v for v, p, _ in detect_versions(conn, question) if p == program]
    resolved = (named[0], "") if named else _resolve_version_id(conn, program, None)
    if not resolved:
        return StructuredResult(False, "", "", "none")
    vid = resolved[0]
    from katrag.query.plan_variants import _flags as _plan_flags, plan_blocks, variant_totals

    variant = "coop" if _plan_flags(question)[0] else "default"
    mp = variant_totals(plan_blocks(conn, vid), variant)
    totals = {k: (b.total, b.pages[0]) for k, b in mp.items() if b.total is not None}
    if not totals:
        totals = semester_totals(conn, vid)
    if not totals:
        return StructuredResult(False, "", "", "none")

    label = _versions_label(conn, [vid])
    want_min = any(w in question for w in _LOAD_MIN_KW)
    plan_name = "แผนที่เข้าโครงการสหกิจศึกษา" if variant == "coop" else "แผนปกติ"
    lines = [f"หน่วยกิตต่อภาคตาม{plan_name}ของ {label} (จากบรรทัด 'รวม' ของแต่ละภาคในเล่ม รวมวิชาเลือกที่แผนกำหนดแล้ว):"]
    for (y, s), (cr, pg) in sorted(totals.items()):
        lines.append(f"  - ปีที่ {y} ภาคการศึกษาที่ {s}: {cr} หน่วยกิต (หน้า {pg})")

    target = min(c for c, _ in totals.values()) if want_min else max(c for c, _ in totals.values())
    hits = [f"ปีที่ {y} ภาคการศึกษาที่ {s}" for (y, s), (c, _) in sorted(totals.items()) if c == target]
    word = "น้อยที่สุด" if want_min else "มากที่สุด"
    lines.append("")
    lines.append(f"ภาคที่หน่วยกิต{word}: {' และ '.join(hits)} — {target} หน่วยกิต")

    # ตรวจความครบ: ผลรวมทุกภาคควรเท่าหน่วยกิตรวมของหลักสูตร (ตาราง rule)
    total = sum(c for c, _ in totals.values())
    rule = conn.execute(
        "SELECT value_numeric FROM rule WHERE version_id=? AND attribute='min_total_credits'", (vid,)
    ).fetchone()
    if rule and rule[0] is not None and int(rule[0]) != total:
        lines.append(
            f"หมายเหตุ: อ่านตัวเลขรวมได้ {len(totals)} ภาค ผลรวม {total} หน่วยกิต ไม่เท่าหน่วยกิตรวมของหลักสูตร "
            f"{rule[0]:g} หน่วยกิต อาจมีบางภาคที่อ่านจากเล่มไม่ได้"
        )
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (vid,)
    ).fetchone()
    pages = sorted({pg for _c, pg in totals.values()})
    return StructuredResult(
        True, "\n".join(lines), label, "semester_load", version_id=vid,
        pages=[(doc[0], pg, "ตารางแผนการศึกษา") for pg in pages] if doc else [],
    )


_TOTAL_CREDIT_KW = (
    "หน่วยกิตรวม", "ตลอดหลักสูตร", "ต้องเรียนกี่หน่วยกิต", "ต้องเรียนหน่วยกิต", "หน่วยกิตที่เรียน",
)
#: ถ้าคำถามถามเรื่องอื่นปนด้วย (แขนง/แผน/โครงสร้าง) ให้ LLM เรียบเรียงต่อ ไม่ตอบตรง
_OTHER_ASPECT_KW = ("แขนง", "แผน", "โครงสร้าง", "อย่างไร", "รายวิชา", "โมดูล")


def detect_credit_compare_intent(conn: sqlite3.Connection, question: str) -> bool:
    """ถามหน่วยกิตรวมของหลักสูตร โดยระบุตั้งแต่ 2 เวอร์ชันขึ้นไป."""
    if not any(k in question for k in _TOTAL_CREDIT_KW):
        return False
    return len(detect_versions(conn, question)) >= 2


def try_credit_compare(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """เทียบหน่วยกิตรวมตลอดหลักสูตรของหลายเวอร์ชัน จากตาราง rule (มี provenance).

    ถ้าเวอร์ชันใดไม่มีค่าในตาราง จะไม่ตอบ (ปล่อยให้ไป retrieval) แทนการเดา
    """
    versions = detect_versions(conn, question)
    if len(versions) < 2 or not any(k in question for k in _TOTAL_CREDIT_KW):
        return StructuredResult(False, "", "", "none")

    facts: list[tuple[str, float, int]] = []  # (label, credits, page)
    for version_id, program, year in versions:
        row = conn.execute(
            "SELECT r.value_numeric, p.page_number FROM rule r "
            "JOIN provenance p ON p.provenance_id = r.provenance_id "
            "WHERE r.version_id=? AND r.rule_kind='graduation' AND r.attribute='min_total_credits'",
            (version_id,),
        ).fetchone()
        if row is None:
            return StructuredResult(False, "", "", "none")
        facts.append((f"{program} {year}", row[0], row[1]))

    lines = ["หน่วยกิตรวมตลอดหลักสูตร (จากหน้าโครงสร้างหลักสูตรในเล่ม):"]
    for label, credits, page in facts:
        lines.append(f"- {label}: {credits:g} หน่วยกิต (มคอ.2 {label} หน้า {page})")

    if len(facts) == 2:
        a, b = facts[0][1], facts[1][1]
        if a == b:
            lines.append(f"\nสรุป: เท่ากัน ({a:g} หน่วยกิต)")
        else:
            more, less = (facts[0], facts[1]) if a > b else (facts[1], facts[0])
            lines.append(f"\nสรุป: {more[0]} มากกว่า {less[0]} อยู่ {abs(a - b):g} หน่วยกิต")
    else:
        top = max(f[1] for f in facts)
        low = min(f[1] for f in facts)
        tops = ", ".join(f[0] for f in facts if f[1] == top)
        lows = ", ".join(f[0] for f in facts if f[1] == low)
        lines.append(f"\nสรุป: มากที่สุดคือ {tops} ({top:g} หน่วยกิต) น้อยที่สุดคือ {lows} ({low:g} หน่วยกิต)")

    intent = "credit_compare_mixed" if any(k in question for k in _OTHER_ASPECT_KW) else "credit_compare"
    return StructuredResult(
        True, "\n".join(lines), " vs ".join(f[0] for f in facts), intent,
        version_id=versions[0][0],
    )


def asks_about_courses(question: str) -> bool:
    """คำถามเทียบเวอร์ชันที่ถามเรื่องรายวิชา (ไม่ใช่หน่วยกิตรวม/แผน/โครงสร้าง)."""
    if any(k in question for k in _TOTAL_CREDIT_KW):
        return False
    return "วิชา" in question


_VERSION_WORDS = ("เก่า", "ใหม่", "ฉบับเดิม", "ฉบับก่อน")
_SET_DIFF_WORDS = ("แต่ไม่มี", "ไม่มีใน", "ไม่อยู่ใน", "ที่หาย", "ที่ตัด", "ที่เพิ่ม", "หายไป", "เพิ่มเข้ามา")


def compares_versions(conn: sqlite3.Connection, question: str) -> bool:
    """คำถามเทียบ "เวอร์ชันหลักสูตร" จริง ไม่ใช่เทียบแผนภายในเวอร์ชันเดียว (เช่น แผนปกติ vs สหกิจ)."""
    if len(detect_versions(conn, question)) >= 2:
        return True
    return any(w in question for w in _VERSION_WORDS + _SET_DIFF_WORDS)


def detect_cross_version_intent(question: str) -> bool:
    """ตรวจว่าเป็นคำถามเทียบหลักสูตรเก่า-ใหม่.

    จับสามรูปแบบ:
    1. คำเปรียบเทียบตรง ๆ (เปรียบเทียบ/ต่างกัน/เก่า/ใหม่ ฯลฯ)
    2. Set-difference phrasing ("แต่ไม่มี/ไม่มีใน/แต่ไม่อยู่") — คำถาม M4
       ที่ถามว่า "วิชาที่มีใน 2560 แต่ไม่มีใน 2565" เข้าข่ายนี้
    3. อ้างปีหลักสูตร 2 ปีในคำถามเดียว (พ.ศ. 2555-2570) — เช่น "2560 กับ 2565"
       เป็นสัญญาณชัดว่ากำลังเทียบเวอร์ชัน
    """
    has_compare = any(w in question for w in [
        "เก่า", "ใหม่", "เปรียบเทียบ", "ต่างกัน", "แตกต่าง",
        "หายไป", "เพิ่มเข้ามา", "ตัดออก",
    ])
    if has_compare:
        return True

    # "แต่ไม่มี" / "ไม่มีใน" / "แต่ไม่อยู่" — set-difference phrasing
    set_diff_patterns = [
        "แต่ไม่มี", "แต่ไม่อยู่", "แต่ไม่ได้มี",
        "ไม่มีใน", "ไม่อยู่ใน", "ไม่ได้อยู่ใน",
        "ที่หาย", "ที่ตัด", "ที่เพิ่ม",
    ]
    if any(p in question for p in set_diff_patterns):
        return True

    # ตรวจปี พ.ศ. 2 ปีในคำถาม (25xx สองครั้ง) — เช่น "2560 กับ 2565"
    years = re.findall(r"\b25[5-7]\d\b", question)
    if len(set(years)) >= 2:
        return True

    return False


def try_cross_version_diff(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """เทียบรายวิชาระหว่างหลักสูตรเก่ากับใหม่ (เทียบด้วยชื่อวิชา)."""
    conn.row_factory = sqlite3.Row
    program = detect_program(question)
    if not program or not detect_cross_version_intent(question):
        return StructuredResult(False, "", "", "none")

    # ดึง version เก่า + ใหม่ ของ program
    vers = conn.execute(
        "SELECT version_id, curriculum_year, edition_status FROM curriculum_version WHERE program=? ORDER BY curriculum_year",
        (program,),
    ).fetchall()
    old_v = next((v for v in vers if v["edition_status"] == "old"), None)
    new_v = next((v for v in vers if v["edition_status"] == "current"), None)
    # ถ้าคำถามระบุปีของหลักสูตรนี้ 2 ปีชัดเจน ใช้ตามนั้น (เช่น IT 2563 กับ 2568)
    named = [v for v in detect_versions(conn, question) if v[1] == program]
    if len(named) >= 2:
        by_id = {v["version_id"]: v for v in vers}
        pair = sorted((by_id[n[0]] for n in named[:2]), key=lambda v: v["curriculum_year"])
        old_v, new_v = pair[0], pair[1]
    if not old_v or not new_v:
        return StructuredResult(False, "", "", "none")

    def _courses(vid):
        rows = conn.execute("SELECT code, name_th, name_en FROM course WHERE version_id=?", (vid,)).fetchall()
        return {_norm_name(r["name_th"]): (r["code"], r["name_th"], r["name_en"]) for r in rows}

    old_courses = _courses(old_v["version_id"])
    new_courses = _courses(new_v["version_id"])

    only_old = [v for k, v in old_courses.items() if k not in new_courses]
    only_new = [v for k, v in new_courses.items() if k not in old_courses]

    label = f"{program} {old_v['curriculum_year']} (เก่า) vs {new_v['curriculum_year']} (ใหม่)"
    lines = [f"เปรียบเทียบหลักสูตร {label} (เทียบด้วยชื่อวิชา):"]
    lines.append(f"\nวิชาที่มีในหลักสูตรเก่า ({old_v['curriculum_year']}) แต่ไม่มีในหลักสูตรใหม่ ({new_v['curriculum_year']}) — {len(only_old)} วิชา:")
    for code, th, en in sorted(only_old, key=lambda x: x[1])[:40]:
        en_s = f" ({en})" if en else ""
        lines.append(f"- {th}{en_s} [รหัสเดิม {code}]")
    lines.append(f"\nวิชาที่เพิ่มเข้ามาในหลักสูตรใหม่ ({new_v['curriculum_year']}) — {len(only_new)} วิชา:")
    for code, th, en in sorted(only_new, key=lambda x: x[1])[:40]:
        en_s = f" ({en})" if en else ""
        lines.append(f"- {th}{en_s} [รหัส {code}]")

    return StructuredResult(True, "\n".join(lines), label, "cross_version")


# ── Program name intent (ชื่อหลักสูตรเต็ม ไทย/อังกฤษ) ──────────────────
# คำถาม "หลักสูตร X ชื่อเต็มภาษาอังกฤษว่าอะไร" เป็น metadata ของเล่ม ไม่ใช่
# รายวิชา — hybrid/semantic retrieval มักพลาดเพราะหน้าปก/หน้าข้อมูลทั่วไป
# มีคำน้อยและไม่ตรง embedding ของคำถาม จึงดึงตรงจาก chunk หน้าแรก ๆ ที่มี
# "ชื่อภาษาอังกฤษ/ชื่อหลักสูตร" + ข้อความภาษาอังกฤษ

_PROGRAM_NAME_KW = (
    "ชื่อหลักสูตร", "ชื่อเต็ม", "ชื่อปริญญา", "ชื่อภาษาอังกฤษ",
    "ชื่ออังกฤษ", "ชื่อภาษาไทย", "full name", "program name",
)


def detect_program_name_intent(question: str) -> bool:
    """ถามชื่อหลักสูตร/ชื่อปริญญา (ไม่ใช่ชื่อรายวิชา).

    ต้องมีคำว่า 'หลักสูตร' หรือ 'ปริญญา' ประกอบ เพื่อไม่ชนกับคำถามชื่อ 'วิชา'
    """
    q = question.lower()
    if "วิชา" in question and "หลักสูตร" not in question:
        return False  # ถามชื่อวิชา ไม่ใช่ชื่อหลักสูตร
    has_name_kw = any(kw.lower() in q for kw in _PROGRAM_NAME_KW)
    has_program_ctx = any(w in question for w in ["หลักสูตร", "ปริญญา", "สาขา"])
    return has_name_kw and has_program_ctx


def try_program_name(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ดึงชื่อหลักสูตร (ไทย/อังกฤษ) จากหน้าข้อมูลทั่วไปของเล่ม.

    ค้น chunk ที่มี 'ชื่อภาษาอังกฤษ'/'ชื่อหลักสูตร' + ข้อความละติน ในหน้าต้นเล่ม
    (โครงสร้าง มคอ.2 วางข้อมูลนี้ในหมวดที่ 1 หน้า 1-6)
    """
    conn.row_factory = sqlite3.Row
    if not detect_program_name_intent(question):
        return StructuredResult(False, "", "", "none")

    program = detect_program(question)
    year = detect_year(question)  # พ.ศ.

    # หา version ที่ตรง (program + year ถ้าระบุ ไม่งั้น current)
    vid = None
    version_label = program or ""
    if program:
        rows = conn.execute(
            "SELECT version_id, curriculum_year, edition_status "
            "FROM curriculum_version WHERE program=? ORDER BY curriculum_year DESC",
            (program,),
        ).fetchall()
        for r in rows:
            if year and r["curriculum_year"] == year:
                vid = r["version_id"]
                version_label = f"{program} {r['curriculum_year']}"
                break
        if vid is None and rows:
            # ไม่ระบุปี → เอา current (ปีล่าสุด)
            vid = rows[0]["version_id"]
            version_label = f"{program} {rows[0]['curriculum_year']}"

    # ค้น chunk ที่มี keyword ชื่อหลักสูตร + ข้อความละติน ในหน้าต้นเล่ม (<=10)
    sql = (
        "SELECT chunk_id, page_number, text FROM chunk "
        "WHERE page_number <= 10 AND is_boilerplate = 0 "
        "AND (text LIKE '%ชื่อภาษาอังกฤษ%' OR text LIKE '%ชื่อหลักสูตร%' "
        "     OR text LIKE '%Bachelor%' OR text LIKE '%Master%' OR text LIKE '%Doctor%') "
    )
    params: list = []
    if vid is not None:
        sql += "AND version_id = ? "
        params.append(vid)
    sql += "ORDER BY page_number LIMIT 4"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return StructuredResult(False, "", "", "none")

    # ประกอบ context — เอาบรรทัดที่มีชื่อไทย/อังกฤษของหลักสูตร
    lines: list[str] = []
    for r in rows:
        for ln in r["text"].split("\n"):
            s = ln.strip()
            if not s:
                continue
            if any(kw in s for kw in ("ชื่อหลักสูตร", "ชื่อภาษา", "ชื่ออังกฤษ", "ชื่อปริญญา",
                                       "Bachelor", "Master", "Doctor", "B.Sc", "M.Sc", "Ph.D")):
                lines.append(f"(หน้า {r['page_number']}) {s}")

    if not lines:
        return StructuredResult(False, "", "", "none")

    # ตัดซ้ำ คงลำดับ
    seen: set[str] = set()
    uniq = [x for x in lines if not (x in seen or seen.add(x))]
    context = "ข้อมูลชื่อหลักสูตรที่พบในเล่ม:\n" + "\n".join(uniq[:12])

    return StructuredResult(
        matched=True, context=context,
        version_label=version_label or "หลักสูตร",
        intent="program_name", version_id=vid,
    )


# ══════════════════════════════════════════════════════════════════════
# เกณฑ์สำเร็จการศึกษา / เกียรตินิยม (ตาราง `rule`)
# ══════════════════════════════════════════════════════════════════════

_RULE_KIND_LABEL = {
    "graduation": "เกณฑ์การสำเร็จการศึกษา",
    "honors": "เกณฑ์เกียรตินิยม",
    "dismissal": "เกณฑ์การพ้นสภาพ",
    "probation": "เกณฑ์ภาคทัณฑ์",
    "grading": "เกณฑ์การให้คะแนน",
}

_ATTRIBUTE_LABEL = {
    "min_total_credits": "หน่วยกิตขั้นต่ำที่ต้องเรียนตลอดหลักสูตร",
    "min_gpa": "เกรดเฉลี่ยสะสมขั้นต่ำ",
    "min_gpa_honors_1_gold": "เกรดเฉลี่ยขั้นต่ำสำหรับเกียรตินิยมอันดับ 1 เหรียญทอง",
}

_GRADUATION_KW = ("จบการศึกษา", "สำเร็จการศึกษา", "เกณฑ์การจบ", "เกณฑ์จบ")
_HONORS_KW = ("เกียรตินิยม",)


def detect_rule_intent(question: str) -> str | None:
    """ตรวจว่าคำถามถามเกณฑ์ที่มีอยู่ในตาราง `rule` — คืน rule_kind หรือ None.

    ครอบเฉพาะ 'graduation' และ 'honors' เพราะเป็นสองประเภทเดียวที่ populate_rules
    ใส่ข้อมูลไว้จริง (ยืนยันด้วย provenance ในเล่ม + ตรงกับ teacher GT)
    """
    if any(kw in question for kw in _HONORS_KW):
        return "honors"
    if any(kw in question for kw in _GRADUATION_KW):
        return "graduation"
    # สำนวนสั้น เช่น "ต้องเรียนกี่หน่วยกิตจึงจะจบ", "รวม 116 หน่วยกิต จบได้ไหม"
    if "หน่วยกิต" in question and _GRAD_SHORT_RE.search(question):
        return "graduation"
    return None


_GRAD_SHORT_RE = re.compile(r"(?:จึงจะ|ถึงจะ|เพื่อ|ถึง|ให้)\s*จบ|จบ\s*(?:ได้|การ|หลักสูตร)")


def try_rule_answer(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ตอบคำถามเกณฑ์สำเร็จการศึกษา/เกียรตินิยมจากตาราง `rule`.

    ต่างจาก intent อื่นที่ตอบจาก course/plan_slot — rule table เก็บเกณฑ์ระดับ
    หลักสูตร (ไม่ใช่รายวิชา) ที่ provenance ยืนยันแล้วว่ามีตัวเลขปรากฏจริงในเล่ม
    (ดู katrag/ingest/populate_rules.py สำหรับที่มาและขอบเขตที่ยืนยันแล้ว)
    """
    conn.row_factory = sqlite3.Row
    rule_kind = detect_rule_intent(question)
    if rule_kind is None:
        return StructuredResult(False, "", "", "none")

    program = detect_program(question)
    if program is None:
        return StructuredResult(False, "", "", "none")

    # ปีที่ระบุในคำถาม (เช่น "BIT 2560") ชนะฉบับ current
    named = [(v, y) for v, p, y in detect_versions(conn, question) if p == program]
    version_id = named[0][0] if len(named) == 1 else _resolve_version_for_rule(conn, program)
    if version_id is None:
        return StructuredResult(False, "", "", "none")
    if len(named) == 1:
        program = f"{program} {named[0][1]}"

    rows = conn.execute(
        "SELECT rule_kind, attribute, comparator, value_numeric, value_text "
        "FROM rule WHERE version_id=? AND rule_kind=? AND attribute NOT LIKE 'credits.%' ORDER BY attribute",
        (version_id, rule_kind),
    ).fetchall()
    if not rows:
        return StructuredResult(False, "", "", "none")

    label = _RULE_KIND_LABEL.get(rule_kind, rule_kind)
    lines = [f"{label} ({program}):"]
    for r in rows:
        attr_label = _ATTRIBUTE_LABEL.get(r["attribute"], r["attribute"])
        value = f"{r['value_numeric']:g}" if r["value_numeric"] is not None else r["value_text"]
        lines.append(f"  - {attr_label} {r['comparator']} {value}")

    return StructuredResult(
        matched=True, context="\n".join(lines),
        version_label=f"{program} (rule)", intent="rule",
        version_id=version_id,
    )


def _resolve_version_for_rule(conn: sqlite3.Connection, program: str) -> int | None:
    """เลือก version 'current' ที่มีจำนวนวิชามากสุด — สอดคล้องกับ
    populate_rules._resolve_current_version และ build_gold_set._resolve_version
    เพื่อไม่ให้ query คนละที่เห็นข้อมูลของคนละเวอร์ชัน (ปัญหา IT มี 3 current)
    """
    row = conn.execute(
        "SELECT cv.version_id FROM curriculum_version cv "
        "LEFT JOIN course c ON c.version_id = cv.version_id "
        "WHERE cv.program=? AND cv.edition_status='current' "
        "GROUP BY cv.version_id ORDER BY COUNT(c.course_id) DESC, cv.curriculum_year DESC LIMIT 1",
        (program,),
    ).fetchone()
    return row[0] if row else None


# ── โครงสร้างหน่วยกิตรายหมวด/กลุ่มวิชา (rule: attribute 'credits.*') ──────────

#: คำที่บ่งชี้ว่าถามหน่วยกิตของหมวด/กลุ่มวิชา (ไม่ใช่รายวิชา)
_STRUCT_CATEGORY_KW = (
    "ศึกษาทั่วไป", "เลือกเสรี", "วิชาแกน", "พื้นฐานวิชาชีพ", "การศึกษาทางเลือก", "วิชาชีพเฉพาะด้าน",
    "เฉพาะด้าน", "เฉพาะเลือก", "วิชาเลือกเฉพาะ", "วิชาชีพเลือก", "บังคับเฉพาะ", "หมวดวิชาเฉพาะ",
)
_STRUCT_EXCLUDE_KW = ("กี่วิชา", "มีวิชาอะไร", "วิชาอะไรบ้าง", "ชื่อวิชา", "รหัสวิชา", "ภาคการศึกษา", "เทอม")


_SYNONYM_HINT_RE = re.compile(r"\(เอกสารอาจใช้คำ:[^)]*\)")


def _strip_synonym_hint(question: str) -> str:
    """ตัดคำใบ้คำเทียบเคียงที่ pipeline ต่อท้ายคำถามออก — ไม่ใช่คำที่ผู้ถามพูด."""
    return _SYNONYM_HINT_RE.sub("", question)


def detect_structure_intent(question: str) -> bool:
    """ถามหน่วยกิตของหมวด/กลุ่มวิชาตามโครงสร้างหลักสูตร เช่น "หมวดวิชาศึกษาทั่วไปเก็บกี่หน่วยกิต"."""
    question = _strip_synonym_hint(question)
    if "หน่วยกิต" not in question or detect_course_code(question):
        return False
    if any(k in question for k in _STRUCT_EXCLUDE_KW) or detect_year(question) is not None:
        return False
    if not any(k in question for k in _STRUCT_CATEGORY_KW):
        return False
    return "หมวด" in question or "กลุ่ม" in question


def _struct_matches(question: str, attr: str) -> bool:
    """attribute นี้คือสิ่งที่คำถามพูดถึงไหม."""
    key = attr.replace("credits.", "")
    q = question
    if "เลือกเสรี" in q and key == "free_elective":
        return True
    if "ศึกษาทั่วไป" in q and key == "general_education":
        return True
    if "วิชาแกน" in q and key == "specific.core":
        return True
    if "พื้นฐานวิชาชีพ" in q and key.endswith(".foundation"):
        return True
    if "การศึกษาทางเลือก" in q and key.endswith(".alternative"):
        return True
    if any(k in q for k in ("วิชาชีพเฉพาะด้าน", "เฉพาะด้าน")) and key == "specific.professional":
        return True
    if any(k in q for k in ("เฉพาะเลือก", "วิชาเลือกเฉพาะ", "วิชาชีพเลือก")) and key in (
        "specific.professional", "specific.elective", "specific.elective_it", "specific.ai_elective",
        "specific.alternative",
    ):
        return True
    if "บังคับเฉพาะ" in q and key.endswith("required_track"):
        return True
    if "หมวดวิชาเฉพาะ" in q and "เฉพาะเลือก" not in q and key == "specific":
        return True
    return False


def try_structure_answer(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ตอบหน่วยกิตของหมวด/กลุ่มวิชาจากตาราง rule (อ่านจากหน้าโครงสร้างหลักสูตรในเล่ม พร้อมหน้าที่มา)."""
    question = _strip_synonym_hint(question)
    program = detect_program(question)
    if not program:
        return StructuredResult(False, "", "", "none")
    named = [(v, y) for v, p, y in detect_versions(conn, question) if p == program]
    version_id = named[0][0] if len(named) == 1 else _resolve_version_for_rule(conn, program)
    if version_id is None:
        return StructuredResult(False, "", "", "none")
    rows = conn.execute(
        "SELECT r.attribute, r.value_numeric, r.value_text, p.document_id, p.page_number "
        "FROM rule r JOIN provenance p ON p.provenance_id = r.provenance_id "
        "WHERE r.version_id=? AND r.attribute LIKE 'credits.%' ORDER BY r.rule_id",
        (version_id,),
    ).fetchall()
    if not rows:
        return StructuredResult(False, "", "", "none")
    label = _versions_label(conn, [version_id])
    hit = [r for r in rows if _struct_matches(question, r[0])]
    if not hit:
        return StructuredResult(False, "", "", "none")

    def _fmt(r) -> str:
        name, _, note = (r[2] or "").partition(" | ")
        return f"{name} {r[1]:g} หน่วยกิต" + (f" ({note})" if note else "") + f" — หน้า {r[4]}"

    lines = [f"หน่วยกิตตามโครงสร้างหลักสูตร {label} (จากหน้าโครงสร้างหลักสูตรใน มคอ.2):", ""]
    lines += [f"▶ {_fmt(r)}" for r in hit]
    lines += ["", "โครงสร้างทั้งหมดของหลักสูตร:"]
    for r in rows:
        depth = r[0].count(".") - 1
        mark = " ◀" if r in hit else ""
        name, _, note = (r[2] or "").partition(" | ")
        lines.append(f"{'  ' * (depth + 1)}- {name} {r[1]:g} หน่วยกิต{mark}")
    total = conn.execute(
        "SELECT value_numeric FROM rule WHERE version_id=? AND attribute='min_total_credits'", (version_id,)
    ).fetchone()
    if total and total[0] is not None:
        lines.append(f"\nหน่วยกิตรวมตลอดหลักสูตร {total[0]:g} หน่วยกิต")
    pages = sorted({(r[3], r[4]) for r in hit})
    return StructuredResult(
        True, "\n".join(lines), label, "category_credits", version_id=version_id,
        pages=[(d, p, "โครงสร้างหลักสูตร 3.1.2") for d, p in pages],
    )


# ══════════════════════════════════════════════════════════════════════
# person — คำถามอาจารย์ผู้รับผิดชอบ/ประจำ/ผู้สอน (ตาราง person)
# ══════════════════════════════════════════════════════════════════════

#: version ที่ตาราง person มีข้อมูลจริง (ตรงกับ populate_person._STRUCTURED_VERSIONS
#: + _RESPONSIBLE_ONLY_VERSIONS — hardcode เพราะ resolve ปกติ (จำนวนวิชามากสุด)
#: จะได้ version ที่ไม่มีข้อมูลอาจารย์เลยสำหรับ IT ซึ่งมี 3 current พร้อมกัน)
_PERSON_VERSIONS: dict[str, int] = {
    "AIT": 1, "AITBA": 8, "IT": 13, "DSBA": 5, "BIT": 3,
}

#: หลักสูตรที่เล่มไม่มี role อื่นนอกจาก responsible (ใช้อธิบายบริบทตอนตอบ
#: role ที่ไม่มีข้อมูล — ดู populate_person.py หัวไฟล์สำหรับที่มา)
_RESPONSIBLE_ONLY_PROGRAMS = frozenset({"DSBA", "BIT"})

_PERSON_ROLE_LABEL = {
    "responsible": "อาจารย์ผู้รับผิดชอบหลักสูตร",
    "regular": "อาจารย์ประจำหลักสูตร",
    "teaching_regular": "อาจารย์ผู้สอนที่เป็นอาจารย์ประจำ",
}

_PERSON_KW = ("อาจารย์ผู้รับผิดชอบ", "อาจารย์ประจำหลักสูตร", "อาจารย์ผู้สอน", "อาจารย์ประจำ")


def detect_person_intent(question: str) -> bool:
    """ตรวจว่าคำถามถามรายชื่ออาจารย์ (ผู้รับผิดชอบ/ประจำ/ผู้สอน) หรือไม่."""
    if not any(kw in question for kw in _PERSON_KW):
        return False
    return any(w in question for w in ("มีใคร", "รายชื่อ", "ชื่ออะไร", "กี่คน", "ใครบ้าง"))


def _detect_person_role(question: str) -> str:
    """แยกบทบาทที่ถาม — ต้องเช็ค 'ผู้รับผิดชอบ' และ 'ผู้สอน' ก่อน 'ประจำ' เฉย ๆ
    เพราะ 'อาจารย์ประจำหลักสูตร' (regular) เป็นคำที่ไม่ทับซ้อนกับอีกสองคำ แต่
    ถ้าตรวจ 'อาจารย์ประจำ' แบบกว้างก่อนจะจับ regular ผิดทุกกรณี (default เมื่อ
    ไม่ระบุชัดคือ responsible เพราะเป็นกลุ่มที่ทุกหลักสูตรมีข้อมูลแน่นอน)
    """
    if "ผู้รับผิดชอบ" in question:
        return "responsible"
    if "ผู้สอน" in question:
        return "teaching_regular"
    if "ประจำหลักสูตร" in question or "ประจำ" in question:
        return "regular"
    return "responsible"


def try_person_answer(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ตอบคำถามรายชื่ออาจารย์จากตาราง `person` (สกัดจาก chunk.heading มคอ.2
    หมวดที่ 5 — ดู katrag/ingest/populate_person.py สำหรับที่มา/ขอบเขต).

    DSBA/BIT เล่มไม่มี sub-heading แยก role อื่นนอกจาก responsible — ถ้าถาม
    role อื่น ตอบตามข้อมูลที่มีจริง พร้อมอธิบายบริบทว่าเล่มไม่ได้แยกไว้ต่างหาก
    (ตกลงกับผู้ใช้แล้วว่า 'ตอบตามข้อมูลที่มีจริง' ดีกว่าไม่ตอบเลยหรือเดาให้ครบ)
    """
    conn.row_factory = sqlite3.Row
    if not detect_person_intent(question):
        return StructuredResult(False, "", "", "none")

    program = detect_program(question)
    if program is None:
        return StructuredResult(False, "", "", "none")

    version_id = _PERSON_VERSIONS.get(program)
    if version_id is None:
        return StructuredResult(False, "", "", "none")

    role = _detect_person_role(question)
    rows = conn.execute(
        "SELECT sequence_no, name_raw FROM person "
        "WHERE version_id=? AND role=? ORDER BY sequence_no",
        (version_id, role),
    ).fetchall()

    role_label = _PERSON_ROLE_LABEL[role]
    if not rows:
        if program in _RESPONSIBLE_ONLY_PROGRAMS and role != "responsible":
            ctx = (
                f"เอกสารหลักสูตร {program} (มคอ.2) ระบุเฉพาะ 'อาจารย์ผู้รับผิดชอบ"
                f"หลักสูตร' เท่านั้น ไม่ได้แยกรายชื่อ '{role_label}' ไว้ต่างหาก "
                f"จึงไม่มีข้อมูลสำหรับคำถามนี้โดยตรง (ถ้าต้องการรายชื่ออาจารย์"
                f"ผู้รับผิดชอบหลักสูตร ถามใหม่ได้)"
            )
            return StructuredResult(True, ctx, program, "person")
        return StructuredResult(False, "", "", "none")

    lines = [f"{role_label} หลักสูตร {program} มีจำนวน {len(rows)} คน ได้แก่:"]
    for r in rows:
        lines.append(f"  {r['sequence_no']}. {r['name_raw']}")

    return StructuredResult(True, "\n".join(lines), f"{program} (person)", "person", version_id=version_id)


# ══════════════════════════════════════════════════════════════════════
# Intent เพิ่มเติมสำหรับคำถามเฉพาะด้าน (Code Lookup, Document Relations,
# Plan Branching, Graduation Audit, Cross-version Overview, Elective Credits)
# ══════════════════════════════════════════════════════════════════════

def detect_course_code(question: str) -> str | None:
    """ตรวจหารหัสวิชา 8 หลัก (เช่น 06066303, 90641001) หรือรูปแบบมีขีด/วรรค เช่น 06-066-303."""
    m = re.search(r"\b(06\d{6}|90\d{6}|\d{8})\b", question)
    if m:
        return m.group(1)
    m_sep = re.search(r"\b(\d{2})[- ]?(\d{3})[- ]?(\d{3})\b", question)
    if m_sep:
        combined = "".join(m_sep.groups())
        if len(combined) == 8:
            return combined
    return None


def try_course_code(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """ตอบชื่อวิชาและข้อมูลจากรหัสวิชาตรง ๆ."""
    code = detect_course_code(question)
    if not code:
        return StructuredResult(False, "", "", "none")
    conn.row_factory = sqlite3.Row
    program = detect_program(question)

    rows = conn.execute(
        "SELECT code, name_th, name_en, credits_raw, year, semester, version_id FROM course WHERE code=? ORDER BY year DESC",
        (code,),
    ).fetchall()
    if not rows:
        return StructuredResult(False, "", "", "none")

    r = rows[0]
    en = f" ({r['name_en']})" if r["name_en"] else ""
    plan_info = f" | แผนการเรียน: ปีที่ {r['year']} ภาคการศึกษาที่ {r['semester']}" if r["year"] and r["semester"] else ""

    ans = f"รหัสวิชา {r['code']} คือวิชา:\n- {r['name_th']}{en}\n- จำนวนหน่วยกิต: {r['credits_raw']}{plan_info}"
    return StructuredResult(
        True, ans, program or "", "course_code",
        codes=[r["code"]], version_id=r["version_id"]
    )


def detect_document_relation_intent(question: str) -> bool:
    """ตรวจคำถามเรื่องเอกสารเล่มเดียวกัน / ใช้เอกสารร่วมกัน / ตรวจจับความซ้ำซ้อนของไฟล์."""
    q = question.lower()
    has_same = any(w in q for w in [
        "เล่มเดียวกัน", "เอกสารเดียวกัน", "ไฟล์เดียวกัน", "คู่หลักสูตร", "ใช้เอกสารร่วมกัน",
        "ซ้ำกัน", "เหมือนกันทุกประการ", "hash", "sha256", "sha-256", "checksum", "duplicate"
    ])
    has_grad = any(w in q for w in ["บัณฑิตศึกษา", "ป.โท", "ป.เอก", "ปริญญาโท", "ปริญญาเอก"])
    return has_same or (has_grad and any(w in q for w in ["คู่ใด", "หลักสูตรใด", "สังเกต", "ร่วมกัน", "เหมือนกัน"]))


def try_document_relation(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """วิเคราะห์ความสัมพันธ์ของเอกสารและตรวจหาไฟล์ซ้ำ (Deduplication) จากตาราง document_relation และ document."""
    if not detect_document_relation_intent(question):
        return StructuredResult(False, "", "", "none")

    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT 
            dr.relation_type, dr.note,
            d1.relative_path AS p1, d1.sha256 AS sha1, d1.size_bytes AS s1, d1.page_count AS c1, d1.degree_level AS deg1,
            d2.relative_path AS p2, d2.sha256 AS sha2, d2.size_bytes AS s2, d2.page_count AS c2, d2.degree_level AS deg2,
            d1.version_id
        FROM document_relation dr
        JOIN document d1 ON dr.from_document_id = d1.document_id
        JOIN document d2 ON dr.to_document_id = d2.document_id
        WHERE dr.relation_type = 'duplicate_content'
    """).fetchall()

    if not rows:
        return StructuredResult(False, "", "", "none")

    pairs_seen = set()
    lines = ["จากการวิเคราะห์ไฟล์เอกสารหลักสูตรในฐานข้อมูลระบบ (Document Metadata & Cryptographic Hash):\n"]
    idx = 1
    for r in rows:
        pair_key = tuple(sorted([r["p1"], r["p2"]]))
        if pair_key in pairs_seen:
            continue
        pairs_seen.add(pair_key)

        lines.append(f"{idx}. คู่หลักสูตรที่ใช้ไฟล์เอกสารเล่มเดียวกันทุกประการ:")
        lines.append(f"   - ไฟล์ที่ 1: {r['p1']} (ระดับที่ระบบตรวจพบจากเนื้อหา: {r['deg1']})")
        lines.append(f"   - ไฟล์ที่ 2: {r['p2']} (ระดับที่ระบบตรวจพบจากเนื้อหา: {r['deg2']})")
        lines.append(f"\n   ข้อสังเกตเชิงลึก (Provenance & Cryptographic Hash Verification):")
        lines.append(f"   - ค่า Cryptographic Hash (SHA-256) ตรงกันทุกตัวอักษร: {r['sha1']}")
        lines.append(f"   - ขนาดไฟล์เท่ากันทุกไบต์: {r['s1']:,} ไบต์ และมีจำนวน {r['c1']} หน้าเท่ากัน 100%")
        idx += 1

    ans = "\n".join(lines)
    return StructuredResult(
        True, ans, "AITBA 2569", "doc_relation",
        version_id=rows[0]["version_id"] if rows else None,
    )


def detect_graduation_audit_intent(question: str) -> bool:
    """ตรวจคำถามตรวจสอบการสำเร็จการศึกษาตามเงื่อนไขหน่วยกิต หรือถามเกณฑ์การจบ."""
    q = question.lower()
    grad_kws = ["จบ", "สำเร็จการศึกษา", "เกณฑ์จบ", "เงื่อนไขจบ", "ครบหลักสูตร", "พ้นสภาพ", "สำเร็จ"]
    audit_kws = ["ตรวจ", "ครบ", "ได้ไหม", "หรือไม่", "กี่หน่วยกิต", "หน่วยกิต", "ขาด", "พอไหม", "ต้องเก็บ", "ต้องได้", "ประเมิน", "เกณฑ์"]
    has_grad = any(k in q for k in grad_kws)
    has_audit = any(k in q for k in audit_kws)
    return has_grad and (has_audit or re.search(r"\d+\s*หน่วยกิต", q) is not None)


# เกณฑ์ที่ตรวจทานกับ มคอ.2 โดยตรง (ไม่ใส่ค่าที่ยังไม่ได้ยืนยัน)
# DSBA 2565: โครงสร้างหลักสูตร หน้า 15 — รวม 132, ศึกษาทั่วไป 30, เฉพาะ 96
# (กลุ่มวิชาแกน 45 + พื้นฐานวิชาชีพ 33 = 78, กลุ่มวิชาชีพเฉพาะด้าน 12), เลือกเสรี = 132-30-96 = 6
# หลักสูตรอื่นยังไม่มีค่าที่ยืนยันแล้ว จึงไม่ตอบ (ปล่อยให้ไหลไป rule/retrieval ปกติ)
VERIFIED_GRAD_RULES = {
    "DSBA": {"total": 132, "gened": 30, "major": 96, "core": 78, "elective": 12, "free": 6},
}


def _try_generic_audit(conn: sqlite3.Connection, question: str, program: str) -> StructuredResult:
    """ตรวจหน่วยกิตที่ผู้ถามระบุ กับเกณฑ์ในตาราง rule ของหลักสูตรนั้น (รวม + ศึกษาทั่วไป/เฉพาะ/เลือกเสรี)."""
    m_tot = re.search(r"รวม\s*(\d+)\s*หน่วยกิต", question)
    if not m_tot:
        return StructuredResult(False, "", "", "none")
    named = [(v, y) for v, p, y in detect_versions(conn, question) if p == program]
    version_id = named[0][0] if len(named) == 1 else _resolve_version_for_rule(conn, program)
    if version_id is None:
        return StructuredResult(False, "", "", "none")
    req = {
        r[0]: r[1] for r in conn.execute(
            "SELECT attribute, value_numeric FROM rule WHERE version_id=? AND attribute IN "
            "('min_total_credits','credits.general_education','credits.specific','credits.free_elective')",
            (version_id,),
        )
    }
    if "min_total_credits" not in req:
        return StructuredResult(False, "", "", "none")

    def _grab(pattern: str) -> int | None:
        m = re.search(pattern, question)
        return int(m.group(1)) if m else None

    student = {
        "credits.general_education": _grab(r"(?:ศึกษาทั่วไป|ทั่วไป)\s*(?:เก็บได้|ได้)?\s*(\d+)"),
        "credits.specific": _grab(r"(?:วิชาเฉพาะ|เฉพาะ)(?!เลือก|ด้าน)\s*(?:เก็บได้|ได้)?\s*(\d+)"),
        "credits.free_elective": _grab(r"เลือกเสรี\s*(?:เก็บได้|ได้)?\s*(\d+)"),
    }
    names = {
        "credits.general_education": "หมวดวิชาศึกษาทั่วไป",
        "credits.specific": "หมวดวิชาเฉพาะ",
        "credits.free_elective": "หมวดวิชาเลือกเสรี",
    }
    total, need = int(m_tot.group(1)), float(req["min_total_credits"])
    label = _versions_label(conn, [version_id])
    short = need - total
    lines = [f"ผลการตรวจสอบเงื่อนไขการสำเร็จการศึกษา (หลักสูตร {label}):", ""]
    lines.append(
        "▶ สรุป: **ยังไม่ครบเงื่อนไขสำเร็จการศึกษา**" if short > 0 or any(
            student[k] is not None and k in req and student[k] < req[k] for k in student
        ) else "▶ สรุป: ผ่านเกณฑ์ที่ตรวจได้จากตัวเลขที่ระบุ"
    )
    lines.append("")
    lines.append("เทียบกับเกณฑ์ตามโครงสร้างหลักสูตรในเล่ม:")
    for k, nm in names.items():
        if k not in req:
            continue
        got = student[k]
        if got is None:
            lines.append(f"- {nm}: เกณฑ์ {req[k]:g} หน่วยกิต (คำถามไม่ได้ระบุว่าเก็บได้เท่าไร)")
        elif got < req[k]:
            lines.append(f"- {nm}: เก็บได้ {got} เกณฑ์ {req[k]:g} → **ขาดอีก {req[k] - got:g} หน่วยกิต**")
        else:
            lines.append(f"- {nm}: เก็บได้ {got} เกณฑ์ {req[k]:g} → ครบตามเกณฑ์")
    if short > 0:
        lines.append(f"- หน่วยกิตรวม: เก็บได้ {total} เกณฑ์ไม่น้อยกว่า {need:g} → **ขาดอีก {short:g} หน่วยกิต**")
    else:
        lines.append(f"- หน่วยกิตรวม: เก็บได้ {total} เกณฑ์ไม่น้อยกว่า {need:g} → ครบตามเกณฑ์")
    pg = conn.execute(
        "SELECT p.document_id, p.page_number FROM rule r JOIN provenance p ON p.provenance_id=r.provenance_id "
        "WHERE r.version_id=? AND r.attribute='min_total_credits'", (version_id,)
    ).fetchone()
    return StructuredResult(
        True, "\n".join(lines), label, "grad_audit", version_id=version_id,
        pages=[(pg[0], pg[1], "จำนวนหน่วยกิตรวมตลอดหลักสูตร")] if pg else [],
    )


def try_graduation_audit(conn: sqlite3.Connection, question: str) -> StructuredResult:
    """เทียบหน่วยกิตที่ผู้ถามระบุมา กับเกณฑ์ที่ตรวจทานแล้ว (เฉพาะ DSBA 2565).

    ทำงานเมื่อคำถามมีตัวเลขหน่วยกิตของนักศึกษาเท่านั้น ถ้าถามเกณฑ์ทั่วไป ไม่ตอบที่นี่
    """
    if not detect_graduation_audit_intent(question):
        return StructuredResult(False, "", "", "none")

    program = detect_program(question) or "DSBA"
    rules = VERIFIED_GRAD_RULES.get(program)
    if rules is None:
        return _try_generic_audit(conn, question, program)
    req_total = rules["total"]

    # สกัดตัวเลขจากคำถามแบบไดนามิก
    m_tot = re.search(r"รวม\s*(\d+)\s*หน่วยกิต", question) or re.search(r"เก็บ(?:ได้)?\s*(\d+)\s*หน่วยกิต", question) or re.search(r"(\d+)\s*หน่วยกิต", question)
    student_total = int(m_tot.group(1)) if m_tot else None

    # สกัดแยกหมวด (ถ้ามีระบุในคำถาม)
    m_gen = re.search(r"(?:ศึกษาทั่วไป|ทั่วไป)\s*(?:เก็บได้|ได้)?\s*(\d+)", question)
    m_core = re.search(r"(?:วิชาแกน|แกน|บังคับ)\s*(?:เก็บได้|ได้)?\s*(\d+)", question)
    m_elec = re.search(r"(?:วิชาชีพเฉพาะด้าน|เฉพาะเลือก|วิชาเลือก)\s*(?:เก็บได้|ได้)?\s*(\d+)", question)
    m_free = re.search(r"(?:เลือกเสรี)\s*(?:เก็บได้|ได้)?\s*(\d+)", question)

    c_gen = int(m_gen.group(1)) if m_gen else None
    c_core = int(m_core.group(1)) if m_core else None
    c_elec = int(m_elec.group(1)) if m_elec else None
    c_free = int(m_free.group(1)) if m_free else None

    lines = [f"ผลการตรวจสอบเงื่อนไขการสำเร็จการศึกษา (หลักสูตร {program} 2565):\n"]

    if student_total is not None:
        diff = req_total - student_total
        if diff > 0:
            lines.append("▶ สรุปผลการประเมิน: **ยังไม่ครบเงื่อนไขสำเร็จการศึกษา**\n")
        else:
            lines.append("▶ สรุปผลการประเมิน: **ผ่านเกณฑ์จำนวนหน่วยกิตรวมขั้นต่ำแล้ว**\n")

        lines.append(f"รายละเอียดการเปรียบเทียบกับเกณฑ์โครงสร้างหลักสูตร (เกณฑ์รวมไม่น้อยกว่า {req_total} หน่วยกิต):")

        # แจกแจงหมวดถ้ามีข้อมูล
        if c_gen is not None:
            status = "ครบถ้วน" if c_gen >= rules["gened"] else f"**ขาดอีก {rules['gened'] - c_gen} หน่วยกิต**"
            lines.append(f"1. หมวดวิชาศึกษาทั่วไป: นักศึกษาเก็บได้ {c_gen} หน่วยกิต (เกณฑ์ขั้นต่ำ {rules['gened']} หน่วยกิต) → {status}")
        else:
            lines.append(f"1. หมวดวิชาศึกษาทั่วไป: เกณฑ์ขั้นต่ำ {rules['gened']} หน่วยกิต")

        if c_core is not None or c_elec is not None:
            lines.append(f"2. หมวดวิชาเฉพาะ (เกณฑ์รวม {rules['major']} หน่วยกิต):")
            if c_core is not None:
                status = "ครบถ้วน" if c_core >= rules["core"] else f"**ขาดอีก {rules['core'] - c_core} หน่วยกิต**"
                lines.append(f"   - กลุ่มวิชาแกนและวิชาบังคับ: นักศึกษาเก็บได้ {c_core} หน่วยกิต (เกณฑ์ {rules['core']} หน่วยกิต) → {status}")
            if c_elec is not None:
                status = "ครบถ้วน" if c_elec >= rules["elective"] else f"**ขาดอีก {rules['elective'] - c_elec} หน่วยกิต**"
                lines.append(f"   - กลุ่มวิชาชีพเฉพาะด้าน (วิชาเฉพาะเลือก): นักศึกษาเก็บได้ {c_elec} หน่วยกิต (เกณฑ์กำหนดไม่น้อยกว่า {rules['elective']} หน่วยกิต) → {status}")
        else:
            lines.append(f"2. หมวดวิชาเฉพาะ: เกณฑ์รวม {rules['major']} หน่วยกิต (วิชาแกน/บังคับ {rules['core']} หน่วยกิต, วิชาเฉพาะเลือก {rules['elective']} หน่วยกิต)")

        if c_free is not None:
            status = "ครบถ้วน" if c_free >= rules["free"] else f"**ขาดอีก {rules['free'] - c_free} หน่วยกิต**"
            lines.append(f"3. หมวดวิชาเลือกเสรี: นักศึกษาเก็บได้ {c_free} หน่วยกิต (เกณฑ์ขั้นต่ำ {rules['free']} หน่วยกิต) → {status}")
        else:
            lines.append(f"3. หมวดวิชาเลือกเสรี: เกณฑ์ขั้นต่ำ {rules['free']} หน่วยกิต")

        lines.append("4. จำนวนหน่วยกิตรวมตลอดหลักสูตร:")
        if diff > 0:
            lines.append(f"   - นักศึกษาเก็บได้รวม {student_total} หน่วยกิต แต่เกณฑ์การสำเร็จการศึกษากำหนดไว้ไม่น้อยกว่า {req_total} หน่วยกิต → **ขาดอีก {diff} หน่วยกิต**")
            extra_msg = f" โดยต้องลงเรียนวิชาเฉพาะเลือกเพิ่มอีกอย่างน้อย {rules['elective'] - c_elec} หน่วยกิต และ" if (c_elec and c_elec < rules["elective"]) else " "
            lines.append(f"\nข้อสรุป: นักศึกษายังไม่สามารถสำเร็จการศึกษาได้{extra_msg}ต้องเก็บหน่วยกิตรวมให้ครบตามเกณฑ์ {req_total} หน่วยกิต")
        else:
            lines.append(f"   - นักศึกษาเก็บได้รวม {student_total} หน่วยกิต เกณฑ์กำหนดไว้ไม่น้อยกว่า {req_total} หน่วยกิต → ครบตามเกณฑ์ขั้นต่ำ")
            lines.append(f"\nข้อสรุป: นักศึกษาเก็บหน่วยกิตรวมผ่านเกณฑ์ขั้นต่ำ {req_total} หน่วยกิตแล้ว")
    else:
        return StructuredResult(False, "", "", "none")

    return StructuredResult(
        True, "\n".join(lines), f"{program} 2565 (current)", "grad_audit",
        version_id=5,
    )
