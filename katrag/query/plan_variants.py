"""แผนการศึกษาแยกตามประเภทแผน (แผนปกติ / แผนที่เข้าโครงการสหกิจศึกษา).

เล่ม มคอ.2 ของ DSBA, BIT, IT มีตารางแผนสองชุดคือ 3.1.4.1 แผนที่ไม่เข้าโครงการสหกิจศึกษา
และ 3.1.4.2 แผนที่เข้าโครงการสหกิจศึกษา แต่ตาราง `course` เก็บปี/ภาคได้ชุดเดียว (ชุดแรกที่พบ)
จึงตอบคำถามเรื่องแผนสหกิจไม่ได้ (เช่น วิชาสหกิจอยู่ปีไหน ภาคไหน ต่างจากแผนปกติตรงไหน)

โมดูลนี้อ่านตารางแผนจาก `page.page_text` ตรง ๆ แยกตามหัวข้อ 3.1.4.1 / 3.1.4.2 แล้วแบ่งเป็นบล็อก
ต่อภาคตามหัว "ปีที่ X ภาคการศึกษาที่ Y" เก็บ หน่วยกิตรวมของภาค (บรรทัด 'รวม N'), รายวิชา, ช่องวิชาเลือก
(รหัสที่มี x เช่น 06026xxx) และเลขหน้า ผลรวมทุกภาคของแต่ละแผนต้องเท่ากับหน่วยกิตรวมของหลักสูตร
ถ้าไม่เท่าจะแจ้งไว้ในคำตอบ ไม่ปิดบัง
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache

_YS_RE = re.compile(r"ปีที่\s*([1-4])\s*ภาค(?:การศึกษา|เรียน)ที่\s*([1-3])")
_TOT_RE = re.compile(r"(?<![ก-๙])รวม\s*\|?\s*(\d{1,2})(?![\d.])")
_H_DEFAULT = re.compile(r"3\.1\.4\.1")
_H_COOP = re.compile(r"3\.1\.4\.2")
_CODE_RE = re.compile(r"(?<![0-9A-Za-z])(\d{8})(?![0-9A-Za-z])")
_SLOT_RE = re.compile(r"(?<![0-9A-Za-z])(?=[0-9x]*x)([0-9x]{8})(?![0-9A-Za-z])")
_CREDIT_RE = re.compile(r"(\d{1,2})\s*\(\d{1,2}-\d{1,2}-\d{1,2}\)")

# หัวกระดาษที่ซ้ำทุกหน้า ("38 มคอ.2 วท.บ.(...) ... สจล.") ไม่ใช่เนื้อตาราง
_RUNNING_HEADER_RE = re.compile(r"^\s*\d*\s*มคอ\.?\s*2.*?สจล\.?\s*", re.DOTALL)

VARIANT_LABEL = {"default": "แผนปกติ (ไม่เข้าโครงการสหกิจศึกษา)", "coop": "แผนที่เข้าโครงการสหกิจศึกษา"}


@dataclass
class Block:
    variant: str
    year: int
    semester: int
    page: int
    document_id: str
    text: str
    total: int | None = None
    pages: list[int] = field(default_factory=list)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=32)
def _blocks_cached(db_key: str, version_id: int) -> tuple[Block, ...]:
    conn = sqlite3.connect(db_key)
    try:
        return tuple(_parse_blocks(conn, version_id))
    finally:
        conn.close()


def plan_blocks(conn: sqlite3.Connection, version_id: int) -> list[Block]:
    """บล็อกแผนทุกภาคของเวอร์ชันนี้ (ผลถูกแคชตามไฟล์ฐานข้อมูล)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    db_file = row[2] if row else ""
    if db_file:
        return list(_blocks_cached(db_file, version_id))
    return _parse_blocks(conn, version_id)


