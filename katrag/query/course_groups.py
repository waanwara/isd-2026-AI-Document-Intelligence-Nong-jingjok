"""กลุ่มวิชา/แขนงของแต่ละรายวิชา อ่านจากหัวข้อรายวิชา (3.1.3) ในเล่ม มคอ.2.

ตาราง `course` เก็บแค่หมวดใหญ่ (หมวดวิชาเฉพาะ / ศึกษาทั่วไป / เลือกเสรี) ไม่รู้ว่าวิชาเลือก
อยู่กลุ่มไหน เช่น DSBA 2565 มีกลุ่มวิชาชีพเฉพาะด้าน 3 กลุ่ม (วิทยาการข้อมูล / การวิเคราะห์เชิงสถิติ /
วิศวกรรมข้อมูล) และนักศึกษาเลือกเรียนกลุ่มเดียว คำถามอย่าง "แขนงวิศวกรรมข้อมูลเรียนวิชาอะไร" หรือ
"วิชา Intelligent System Development เรียนตอนไหน" จึงตอบไม่ได้

ในเล่ม รายวิชาถูกเรียงใต้หัวข้อกลุ่ม เช่น "- กลุ่มวิศวกรรมข้อมูล 12 หน่วยกิต" ตามด้วยตาราง
รหัสวิชา โมดูลนี้จับหัวข้อกลุ่มที่มีจำนวนหน่วยกิตต่อท้าย แล้วให้รหัสวิชาแต่ละตัวสังกัดหัวข้อที่อยู่ก่อนหน้าใกล้สุด
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

# "3) กลุ่มวิชาชีพเฉพาะด้าน 12 หน่วยกิต" (ระดับ 1) / "- กลุ่มวิศวกรรมข้อมูล 12 หน่วยกิต" (ระดับ 2)
_HEADER_RE = re.compile(
    r"(?P<mark>\d\)|[-–])\s*(?P<label>(?:กลุ่ม|สหกิจ|วิชาสหกิจ)[ก-๙A-Za-z\s()/]{2,70}?)\s*[|\s]*(?P<credits>\d{1,3})\s*(?:\*\s*)?[|\s]*หน่วยกิต"
)
# หัวตารางย่อยที่ไม่มีหน่วยกิต เช่น IT 2565 "กลุ่มวิชาด้านการพัฒนาซอฟต์แวร์ | รหัสวิชา ..." (โมดูลวิชาสาขา)
_SUBTABLE_RE = re.compile(r"(?:(?<=\n)|(?<=\|)|^)[ \t]*(?P<label>(?:กลุ่ม|สหกิจ|วิชาสหกิจ)[ก-๙A-Za-z\s,()]{2,90}?)\s*[|\s]*รหัสวิชา")
_CODE_RE = re.compile(r"(?<![0-9A-Za-z])(\d{8})(?![0-9A-Za-z])")
_SECTION_START = re.compile(r"3\.[12]\.3\s|รายวิชา\s*\n?\s*ก\.\s*หมวดวิชาศึกษาทั่วไป|3\.2\s*รายวิชา")
_SECTION_END = re.compile(r"3\.1\.4\.1|แผนการศึกษาที่ไม่เข้าโครงการสหกิจศึกษา\s*\n|3\.1\.4\s*แผนการศึกษา")


@dataclass(frozen=True)
class Group:
    label: str          # ชื่อกลุ่มตามเล่ม เช่น "กลุ่มวิศวกรรมข้อมูล"
    parent: str         # กลุ่มระดับบน เช่น "กลุ่มวิชาชีพเฉพาะด้าน" ("" ถ้าไม่มี)
    credits: int
    page: int


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _last_label(raw: str) -> str:
    """หัวตารางย่อยมักติดประโยคก่อนหน้ามา (เช่น '...ตามกลุ่มวิชาพื้นฐานที่สนใจ | กลุ่มวิชาด้าน...')
    ใช้บรรทัดสุดท้ายที่ขึ้นต้นด้วยคำว่า กลุ่ม/สหกิจ."""
    parts = [p.strip() for p in re.split(r"[\n|]", raw) if p.strip()]
    for p in reversed(parts):
        if p.startswith(("กลุ่ม", "สหกิจ", "วิชาสหกิจ")):
            return _clean(p)
    return _clean(raw)


@lru_cache(maxsize=32)
def _groups_cached(db_file: str, version_id: int) -> tuple[tuple[str, tuple[Group, ...]], ...]:
    conn = sqlite3.connect(db_file)
    try:
        return tuple((k, tuple(v)) for k, v in _parse(conn, version_id).items())
    finally:
        conn.close()


def course_groups(conn: sqlite3.Connection, version_id: int) -> dict[str, list[Group]]:
    """{รหัสวิชา: [กลุ่ม, ...]} — วิชาเดียวอยู่ได้หลายกลุ่ม (เช่น IT 06016418 อยู่ทั้งโมดูลซอฟต์แวร์และสื่อประสม)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if row and row[2]:
        return {k: list(v) for k, v in _groups_cached(row[2], version_id)}
    return _parse(conn, version_id)


