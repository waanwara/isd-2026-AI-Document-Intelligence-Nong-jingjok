"""Tests for the fixes from tester feedback: course groups/tracks, faculty lists, course lookup, PII and CJK."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from katrag.query.course_groups import course_groups, try_course_lookup, try_track
from katrag.query.faculty import faculty_lists
from katrag.query.pipeline import _strip_cjk, redact_pii

DB = Path(__file__).resolve().parents[2] / "artifacts" / "katrag.sqlite3"
needs_db = pytest.mark.skipif(not DB.exists(), reason="database not extracted (run setup_db.py)")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(str(DB))
    yield c
    c.close()


def test_redact_pii_masks_national_ids():
    assert "3100500712364" not in redact_pii("ศ.ดร.ศุภมิตร (3100500712364) วศ.บ.")
    assert "1-2345-67890-12-3" not in redact_pii("เลข 1-2345-67890-12-3")
    assert redact_pii("รหัสวิชา 06026240 3 หน่วยกิต") == "รหัสวิชา 06026240 3 หน่วยกิต"


def test_strip_cjk_keeps_thai_and_english():
    assert _strip_cjk("วิชานี้เรียนปี 3 学期 Data") == "วิชานี้เรียนปี 3 Data"


@needs_db
def test_dsba_track_groups(conn):
    groups = course_groups(conn, 5)
    assert groups["06026240"][0].label == "กลุ่มวิศวกรรมข้อมูล"
    assert groups["06026216"][0].label == "กลุ่มวิทยาการข้อมูล"
    assert groups["06026230"][0].label == "กลุ่มการวิเคราะห์เชิงสถิติ"


@needs_db
def test_it_module_course_can_be_in_two_modules(conn):
    labels = {g.label for g in course_groups(conn, 7)["06016418"]}
    assert "กลุ่มวิชาด้านการพัฒนาซอฟต์แวร์" in labels
    assert any("สื่อประสม" in lab for lab in labels)


@needs_db
def test_groups_not_used_when_section_end_missing(conn):
    assert course_groups(conn, 1) == {}  # AIT: no 3.1.4.1 heading, parsing would run into other pages


@needs_db
def test_course_lookup_by_english_name(conn):
    r = try_course_lookup(conn, "หลักสูตร DSBA: fundamental web programming เรียนตอนไหน")
    assert r.matched and "06066302" in r.context and "ปีที่ 2 ภาคการศึกษาที่ 1" in r.context


@needs_db
def test_course_lookup_elective_points_to_track_slots(conn):
    r = try_course_lookup(conn, "หลักสูตร DSBA: intelligent system development เรียนตอนไหน")
    assert "กลุ่มวิศวกรรมข้อมูล" in r.context and "วิชาเลือกกลุ่มวิศวกรรมข้อมูล" in r.context


@needs_db
def test_track_lists_group_courses(conn):
    r = try_track(conn, "หลักสูตร DSBA: แขนงวิทยาการข้อมูลมีวิชาอะไรบ้าง")
    assert r.matched and "(14 วิชา)" in r.context and "06026229" in r.context


@needs_db
def test_faculty_lists_from_book(conn):
    it = faculty_lists(conn, 7)
    assert len(it["regular"]) == 6 and it["regular"][0][1].startswith("รศ.ดร.โชติพัชร์")
    assert len(faculty_lists(conn, 5)["teaching"]) == 33
    for people in it.values():
        for _n, name, _p in people:
            assert not any(ch.isdigit() for ch in name)