def _parse_blocks(conn: sqlite3.Connection, version_id: int) -> list[Block]:
    doc = conn.execute(
        "SELECT document_id FROM document WHERE version_id=? AND degree_level='bachelor'", (version_id,)
    ).fetchone()
    if not doc:
        return []
    doc_id = doc[0]
    blocks: list[Block] = []
    variant: str | None = None
    for page_no, text in conn.execute(
        "SELECT page_number, page_text FROM page WHERE document_id=? AND page_number BETWEEN 15 AND 60 "
        "ORDER BY page_number", (doc_id,)
    ):
        events: list[tuple[int, str, re.Match | None]] = []
        events += [(m.start(), "default", m) for m in _H_DEFAULT.finditer(text)]
        events += [(m.start(), "coop", m) for m in _H_COOP.finditer(text)]
        events += [(m.start(), "ys", m) for m in _YS_RE.finditer(text)]
        events.sort(key=lambda e: e[0])

        # ตารางของภาคก่อนหน้าล้นมาหน้านี้ (ส่วนก่อนหัวแรกของหน้า) ใช้ได้เมื่อภาคนั้นยังไม่เจอแถว 'รวม'
        if blocks and blocks[-1].total is None and page_no - blocks[-1].pages[-1] == 1:
            pre = text[: events[0][0]] if events else text
            pre = _RUNNING_HEADER_RE.sub("", pre, count=1)
            m = _TOT_RE.search(pre)
            blocks[-1].text += "\n" + pre
            blocks[-1].pages.append(page_no)
            if m:
                blocks[-1].total = int(m.group(1))
            if not events:
                continue

        for i, (pos, kind, m) in enumerate(events):
            if kind in ("default", "coop"):
                variant = kind
                continue
            if variant is None:
                continue
            end = len(text)
            for pos2, _k, _m in events[i + 1:]:
                end = pos2
                break
            seg = text[m.end(): end]
            tot = _TOT_RE.search(seg)
            blocks.append(Block(
                variant=variant, year=int(m.group(1)), semester=int(m.group(2)), page=page_no,
                document_id=doc_id, text=seg, total=int(tot.group(1)) if tot else None, pages=[page_no],
            ))
    return blocks


def _course_name(conn: sqlite3.Connection, version_id: int, code: str) -> tuple[str, str, str]:
    r = conn.execute(
        "SELECT name_th, name_en, credits_raw FROM course WHERE version_id=? AND code=? LIMIT 1", (version_id, code)
    ).fetchone()
    return (r[0] or "", r[1] or "", r[2] or "") if r else ("", "", "")