def _parse(conn: sqlite3.Connection, version_id: int) -> dict[str, list[Group]]:
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (version_id,)
    ).fetchone()
    if not doc:
        return {}
    pages = conn.execute(
        "SELECT page_number, page_text FROM page WHERE document_id=? AND page_number BETWEEN 10 AND 70 "
        "ORDER BY page_number", (doc[0],)
    ).fetchall()
    started = False
    ended = False
    out: dict[str, list[Group]] = {}
    level1: tuple[str, int, int] | None = None   # (label, credits, page)
    current: Group | None = None
    for page_no, text in pages:
        if not started:
            m = _SECTION_START.search(text)
            if not m:
                continue
            started = True
            text = text[m.start():]
        end = _SECTION_END.search(text)
        seg = text[: end.start()] if end else text
        events: list[tuple[int, str, re.Match]] = [(m.start(), "h", m) for m in _HEADER_RE.finditer(seg)]
        head_spans = [(m.start(), m.end()) for m in _HEADER_RE.finditer(seg)]
        events += [
            (m.start(), "s", m) for m in _SUBTABLE_RE.finditer(seg)
            if not any(a <= m.start() < b for a, b in head_spans)
        ]
        events += [(m.start(), "c", m) for m in _CODE_RE.finditer(seg)]
        events.sort(key=lambda e: e[0])
        for _pos, kind, m in events:
            if kind == "h":
                label = _clean(m.group("label"))
                credits = int(m.group("credits"))
                if m.group("mark").endswith(")"):
                    level1 = (label, credits, page_no)
                    current = Group(label, "", credits, page_no)
                else:
                    current = Group(label, level1[0] if level1 else "", credits, page_no)
                continue
            if kind == "s":
                label = _last_label(m.group("label"))
                parent = level1[0] if level1 else ""
                if label != parent:
                    current = Group(label, parent, 0, page_no)
                continue
            code = m.group(1)
            if current is not None and current not in out.setdefault(code, []):
                out[code].append(current)
        if end:
            ended = True
            break
    # ไม่เจอจุดจบของหัวข้อรายวิชา (เช่น เล่ม AIT ไม่มีหัวข้อ 3.1.4.1) = อ่านเลยไปถึงหน้าแผน/คำอธิบายรายวิชา
    # ซึ่งทำให้วิชาบังคับถูกนับเป็นวิชาเลือก จึงไม่ใช้ผลของเล่มนั้นเลย ดีกว่าให้ข้อมูลกลุ่มผิด
    return out if ended else {}


def all_groups(groups: dict[str, list[Group]]) -> list[Group]:
    seen: list[Group] = []
    for gs in groups.values():
        for g in gs:
            if g not in seen:
                seen.append(g)
    return seen


def group_members(groups: dict[str, list[Group]], group: Group) -> list[str]:
    return [code for code, gs in groups.items() if group in gs]


# ══════════════════════════════════════════════════════════════════════
# คำตอบ: "วิชา X เรียนตอนไหน" และ "แขนง/กลุ่ม Y มีวิชาอะไร"
# ══════════════════════════════════════════════════════════════════════

_LOOKUP_KW = (
    "เรียนตอนไหน", "เรียนปีไหน", "เรียนเทอมไหน", "เรียนภาคไหน", "ปีไหน", "เทอมไหน", "ภาคไหน", "ตอนไหน",
    "ปีอะไร", "เทอมอะไร", "ภาคอะไร", "กลุ่มไหน", "แขนงไหน", "อยู่แขนง", "อยู่กลุ่ม", "กี่หน่วยกิต",
    "รหัสวิชาอะไร", "รหัสอะไร", "ลงตอนไหน", "ลงได้ตอนไหน", "ลงปีไหน",
)
_TRACK_WORDS = ("แขนง", "กลุ่ม", "โมดูล")
_TRACK_ASK = ("วิชาอะไร", "มีวิชา", "เรียนอะไร", "ต้องเรียน", "กี่วิชา", "รายวิชา", "มีอะไรบ้าง", "เรียนวิชา")
_GENERIC_TOKENS = {"กลุ่ม", "วิชา", "ด้าน", "การ", "สำหรับ", "และ", "พัฒนา", "การพัฒนา", "เชิง", "ทาง", "ของ"}
_CHOOSE_ONE_PARENTS = ("วิชาชีพเฉพาะด้าน", "บังคับเฉพาะสาขา")


