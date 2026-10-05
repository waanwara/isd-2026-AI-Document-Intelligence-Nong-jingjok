"""Tests for category-credit rules and plan variants (read the shipped database)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from katrag.ingest.populate_structure_rules import STRUCTURE, verify_seed
from katrag.query.plan_variants import plan_blocks, variant_totals
from katrag.query.structured_query import (
    detect_structure_intent,
    try_graduation_audit,
    try_structure_answer,
)

DB = Path(__file__).resolve().parents[2] / "artifacts" / "katrag.sqlite3"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="database not extracted (run setup_db.py)")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(str(DB))
    yield c
    c.close()


def _vid(c, program, year):
    return c.execute(
        "SELECT version_id FROM curriculum_version WHERE program=? AND curriculum_year=?", (program, year)
    ).fetchone()[0]


def test_verify_seed_rejects_wrong_numbers(conn):
    doc = conn.execute("SELECT document_id FROM document WHERE version_id=?", (_vid(conn, "DSBA", 2565),)).fetchone()[0]
    text = conn.execute("SELECT page_text FROM page WHERE document_id=? AND page_number=15", (doc,)).fetchone()[0]
    assert verify_seed(text, "หมวดวิชาศึกษาทั่วไป", 30)
    assert not verify_seed(text, "หมวดวิชาศึกษาทั่วไป", 31)
    assert not verify_seed(text, "หมวดวิชาเลือกเสรี", 7)


def test_every_structure_seed_is_in_the_database(conn):
    for (program, year), rows in STRUCTURE.items():
        vid = _vid(conn, program, year)
        n = conn.execute(
            "SELECT COUNT(*) FROM rule WHERE version_id=? AND attribute LIKE 'credits.%'", (vid,)
        ).fetchone()[0]
        assert n == len(rows), (program, year)


def test_top_level_structure_adds_up_to_total_credits(conn):
    """ศึกษาทั่วไป + เฉพาะ + เลือกเสรี = หน่วยกิตรวม สำหรับทุกหลักสูตรที่เก็บโครงสร้างไว้."""
    for program, year in STRUCTURE:
        vid = _vid(conn, program, year)
        vals = dict(conn.execute(
            "SELECT attribute, value_numeric FROM rule WHERE version_id=? AND attribute IN "
            "('credits.general_education','credits.specific','credits.free_elective','min_total_credits')", (vid,)
        ).fetchall())
        if "min_total_credits" in vals:
            parts = vals["credits.general_education"] + vals["credits.specific"] + vals["credits.free_elective"]
            assert parts == vals["min_total_credits"], (program, year, vals)


def test_structure_answer_gives_the_asked_category(conn):
    q = "หลักสูตร DSBA: หมวดวิชาศึกษาทั่วไปต้องเก็บกี่หน่วยกิต"
    assert detect_structure_intent(q)
    r = try_structure_answer(conn, q)
    assert r.matched and "หมวดวิชาศึกษาทั่วไป 30 หน่วยกิต" in r.context and r.pages


def test_course_questions_are_not_structure_questions():
    assert not detect_structure_intent("วิชาแคลคูลัส 2 มีกี่หน่วยกิต")
    assert not detect_structure_intent("ปีหนึ่งเทอมหนึ่งเรียนวิชาอะไร กี่หน่วยกิต")


def test_generic_audit_reports_the_shortfall(conn):
    q = "นักศึกษา AIT เก็บศึกษาทั่วไป 30 หน่วยกิต วิชาเฉพาะ 80 หน่วยกิต เลือกเสรี 6 หน่วยกิต รวม 116 หน่วยกิต จบได้ไหม"
    r = try_graduation_audit(conn, q)
    assert r.matched
    assert "ขาดอีก 4" in r.context and "ขาดอีก 10" in r.context


@pytest.mark.parametrize("program,year", [("DSBA", 2565), ("BIT", 2565), ("IT", 2565), ("IT", 2560), ("DSBA", 2560), ("BIT", 2560)])
def test_both_plans_sum_to_the_course_total(conn, program, year):
    """ตารางแผนปกติและแผนสหกิจที่อ่านจากเล่ม รวมทุกภาคเท่ากับหน่วยกิตรวมของหลักสูตร."""
    vid = _vid(conn, program, year)
    blocks = plan_blocks(conn, vid)
    total = conn.execute(
        "SELECT value_numeric FROM rule WHERE version_id=? AND attribute='min_total_credits'", (vid,)
    ).fetchone()[0]
    for variant in ("default", "coop"):
        got = sum(b.total or 0 for b in variant_totals(blocks, variant).values())
        assert got == total, (program, year, variant, got, total)


def test_dsba_coop_plan_differs_in_year_4(conn):
    blocks = plan_blocks(conn, _vid(conn, "DSBA", 2565))
    normal, coop = variant_totals(blocks, "default"), variant_totals(blocks, "coop")
    assert (normal[(4, 1)].total, normal[(4, 2)].total) == (9, 9)
    assert (coop[(4, 1)].total, coop[(4, 2)].total) == (12, 6)
    assert normal[(1, 1)].total == coop[(1, 1)].total == 18