def block_courses(conn: sqlite3.Connection, version_id: int, b: Block) -> list[tuple[str, str, str]]:
    """รายวิชาที่มีรหัสจริงในบล็อก: (รหัส, ชื่อ, หน่วยกิต) — ชื่อที่ไม่อยู่ในตาราง course อ่านจากข้อความในแผน."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    codes = [(m.group(1), m.start(), m.end()) for m in _CODE_RE.finditer(b.text)]
    prev_has_or = False
    for i, (code, s, e) in enumerate(codes):
        if code in seen:
            continue
        seen.add(code)
        th, en, cr = _course_name(conn, version_id, code)
        has_or = False
        if not th:
            nxt = codes[i + 1][1] if i + 1 < len(codes) else len(b.text)
            raw = b.text[e:nxt]
            raw = re.split(r"รวม\s*\|?\s*\d", raw)[0]
            has_or = "หรือ" in raw
            cm = _CREDIT_RE.search(raw)
            thai = re.findall(r"[ก-๙][ก-๙\s]*", raw)
            th = _clean(" ".join(thai))
            th = re.sub(r"(?:^|\s)หรือ(?:\s|$)", " ", th).strip()
            cr = cm.group(0) if cm else ""
        # รายวิชาที่เลือกอย่างใดอย่างหนึ่ง (แถว 'หรือ') ใช้หน่วยกิตของแถวบนร่วมกัน
        if not cr and prev_has_or and out:
            cr = out[-1][2]
        prev_has_or = has_or
        out.append((code, th, cr))
    return out


def block_slots(b: Block) -> list[str]:
    """ช่องวิชาเลือกในภาคนั้น (รหัสที่มี x) พร้อมชื่อกลุ่มตามที่แผนเขียน."""
    labels: list[str] = []
    n_slots = 0
    for m in _SLOT_RE.finditer(b.text):
        n_slots += 1
        window = b.text[m.end(): m.end() + 260]
        window = re.split(r"\d\s*\(\d+-\d+-\d+\)", window)[0]
        for lab in re.findall(r"วิชาเลือก[^\n|]*", window):
            lab = _clean(lab)
            lab = re.sub(r"\s*[A-Z][A-Z\s\d\-]+$", "", lab).strip()
            lab = re.sub(r"\s*หรือ$", "", lab).strip()
            if lab and lab not in labels:
                labels.append(lab)
    return [f"{n_slots} ช่อง"] + labels if n_slots else []


def variant_totals(blocks: list[Block], variant: str) -> dict[tuple[int, int], Block]:
    out: dict[tuple[int, int], Block] = {}
    for b in blocks:
        if b.variant == variant and (b.year, b.semester) not in out:
            out[(b.year, b.semester)] = b
    return out


def describe_block(conn: sqlite3.Connection, version_id: int, b: Block, *, indent: str = "  ") -> list[str]:
    head = f"{VARIANT_LABEL[b.variant]} — ปีที่ {b.year} ภาคการศึกษาที่ {b.semester} (หน้า {', '.join(map(str, b.pages))}):"
    lines = [head]
    for code, th, cr in block_courses(conn, version_id, b):
        lines.append(f"{indent}- {code} {th} {('— ' + cr) if cr else ''}".rstrip())
    slots = block_slots(b)
    if slots:
        lines.append(f"{indent}- วิชาเลือกที่ต้องลงตามแผน: {slots[0]}")
        for lab in slots[1:]:
            lines.append(f"{indent}    • {lab}")
    if b.total is not None:
        lines.append(f"{indent}รวมภาคนี้ตามแผนในเล่ม: {b.total} หน่วยกิต")
    return lines


# ══════════════════════════════════════════════════════════════════════
# คำตอบ: ถามเรื่องแผนสหกิจ / แผนปกติ
# ══════════════════════════════════════════════════════════════════════

_NORMAL_KW = ("แผนปกติ", "ไม่ทำสหกิจ", "ไม่เข้าโครงการ", "ไม่เข้าสหกิจ", "ไม่สหกิจ")
_DIFF_KW = ("ต่างกัน", "แตกต่าง", "เปรียบเทียบ", "ต่างจาก")
_WHERE_KW = ("ภาคไหน", "ภาคใด", "ปีไหน", "เทอมไหน", "ลงทะเบียน", "กี่หน่วยกิต", "ภาคเรียนไหน", "เรียนตอนไหน")


def _flags(q: str) -> tuple[bool, bool, bool]:
    normal = any(k in q for k in _NORMAL_KW)
    # "ไม่ทำสหกิจ" มีคำว่าสหกิจอยู่ด้วย — นับเป็นแผนปกติ ไม่ใช่แผนสหกิจ
    coop = "สหกิจ" in re.sub(r"ไม่(?:ทำ|เข้าโครงการ|เข้า|)\s*สหกิจ(?:ศึกษา)?", "", q)
    diff = any(k in q for k in _DIFF_KW)
    return coop, normal, diff


def detect_plan_variant_intent(question: str) -> bool:
    from katrag.query.structured_query import detect_semester, detect_year

    coop, normal, diff = _flags(question)
    if not (coop or normal or ("สหกิจ" in question)):
        return False
    has_slot = detect_year(question) is not None
    return has_slot or diff or any(k in question for k in _WHERE_KW)


def try_plan_variants(conn: sqlite3.Connection, question: str):
    from katrag.query.structured_query import (
        StructuredResult, _resolve_version_id, _versions_label, detect_program, detect_semester,
        detect_versions, detect_year,
    )

    none = StructuredResult(False, "", "", "none")
    program = detect_program(question)
    if not program:
        return none
    named = [(v, y) for v, p, y in detect_versions(conn, question) if p == program]
    if len(named) == 1:
        version_id = named[0][0]
    else:
        resolved = _resolve_version_id(conn, program, None)
        if not resolved:
            return none
        version_id = resolved[0]
    blocks = plan_blocks(conn, version_id)
    default, coop_map = variant_totals(blocks, "default"), variant_totals(blocks, "coop")
    if not coop_map or not default:
        return none

    label = _versions_label(conn, [version_id])
    coop, normal, diff = _flags(question)
    year, sem = detect_year(question), detect_semester(question)
    rule_total = conn.execute(
        "SELECT value_numeric FROM rule WHERE version_id=? AND attribute='min_total_credits'", (version_id,)
    ).fetchone()
    sum_default = sum(b.total or 0 for b in default.values())
    sum_coop = sum(b.total or 0 for b in coop_map.values())
    note: list[str] = []
    if rule_total and rule_total[0] is not None and any(
        s != int(rule_total[0]) for s in (sum_default, sum_coop)
    ):
        note.append(
            f"หมายเหตุ: ผลรวมหน่วยกิตทุกภาคที่อ่านได้ (ปกติ {sum_default}, สหกิจ {sum_coop}) ไม่เท่าหน่วยกิตรวมของหลักสูตร "
            f"{rule_total[0]:g} อาจมีบางภาคอ่านจากเล่มไม่ได้"
        )

    def _pages(blks: list[Block]) -> list[tuple[str, int, str]]:
        out: list[tuple[str, int, str]] = []
        for b in blks:
            for pg in b.pages:
                item = (b.document_id, pg, "ตารางแผนการศึกษา " + VARIANT_LABEL[b.variant])
                if item not in out:
                    out.append(item)
        return out

    def _sig(b: Block) -> tuple:
        # เทียบเป็นเซ็ต: สองแผนอาจเรียงแถวในตารางต่างกันโดยเนื้อหาเหมือนกัน
        codes = tuple(sorted(c for c, _t, _c in block_courses(conn, version_id, b)))
        slots = block_slots(b)
        return (codes, slots[0] if slots else "", tuple(sorted(slots[1:])), b.total)

    # ── 1) เปรียบเทียบแผนปกติกับแผนสหกิจ ──
    if (diff or "แทน" in question) and coop and not (year and sem):
        keys = sorted(set(default) | set(coop_map))
        lines = [f"เปรียบเทียบแผนการศึกษา {label}: แผนปกติ (3.1.4.1) กับแผนที่เข้าโครงการสหกิจศึกษา (3.1.4.2)", ""]
        differing: list[tuple[int, int]] = []
        used: list[Block] = []
        for k in keys:
            a, b = default.get(k), coop_map.get(k)
            same = a is not None and b is not None and _sig(a) == _sig(b)
            ta = a.total if a else None
            tb = b.total if b else None
            lines.append(
                f"- ปีที่ {k[0]} ภาคการศึกษาที่ {k[1]}: แผนปกติ {ta if ta is not None else '-'} หน่วยกิต · "
                f"แผนสหกิจ {tb if tb is not None else '-'} หน่วยกิต" + ("" if same else "  ← ต่างกัน")
            )
            if not same:
                differing.append(k)
        lines.append(f"\nรวมตลอดหลักสูตร: แผนปกติ {sum_default} หน่วยกิต · แผนสหกิจ {sum_coop} หน่วยกิต"
                     + (" (เท่ากัน)" if sum_default == sum_coop else " (ต่างกัน)"))
        if not differing:
            lines.append("\nทุกภาคเหมือนกันทั้งสองแผน")
        else:
            lines.append("\nภาคที่ต่างกัน: " + ", ".join(f"ปี {y} ภาค {s}" for y, s in differing))
            for k in differing:
                for blk in (default.get(k), coop_map.get(k)):
                    if blk:
                        used.append(blk)
                        lines.append("")
                        lines.extend(describe_block(conn, version_id, blk))
        alt = conn.execute(
            "SELECT value_numeric, value_text FROM rule WHERE version_id=? AND attribute LIKE 'credits.%.alternative'",
            (version_id,),
        ).fetchone()
        if alt:
            name, _, extra = (alt[1] or "").partition(" | ")
            lines.append(f"\nตามโครงสร้างหลักสูตร: {name} {alt[0]:g} หน่วยกิต" + (f" ({extra})" if extra else ""))
        lines += note
        return StructuredResult(True, "\n".join(lines), label, "plan_variant", version_id=version_id, pages=_pages(used))

    # ── 2) ภาคเรียนใดภาคเรียนหนึ่งของแผนใดแผนหนึ่ง ──
    if year is not None and (coop or normal):
        maps = [default, coop_map] if (coop and normal) else [coop_map] if coop else [default]
        blks = []
        for mp in maps:
            want = [(year, sem)] if sem is not None else sorted(k for k in mp if k[0] == year)
            blks += [mp[k] for k in want if k in mp]
        if not blks:
            return none
        lines: list[str] = []
        for blk in blks:
            lines.extend(describe_block(conn, version_id, blk))
            lines.append("")
        lines += note
        return StructuredResult(True, "\n".join(lines).strip(), label, "plan_variant", version_id=version_id, pages=_pages(blks))

    # ── 3) วิชาสหกิจอยู่ภาคไหน กี่หน่วยกิต ──
    if coop and not (year or sem):
        only: list[tuple[Block, tuple[str, str, str]]] = []
        default_codes = {c for b in default.values() for c, _t, _c in block_courses(conn, version_id, b)}
        for k in sorted(coop_map):
            blk = coop_map[k]
            for code, th, cr in block_courses(conn, version_id, blk):
                if code not in default_codes:
                    only.append((blk, (code, th, cr)))
        if not only:
            return none
        lines = [f"รายวิชาที่มีเฉพาะในแผนที่เข้าโครงการสหกิจศึกษา ({label}):"]
        for blk, (code, th, cr) in only:
            lines.append(f"- {code} {th} — {cr} | ปีที่ {blk.year} ภาคการศึกษาที่ {blk.semester} (หน้า {', '.join(map(str, blk.pages))})")
        first = only[0][0]
        lines.append(f"\nภาคนั้นรวม {first.total} หน่วยกิตตามแผนในเล่ม (ในแผนปกติภาคเดียวกันรวม "
                     f"{default[(first.year, first.semester)].total if (first.year, first.semester) in default else '-'} หน่วยกิต)")
        lines += note
        return StructuredResult(True, "\n".join(lines), label, "plan_variant", version_id=version_id,
                                pages=_pages([b for b, _ in only]))
    return none