def _core(label: str) -> str:
    return re.sub(r"^(?:กลุ่มวิชาด้าน|กลุ่มวิชา|กลุ่ม|วิชา)", "", label).strip()


def _tokens(text: str) -> list[str]:
    try:
        from pythainlp.tokenize import word_tokenize

        toks = word_tokenize(text, engine="newmm")
    except Exception:  # pragma: no cover
        toks = text.split()
    return [t for t in (x.strip() for x in toks) if len(t) >= 3 and t not in _GENERIC_TOKENS]


def detect_course_lookup_intent(question: str) -> bool:
    from katrag.query.structured_query import detect_dependents_intent, detect_prerequisite_intent

    if detect_prerequisite_intent(question) or detect_dependents_intent(question):
        return False
    return any(k in question for k in _LOOKUP_KW)


def detect_track_intent(question: str) -> bool:
    return any(w in question for w in _TRACK_WORDS) and any(a in question for a in _TRACK_ASK)


def _placements(conn: sqlite3.Connection, version_id: int, code: str) -> list[tuple[str, int, int, list[int]]]:
    from katrag.query.plan_variants import block_courses, plan_blocks

    out = []
    for b in plan_blocks(conn, version_id):
        if any(c == code for c, _t, _c in block_courses(conn, version_id, b)):
            out.append((b.variant, b.year, b.semester, b.pages))
    return out


def _slot_placements(conn: sqlite3.Connection, version_id: int, groups: list[Group]) -> list[tuple[str, int, int, str, list[int]]]:
    """ช่องวิชาเลือกในแผนที่รับวิชาของกลุ่มเหล่านี้ (ชื่อช่องมีชื่อกลุ่มหรือกลุ่มแม่)."""
    from katrag.query.plan_variants import block_slots, plan_blocks

    cores = {_core(g.label) for g in groups} | {_core(g.parent) for g in groups if g.parent}
    cores = {c for c in cores if len(c) >= 4}
    out = []
    for b in plan_blocks(conn, version_id):
        for lab in block_slots(b)[1:]:
            if any(c in lab for c in cores):
                out.append((b.variant, b.year, b.semester, lab, b.pages))
    return out


_CREDIT_PAT = re.compile(r"\d{1,2}\s*\(\d{1,2}-\d{1,2}-\d{1,2}\)")


def _name_from_pages(conn: sqlite3.Connection, version_id: int, code: str, page: int) -> tuple[str, str, str]:
    """ชื่อ/หน่วยกิตของวิชาที่ไม่อยู่ในตาราง course อ่านจากข้อความหน้ารายวิชา (หน้านั้นและหน้าถัดไป)."""
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (version_id,)
    ).fetchone()
    if not doc:
        return "", "", ""
    for pg in (page, page + 1):
        t = conn.execute("SELECT page_text FROM page WHERE document_id=? AND page_number=?", (doc[0], pg)).fetchone()
        if not t or code not in t[0]:
            continue
        seg = t[0][t[0].index(code) + len(code):]
        cm = _CREDIT_PAT.search(seg)
        seg = seg[: cm.start()] if cm else seg[:200]
        th = _clean(" ".join(re.findall(r"[ก-๙][ก-๙\s]*", seg)))
        en = _clean(" ".join(re.findall(r"[A-Z][A-Z\s\-]{3,}", seg)))
        return th, en, cm.group(0) if cm else ""
    return "", "", ""


def _variant_name(v: str) -> str:
    return "แผนปกติ" if v == "default" else "แผนสหกิจ"


def _fmt_places(places: list[tuple[str, int, int, list[int]]]) -> list[str]:
    by_slot: dict[tuple[int, int], list[str]] = {}
    pages: dict[tuple[int, int], list[int]] = {}
    for v, y, s, pg in places:
        by_slot.setdefault((y, s), []).append(_variant_name(v))
        pages.setdefault((y, s), []).extend(pg)
    lines = []
    for (y, s), vs in sorted(by_slot.items()):
        which = "ทั้งแผนปกติและแผนสหกิจ" if len(set(vs)) == 2 else vs[0]
        lines.append(f"  - ปีที่ {y} ภาคการศึกษาที่ {s} ({which}, หน้า {', '.join(map(str, sorted(set(pages[(y, s)]))))})")
    return lines


def _dedupe(items: list) -> list:
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def try_course_lookup(conn: sqlite3.Connection, question: str):
    """วิชานี้เรียนปี/ภาคไหน หน่วยกิตเท่าไร อยู่กลุ่มไหน — จากตารางแผนและหัวข้อรายวิชาในเล่ม."""
    import json

    from katrag.query.structured_query import (
        _EN_STOP, StructuredResult, _course_scope_versions, _match_course_by_name, _stem_eq, _versions_label,
        detect_program,
    )

    none = StructuredResult(False, "", "", "none")
    conn.row_factory = sqlite3.Row
    program = detect_program(question)
    if not program:
        return none
    q = re.sub(r"หลักสูตร\s+[A-Za-z]+\s*[:：]", " ", question)
    q = re.sub(rf"(?i)\b{re.escape(program)}\b", " ", q)
    q = re.sub(r"\(เอกสารอาจใช้คำ:[^)]*\)", " ", q)
    version_ids = _course_scope_versions(conn, question, program)
    rows = _match_course_by_name(conn, q, version_ids)
    en_words = [w for w in re.findall(r"[A-Za-z]{3,}", q) if w.lower() not in _EN_STOP]
    if not rows and en_words and version_ids:
        ph = ",".join("?" for _ in version_ids)
        strict = [
            c for c in conn.execute(
                f"SELECT code, name_th, name_en, credits_raw, version_id FROM course WHERE version_id IN ({ph})",
                version_ids,
            ).fetchall()
            if all(
                any(_stem_eq(w, x) for x in re.findall(r"[a-z]{3,}", (c["name_en"] or "").lower()))
                for w in en_words
            )
        ]
        if not strict:
            return StructuredResult(
                True,
                f"ไม่พบวิชาชื่อ \"{' '.join(en_words)}\" ในหลักสูตร {_versions_label(conn, version_ids)}\n"
                "ลองตรวจชื่อวิชา หรือระบุรหัสวิชา 8 หลัก",
                "", "course_lookup", version_id=version_ids[0],
            )
        strict.sort(key=lambda c: len(c["name_en"] or ""))
        rows = strict[:1]
    if not rows:
        return none

    vid, code = rows[0]["version_id"], rows[0]["code"]
    full = conn.execute(
        "SELECT code, name_th, name_en, credits_raw, year, semester, prerequisite_json FROM course "
        "WHERE version_id=? AND code=?", (vid, code),
    ).fetchone()
    label = _versions_label(conn, [vid])
    en = f" ({full['name_en']})" if full["name_en"] else ""
    lines = [f"วิชา {code} {full['name_th']}{en} — {full['credits_raw']} หน่วยกิต · หลักสูตร {label}"]
    groups = course_groups(conn, vid).get(code, [])
    for g in groups:
        parent = f" (ส่วนของ{g.parent})" if g.parent else ""
        choose = " — ต้องเลือกเรียนกลุ่มใดกลุ่มหนึ่ง" if any(p in g.parent for p in _CHOOSE_ONE_PARENTS) else ""
        lines.append(f"อยู่ใน{g.label}{parent}{choose} (หน้า {g.page})")

    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (vid,)
    ).fetchone()
    pages: list[tuple[str, int, str]] = []
    places = _placements(conn, vid, code)
    if places:
        lines.append("เรียนตามแผนการศึกษา:")
        lines += _fmt_places(places)
        if doc:
            pages += [(doc[0], p, "ตารางแผนการศึกษา") for _v, _y, _s, pg in places for p in pg]
    else:
        slots = _dedupe([(v, y, s, lab, tuple(pg)) for v, y, s, lab, pg in _slot_placements(conn, vid, groups)])
        if slots:
            lines.append("ไม่ได้กำหนดปี/ภาคตายตัวในแผนการศึกษา (เป็นวิชาเลือกของกลุ่ม) ลงเรียนได้ในช่องวิชาเลือกตามแผน:")
            for v, y, s, lab, pg in slots:
                lines.append(f"  - {_variant_name(v)} ปีที่ {y} ภาคการศึกษาที่ {s}: ช่อง \"{lab}\" (หน้า {', '.join(map(str, pg))})")
                if doc:
                    pages += [(doc[0], p, "ตารางแผนการศึกษา") for p in pg]
        elif full["year"]:
            lines.append(f"ตามตารางรายวิชา: ปีที่ {full['year']} ภาคการศึกษาที่ {full['semester']}")
        else:
            lines.append("ไม่ได้กำหนดปี/ภาคไว้ในแผนการศึกษาของเล่ม (เป็นวิชาเลือก)")

    pre = json.loads(full["prerequisite_json"] or "[]")
    if pre:
        names = []
        for pc in pre:
            pr = conn.execute("SELECT name_th FROM course WHERE version_id=? AND code=?", (vid, pc)).fetchone()
            names.append(f"{pc} {pr[0] if pr else ''}".strip())
        lines.append("วิชาบังคับก่อน: " + ", ".join(names))
    else:
        lines.append("วิชาบังคับก่อน: ไม่มี")
    if doc and groups:
        pages = [(doc[0], g.page, "รายวิชาในกลุ่ม") for g in groups] + pages
    return StructuredResult(
        True, "\n".join(lines), label, "course_lookup", codes=[code], version_id=vid, pages=_dedupe(pages)[:8],
    )


def try_track(conn: sqlite3.Connection, question: str):
    """แขนง/กลุ่มวิชาที่ถาม มีวิชาอะไรบ้าง ต้องเรียนกี่หน่วยกิต และลงตอนไหนตามแผน."""
    from katrag.query.structured_query import (
        StructuredResult, _course_scope_versions, _versions_label, detect_program, detect_year,
    )

    none = StructuredResult(False, "", "", "none")
    program = detect_program(question)
    if not program:
        return none
    q = re.sub(r"\(เอกสารอาจใช้คำ:[^)]*\)", " ", question)
    vids = _course_scope_versions(conn, question, program)
    if not vids:
        return none
    vid = vids[0]
    groups = course_groups(conn, vid)
    scored = []
    for g in all_groups(groups):
        if not g.parent:
            continue
        core = _core(g.label)
        score = 3 if core and core in q else sum(1 for t in _tokens(core) if t in q)
        # "แขนง/โมดูล" หมายถึงกลุ่มที่ต้องเลือกเรียนกลุ่มเดียว ไม่ใช่กลุ่มวิชาบังคับทั่วไป
        if score and any(w in q for w in ("แขนง", "โมดูล")) and any(p in g.parent for p in _CHOOSE_ONE_PARENTS):
            score += 1
        if score:
            scored.append((score, g))
    if not scored:
        return none
    best = max(s for s, _ in scored)
    chosen = [g for s, g in scored if s == best]
    year = detect_year(q)
    label = _versions_label(conn, [vid])
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (vid,)
    ).fetchone()
    lines: list[str] = []
    pages: list[tuple[str, int, str]] = []
    codes: list[str] = []
    for g in chosen:
        members = group_members(groups, g)
        lines.append(f"{g.label} (ส่วนของ{g.parent}) — {label}")
        notes = []
        if g.credits:
            notes.append(f"เรียนจากกลุ่มนี้ {g.credits} หน่วยกิต")
        if any(p in g.parent for p in _CHOOSE_ONE_PARENTS):
            notes.append("ต้องเลือกเรียนกลุ่มใดกลุ่มหนึ่ง")
        notes.append(f"รายวิชาในเล่มหน้า {g.page}")
        lines.append("  " + " · ".join(notes))
        lines.append(f"  รายวิชาในกลุ่ม ({len(members)} วิชา):")
        for code in members:
            r = conn.execute(
                "SELECT name_th, name_en, credits_raw FROM course WHERE version_id=? AND code=?", (vid, code)
            ).fetchone()
            places = _placements(conn, vid, code)
            if year is not None:
                places = [p for p in places if p[1] == year]
            where = " | " + "; ".join(sorted({f"ปี {y} ภาค {s}" for _v, y, s, _p in places})) if places else ""
            name = (r[0], r[1], r[2]) if r and r[0] else _name_from_pages(conn, vid, code, g.page)
            en = f" ({name[1]})" if name[1] else ""
            cr = f" — {name[2]}" if name[2] else ""
            lines.append(f"    - {code} {name[0]}{en}{cr}{where}".rstrip())
            codes.append(code)
        slots = _dedupe([(v, y, s, lab, tuple(pg)) for v, y, s, lab, pg in _slot_placements(conn, vid, [g])])
        if year is not None:
            slots = [x for x in slots if x[1] == year]
        if slots:
            lines.append("  ลงในช่องวิชาเลือกตามแผน:")
            for v, y, s, lab, pg in slots:
                lines.append(f"    • {_variant_name(v)} ปีที่ {y} ภาคการศึกษาที่ {s}: \"{lab}\" (หน้า {', '.join(map(str, pg))})")
                if doc:
                    pages += [(doc[0], p, "ตารางแผนการศึกษา") for p in pg]
        if doc:
            pages.insert(0, (doc[0], g.page, "รายวิชาในกลุ่ม"))
        lines.append("")
    return StructuredResult(
        True, "\n".join(lines).strip(), label, "track", version_id=vid, pages=_dedupe(pages)[:8],
    )
