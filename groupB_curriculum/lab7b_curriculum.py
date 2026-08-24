#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 lab7b_curriculum.py
 Lab 7B — สกัดแผนการศึกษาจากเล่มหลักสูตร ด้วย LLM ที่รันบนเครื่องตัวเอง
================================================================================

 วิชา 06026240 การพัฒนาระบบอัจฉริยะ  |  เทคโนโลยีสารสนเทศ สจล.
 --------------------------------------------------------------------------
 ⚠️  ข้อบังคับ: รันแบบออฟไลน์ 100% ไม่มีค่าใช้จ่าย
 --------------------------------------------------------------------------
 แม้เล่มหลักสูตรจะเป็นเอกสารสาธารณะ (ไม่เข้าข่าย PDPA) แต่แล็บนี้กำหนดให้
 ทุกกลุ่มใช้โมเดลที่รันบนเครื่องเท่านั้น ด้วยเหตุผล 3 ข้อ:
   1. นักศึกษาต้องไม่มีค่าใช้จ่าย
   2. ผลลัพธ์ต้องทำซ้ำได้ (API ภายนอกเปลี่ยนโมเดลเงียบ ๆ เมื่อไรก็ได้)
   3. เป็นทักษะที่ใช้ได้จริงเมื่อไปทำงานกับข้อมูลที่ห้ามออกนอกองค์กร

 --------------------------------------------------------------------------
 วิธีใช้
 --------------------------------------------------------------------------
   python3 lab7b_curriculum.py --check

   python3 lab7b_curriculum.py \
       --input data/DSBA_plan.pdf \
       --gt    gt/DSBA_academic_plan_coop.json \
       --pipeline all --out output/

   # เล่มหลักสูตรยาวมาก ให้ระบุเฉพาะหน้าที่เป็นตารางแผนการศึกษา
   python3 lab7b_curriculum.py -i data/DSBA.pdf --pages 42-58 -g gt/x.json

================================================================================
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lab7_metrics as M  # noqa: E402


# ==============================================================================
#  ส่วนที่ 0 — ค่าตั้งต้น
# ==============================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL_OCR = os.getenv("LAB7_MODEL_OCR", "scb10x/typhoon-ocr1.5-3b")
MODEL_TEXT = os.getenv("LAB7_MODEL_TEXT", "qwen3:4b")
DPI = int(os.getenv("LAB7_DPI", "150"))
REQUEST_TIMEOUT = 900

# ⭐ ค่าเฉพาะของกลุ่ม B
# เล่มหลักสูตรมี 50-150 หน้า ส่งเข้าโมเดลทีเดียวไม่ได้แน่นอน
# เราจึง "แบ่งเป็นก้อน" (chunk) ทีละไม่กี่หน้า แล้วรวมผลทีหลัง
PAGES_PER_CHUNK = int(os.getenv("LAB7_CHUNK", "3"))

# ข้าม pipeline baseline (Tesseract) ทั้งหมด
#     export LAB7_SKIP_BASELINE=1
# ⚠️ ผลที่ตามมา: จะไม่มีเส้นฐานไว้เปรียบเทียบ ทำให้ตอบคำถามท้ายบท
#    ชุดที่ 2 (เปรียบเทียบ pipeline) ไม่ได้ และเสียคะแนนส่วนที่ 3
SKIP_BASELINE = os.getenv("LAB7_SKIP_BASELINE", "").strip() in ("1", "true", "yes")


# ==============================================================================
#  ส่วนที่ 1 — ตรวจความพร้อม / ยืนยันออฟไลน์
# ==============================================================================


def _need(mod: str, pipname: str = "") -> Any:
    try:
        return __import__(mod)
    except ImportError:
        raise SystemExit(f"\n❌ ไม่พบไลบรารี '{mod}'\n   ติดตั้ง: pip install {pipname or mod}\n")


def assert_offline() -> None:
    """ตรวจว่า Ollama ชี้ไปที่เครื่องตัวเอง — fail closed ถ้าไม่แน่ใจ"""
    allowed = ("127.0.0.1", "localhost", "0.0.0.0", "::1")
    host = OLLAMA_HOST.replace("http://", "").replace("https://", "").split(":")[0]
    if host not in allowed:
        raise SystemExit(
            f"\n❌ OLLAMA_HOST = {OLLAMA_HOST} ไม่ใช่เครื่องภายใน\n"
            f"   แล็บนี้กำหนดให้รันออฟไลน์เท่านั้น  แก้โดย: unset OLLAMA_HOST\n")
    print(f"✓ ยืนยันโหมดออฟไลน์: {OLLAMA_HOST}")


def check_environment() -> bool:
    ok = True
    print("\n" + "=" * 70)
    print("  ตรวจความพร้อมของเครื่อง")
    print("=" * 70)

    if shutil.which("ollama"):
        try:
            v = subprocess.run(["ollama", "--version"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
            print(f"  ✓ พบ Ollama: {v}")
        except Exception:
            print("  ✓ พบ Ollama")
    else:
        print("  ✗ ไม่พบคำสั่ง ollama --> ดูเอกสารแล็บ ส่วนที่ 2")
        ok = False

    try:
        requests = _need("requests")
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        installed = [m["name"] for m in r.json().get("models", [])]
        print(f"  ✓ Ollama service ทำงานที่ {OLLAMA_HOST}")
        for tag, role in [(MODEL_OCR, "อ่านภาพ"), (MODEL_TEXT, "จัด JSON")]:
            hit = any(i == tag or i.split(":")[0] == tag for i in installed)
            print(f"  {'✓' if hit else '✗'} [{role}] {tag}"
                  + ("" if hit else f"   --> ollama pull {tag}"))
            if not hit:
                ok = False
    except Exception as e:
        print(f"  ✗ ต่อ Ollama ไม่ได้: {e}\n    --> สั่ง: ollama serve")
        ok = False

    for mod, pip in [("fitz", "pymupdf"), ("PIL", "pillow"),
                     ("requests", "requests"), ("pdfplumber", "pdfplumber"),
                     ("pythainlp", "pythainlp")]:
        try:
            __import__(mod)
            print(f"  ✓ python: {mod}")
        except ImportError:
            print(f"  ✗ python: {mod} --> pip install {pip}")
            ok = False

    # --- ของที่ไม่จำเป็น — ขาดได้ ไม่ทำให้ --check ตก ---
    #
    # ⚠️ สังเกตว่าส่วนนี้ "ไม่มี ok = False" เลย
    #    สิ่งที่ทำให้ผลตรวจ "ไม่พร้อม" ต้องเป็นสิ่งที่ขาดแล้วรันไม่ได้จริงเท่านั้น
    print("\n  ส่วนเสริม (ขาดได้ ไม่ทำให้ --check ตก):")

    if SKIP_BASELINE:
        print("  ○ tesseract — ข้ามตามค่า LAB7_SKIP_BASELINE=1")
    else:
        has_exe = shutil.which("tesseract") is not None
        try:
            __import__("pytesseract")
            has_lib = True
        except ImportError:
            has_lib = False

        if has_exe and has_lib:
            print("  ✓ tesseract (จาก Lab 5-6) — ใช้กับ pipeline baseline")
        else:
            miss = []
            if not has_lib:
                miss.append("pip install pytesseract")
            if not has_exe:
                miss.append("ติดตั้งตัว engine (ดูเอกสาร Lab 5)")
            print(f"  ✗ tesseract — {' + '.join(miss)}")
            print("      pipeline baseline จะถูกข้ามไป (text และ vlm ยังใช้ได้ตามปกติ)")
            print("      ถ้าไม่ต้องการใช้ baseline เลย:  export LAB7_SKIP_BASELINE=1")

    print("=" * 70)
    print("  พร้อมใช้งาน ✓" if ok else "  ยังไม่พร้อม ✗")
    print("=" * 70 + "\n")
    return ok


# ==============================================================================
#  ส่วนที่ 2 — เตรียม input
# ==============================================================================


def parse_page_range(spec: str, total: int) -> list[int]:
    """
    แปลงข้อความอย่าง "42-58" หรือ "3,7,10-12" เป็น list ของ index (เริ่มที่ 0)

    ทำไมต้องมี? เพราะเล่มหลักสูตรมี 150 หน้า แต่ตารางแผนการศึกษาอยู่แค่ 10-20 หน้า
    การส่งทั้งเล่มเข้าโมเดลคือการเผาเวลาไปกับหน้าที่ไม่เกี่ยวข้อง
    (ในระบบที่จ่ายเงินตาม token นี่คือการเผาเงินด้วย)
    """
    idx: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            idx.update(range(int(a) - 1, int(b)))    # ผู้ใช้พิมพ์เลขหน้าเริ่มที่ 1
        elif part:
            idx.add(int(part) - 1)
    return sorted(i for i in idx if 0 <= i < total)


def load_pages(path: str, page_spec: str | None = None) -> list[bytes]:
    """แปลง PDF เป็นภาพ PNG รายหน้า"""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"❌ ไม่พบไฟล์: {path}")

    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return [p.read_bytes()]

    fitz = _need("fitz", "pymupdf")
    doc = fitz.open(str(p))
    wanted = parse_page_range(page_spec, len(doc)) if page_spec else range(len(doc))

    if page_spec:
        print(f"  เล่มมี {len(doc)} หน้า — เลือกใช้ {len(list(wanted))} หน้า")

    mat = fitz.Matrix(DPI / 72, DPI / 72)
    pages = []
    for i in wanted:
        pix = doc[i].get_pixmap(matrix=mat)
        pages.append(pix.tobytes("png"))
    doc.close()
    print(f"  แปลงเป็นภาพแล้ว {len(pages)} หน้า @ {DPI} DPI")
    return pages


def extract_pdf_text(path: str, page_spec: str | None = None) -> str:
    """
    ดึงข้อความจาก PDF โดยตรง (ถ้าเป็น PDF ที่ฝังข้อความไว้ ไม่ใช่ภาพสแกน)

    ⚠️ ประเด็นสำคัญของกลุ่ม B:
       เล่มหลักสูตรจำนวนมากเป็น "digital PDF" ที่มีข้อความอยู่แล้ว
       ถ้าเป็นแบบนั้น การเอาไปทำ OCR คือการทำงานซ้ำซ้อนโดยไม่จำเป็น
       และยังทำให้ผลแย่ลง เพราะ OCR มีโอกาสอ่านผิด แต่ข้อความที่ฝังมาไม่ผิด

       --> ตรวจก่อนเสมอ ว่าดึงข้อความตรง ๆ ได้ไหม
       เกณฑ์ที่ใช้: ถ้าดึงได้เกิน 500 ตัวอักษรต่อหน้า ถือว่าเป็น digital PDF

    ⚠️ แต่มีข้อควรระวัง: extract_text() ธรรมดา "ทำตารางพัง"
       คอลัมน์จะปนกันมั่ว --> ต้องใช้ layout=True เพื่อรักษาตำแหน่ง
       นี่คือเหตุผลที่ตาราง "แผนการศึกษา" มักอ่านผิดแม้เป็น digital PDF
    """
    pdfplumber = _need("pdfplumber")
    out = []
    with pdfplumber.open(path) as pdf:
        wanted = parse_page_range(page_spec, len(pdf.pages)) if page_spec \
            else range(len(pdf.pages))
        for i in wanted:
            # layout=True รักษาระยะห่างแนวนอน ทำให้คอลัมน์ยังเรียงกันอยู่
            t = pdf.pages[i].extract_text(layout=True) or ""
            out.append(f"\n=== หน้า {i + 1} ===\n{t}")
    return "\n".join(out)


# ==============================================================================
#  ส่วนที่ 3 — JSON SCHEMA
# ==============================================================================
#
#  Schema ต้องตรงกับ ground truth (DSBA_academic_plan_coop.json) เป๊ะ ๆ
#
#  ⚠️ ข้อสังเกตจาก ground truth จริง ที่ต้องสะท้อนใน schema:
#
#   1. `year` และ `semester` เป็น "0" ได้ ซึ่งไม่ได้แปลว่าปี 0
#      แต่แปลว่า "วิชาเลือก ที่ยังไม่กำหนดว่าจะลงปีไหน/ภาคไหน"
#      กรณีนี้ต้องกรอก flexible_year_semester แทน เช่น "3/1, 3/2, 4/1"
#
#   2. `prerequisite` เป็น string ไม่ใช่ list  ถ้าไม่มีให้ใส่คำว่า "ไม่มี"
#      (ไม่ใช่ null, ไม่ใช่ [] — ต้องตรงกับ GT)
#
#   3. `credits` เป็น string รูปแบบ "3(3-0-6)"
#      แปลว่า 3 หน่วยกิต = บรรยาย 3 ชม. - ปฏิบัติ 0 ชม. - ศึกษาเอง 6 ชม.
#      บางวิชาเป็น "3(3-0-6) หรือ 3(2-2-5)" ได้ด้วย
#
#   4. `name_en` ใน GT มีอักขระขึ้นบรรทัดใหม่ (\n) ฝังอยู่
#      เพราะชื่อยาวเกินความกว้างคอลัมน์ใน PDF แล้วถูกตัดบรรทัด
#      --> เราจะจัดการด้วย normalization ไม่ใช่บังคับให้โมเดลเดาว่าตัดตรงไหน
# ==============================================================================

_S = {"type": "string"}
_SN = {"type": ["string", "null"]}

COURSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "program": _SN,          # เช่น "DSBA"
        "plan": _SN,             # เช่น "coop" หรือ "normal"
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": _S,           # รหัสวิชา 8 หลัก
                    "name_th": _SN,
                    "name_en": _SN,
                    "credits": _SN,       # "3(3-0-6)"
                    "year": {"type": ["integer", "string", "null"]},
                    "semester": {"type": ["integer", "string", "null"]},
                    "category": _SN,      # หมวดวิชาศึกษาทั่วไป / เฉพาะ / เลือกเสรี
                    "type": _SN,          # บังคับ / เลือก
                    "prerequisite": _SN,  # รหัสวิชา หรือคำว่า "ไม่มี"
                    "flexible_year_semester": _SN,
                    "note": _SN,
                },
                "required": ["code", "name_th", "credits", "year", "semester"],
            },
        },
    },
    "required": ["courses"],
}


# ==============================================================================
#  ส่วนที่ 4 — PROMPT
# ==============================================================================

SYSTEM_PROMPT = """You are a precise document extraction system for Thai university curriculum documents.
You transcribe exactly what is printed. You never invent courses that are not in the document.
You never stop early. When a field is absent you output null."""

EXTRACT_PROMPT = """ต่อไปนี้คือข้อความจากเล่มหลักสูตรของสถาบันในประเทศไทย
จงสกัดรายวิชาทั้งหมดออกมาเป็น JSON ตาม schema ที่กำหนด

=== กติกา ===

[1] สกัดทุกวิชาที่ปรากฏ ห้ามข้าม ห้ามหยุดกลางทาง
    ดูให้ครบทุกหมวด:
      - หมวดวิชาศึกษาทั่วไป
      - หมวดวิชาเฉพาะ (กลุ่มวิชาแกน / กลุ่มวิชาเฉพาะด้าน / กลุ่มวิชาบังคับ / กลุ่มวิชาเลือก)
      - หมวดวิชาเลือกเสรี
      - รายวิชาสหกิจศึกษา (ถ้ามี)

[2] ปี/ภาคการศึกษา — อ่านให้ดี ตรงนี้ผิดกันบ่อย
    - วิชาบังคับที่ตารางแผนการศึกษาระบุปี/ภาคชัดเจน
        --> ใส่ year = 1..4 และ semester = 1..3 ตามที่ระบุ
        --> flexible_year_semester = null
    - วิชาเลือก ที่ตารางบอกว่าลงได้หลายภาค
        --> ใส่ year = 0 และ semester = 0
        --> แล้วระบุตัวเลือกใน flexible_year_semester เช่น "3/1, 3/2, 4/1"
    ห้ามเดาปี/ภาคให้วิชาเลือกที่เอกสารไม่ได้ระบุ

[3] prerequisite (วิชาบังคับก่อน)
    - ถ้ามี ให้ใส่ "รหัสวิชา" ของวิชาบังคับก่อน เช่น "06026200"
    - ถ้าไม่มี ให้ใส่คำว่า "ไม่มี"  (ห้ามใส่ null ห้ามใส่ [])

[4] credits ให้คัดลอกตามที่พิมพ์ เช่น "3(3-0-6)" หรือ "3(2-2-5)"
    ห้ามแปลงเป็นตัวเลขเดี่ยว  ถ้าเอกสารเขียนสองแบบ ให้คงไว้ทั้งสอง
    เช่น "3(3-0-6) หรือ 3(2-2-5)"

[5] category ต้องเป็นหนึ่งใน 3 ค่านี้เท่านั้น:
    "หมวดวิชาศึกษาทั่วไป" | "หมวดวิชาเฉพาะ" | "หมวดวิชาเลือกเสรี"

[6] type ต้องเป็น "บังคับ" หรือ "เลือก" เท่านั้น

[7] ชื่อวิชาภาษาอังกฤษ ให้คัดลอกตามที่พิมพ์ รวมทั้งตัวพิมพ์ใหญ่
    ถ้าชื่อถูกตัดขึ้นบรรทัดใหม่ในเอกสาร ให้ต่อเป็นบรรทัดเดียวโดยเว้นวรรค 1 ครั้ง

[8] ⭐ แถว "ช่องวิชาเลือก" ที่ยังไม่ระบุวิชาเจาะจง
    ในตารางแผนการศึกษา บางแถวไม่ได้ระบุรหัสวิชาจริง แต่เขียนว่า
    "วิชาเลือกกลุ่ม..." หรือ "วิชาเลือกเสรี" พร้อมรหัสที่มี x เช่น
        06026xxx  9064xxxx  xxxxxxxx
    แถวเหล่านี้ "เป็นข้อมูลจริง" ต้องสกัดออกมาด้วย ห้ามข้าม
    ให้คัดลอกรหัสตามที่พิมพ์ (เก็บตัว x ไว้) และคัดลอกชื่อตามที่พิมพ์
    ถ้ามีหลายแถวชื่อคล้ายกัน ให้แยกเป็นคนละรายการ เช่น
        "วิชาเลือกกลุ่มวิทยาการข้อมูล 1" และ "วิชาเลือกกลุ่มวิทยาการข้อมูล 2"

[9] ห้ามสร้างวิชาที่ไม่มีในเอกสาร ห้ามเติมวิชาที่ "น่าจะมี"
    ถ้าไม่แน่ใจว่าแถวนั้นเป็นวิชาหรือไม่ ให้ข้าม ดีกว่าใส่ข้อมูลผิด
    (แต่แถวช่องวิชาเลือกตามข้อ [8] ถือเป็นวิชา ต้องเก็บ)

=== ข้อความจากเอกสาร ===
{document_text}

=== สิ้นสุดข้อความ ===
ตอบเป็น JSON เท่านั้น"""

TYPHOON_PROMPT = ("Below is an image of a document page. "
                  "Extract all text content and structure into markdown format. "
                  "Preserve tables using markdown table syntax.")


# ==============================================================================
#  ส่วนที่ 5 — เรียก Ollama
# ==============================================================================


def ollama_chat(model: str, messages: list[dict], *, fmt: dict | None = None,
                images: list[bytes] | None = None, temperature: float = 0.0,
                retries: int = 2) -> str:
    """เหมือนกับของกลุ่ม A — ดูคำอธิบายละเอียดในเอกสารแล็บ ส่วนที่ 4"""
    requests = _need("requests")

    if images:
        messages = [dict(m) for m in messages]
        messages[-1]["images"] = [base64.b64encode(im).decode() for im in images]

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            # ⭐ กลุ่ม B ต้องการ context ใหญ่กว่ากลุ่ม A มาก
            #    เพราะตารางหลักสูตรยาว 90+ แถว
            #    ⚠️ ยิ่ง num_ctx ใหญ่ ยิ่งกินแรม: 32768 tokens ~ +2-3 GB
            #    ถ้าเครื่องแรมน้อย ให้ลดเหลือ 16384 แล้วเพิ่มการแบ่ง chunk แทน
            "num_ctx": 32768,
            "num_predict": 16384,
        },
    }
    if fmt is not None:
        payload["format"] = fmt

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload,
                              timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            body = r.json()
            content = body["message"]["content"]
            # eval_count = จำนวน token ที่โมเดลผลิต — ใช้ดูว่าโดนตัดหรือไม่
            n_out = body.get("eval_count", 0)
            print(f"      ({model}: {time.time() - t0:.1f} วิ, "
                  f"{len(content):,} ตัวอักษร, {n_out:,} tokens)")
            if n_out >= payload["options"]["num_predict"] - 8:
                print("      ⚠ ผลลัพธ์อาจถูกตัดเพราะชน num_predict "
                      "--> ลดจำนวนหน้าต่อ chunk หรือเพิ่ม num_predict")
            if not content.strip():
                raise ValueError("โมเดลตอบว่าง")
            return content
        except Exception as e:
            last = e
            if attempt < retries:
                print(f"      ⚠ ลองใหม่ {attempt + 1}: {e}")
                time.sleep(3)
    raise RuntimeError(f"เรียก {model} ไม่สำเร็จ: {last}")


def parse_json(text: str) -> dict:
    t = re.sub(r"<think>.*?</think>", "", text.strip(), flags=re.DOTALL)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE)
    starts = [p for p in (t.find("{"), t.find("[")) if p != -1]
    if not starts:
        raise ValueError(f"ไม่พบ JSON:\n{text[:400]}")
    obj, _ = json.JSONDecoder().raw_decode(t[min(starts):])
    return obj


# ==============================================================================
#  ส่วนที่ 6 — การรวมผลจากหลาย chunk
# ==============================================================================


def merge_chunks(chunks: list[dict]) -> dict:
    """
    รวมผลจากหลาย chunk เข้าเป็นชุดเดียว

    ⚠️ ปัญหาที่ต้องแก้: วิชาซ้ำ
       ถ้าหน้าที่ 5 และหน้าที่ 6 มีตารางที่คาบเกี่ยวกัน วิชาเดียวกันจะถูก
       สกัดออกมาสองครั้ง  ถ้าไม่กรอง จำนวนวิชาจะเกินจริง

    ⚠️ แต่ระวัง! ในหลักสูตร DSBA จริง รหัส 06026259 (สหกิจศึกษา)
       ปรากฏ 2 แถวโดยตั้งใจ:
         แถวหนึ่ง เป็นวิชาบังคับ ปี 4 ภาค 2
         อีกแถวหนึ่ง เป็นวิชาเลือก ที่ยังไม่กำหนดปี/ภาค (year=0)
       --> กุญแจสำหรับกันซ้ำจึงต้องเป็น (รหัส, ปี, ภาค) ไม่ใช่รหัสอย่างเดียว
           ถ้าใช้รหัสอย่างเดียว เราจะ "ลบข้อมูลจริง" ทิ้งไปโดยไม่รู้ตัว

    บทเรียน: การกันซ้ำที่ก้าวร้าวเกินไป อันตรายกว่าการปล่อยให้ซ้ำ
    """
    seen: set[tuple] = set()
    courses: list[dict] = []
    n_dup = 0

    for ch in chunks:
        for c in ch.get("courses") or []:
            # ⚠️ ต้องรวม name_th ในกุญแจด้วย ไม่งั้นแถว "06026xxx" ที่มีสองแถว
            #    ในภาคเดียวกัน (วิชาเลือกกลุ่มฯ 1 และ 2) จะถูกลบทิ้งไปหนึ่ง
            key = (
                M.normalize(c.get("code"), "strict"),
                str(c.get("year")),
                str(c.get("semester")),
                M.normalize(c.get("name_th"), "strict"),
            )
            if key in seen:
                n_dup += 1
                continue
            seen.add(key)
            courses.append(c)

    if n_dup:
        print(f"      กรองวิชาซ้ำออก {n_dup} รายการ (คีย์ = รหัส+ปี+ภาค+ชื่อ)")

    return {
        "program": next((ch.get("program") for ch in chunks if ch.get("program")), None),
        "plan": next((ch.get("plan") for ch in chunks if ch.get("plan")), None),
        "courses": courses,
    }


# ==============================================================================
#  ส่วนที่ 7 — PIPELINE A : Tesseract baseline
# ==============================================================================


def pipeline_baseline(pages: list[bytes]) -> dict:
    """OpenCV -> Tesseract -> regex   (เส้นฐานสำหรับเปรียบเทียบ)"""
    try:
        import pytesseract
        from PIL import Image
        import numpy as np
        import cv2
    except ImportError as e:
        print(f"  ⚠ ข้าม baseline: {e}")
        return {}

    text = ""
    for i, png in enumerate(pages):
        img = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(bw, lang="tha+eng", config="--psm 6")
        text += txt + "\n"
        print(f"      Tesseract หน้า {i + 1}: {len(txt):,} ตัวอักษร")
    return _rule_based_parse(text)


def _rule_based_parse(text: str) -> dict:
    """
    regex สำหรับตารางหลักสูตร

    รูปแบบที่คาดหวัง:  <รหัส 8 หลัก> <ชื่อไทย> <ชื่ออังกฤษ> <หน่วยกิต>
    ปัญหาที่ regex แก้ไม่ได้เลย:
      - ชื่อวิชาไทยและอังกฤษอยู่คนละบรรทัด (ตัดบรรทัดตามความกว้างคอลัมน์)
      - บางตารางมีคอลัมน์ "ปี/ภาค" บางตารางไม่มี
      - หัวข้อหมวดวิชาอยู่คนละแถวกับตัววิชา ต้องจำ state ไว้
    --> นี่คือจุดที่ LLM ได้เปรียบชัดเจน เพราะมันเข้าใจ "บริบท" ของทั้งหน้า
    """
    courses: list[dict] = []
    category = None

    cat_re = re.compile(r"(หมวดวิชาศึกษาทั่วไป|หมวดวิชาเฉพาะ|หมวดวิชาเลือกเสรี)")
    # รหัส 8 หลัก + ข้อความ + หน่วยกิตรูปแบบ N(N-N-N)
    row_re = re.compile(r"(\d{8})\s+(.{3,90}?)\s+(\d\([\d\s\-]+\))")

    for line in text.splitlines():
        cm = cat_re.search(line)
        if cm:
            category = cm.group(1)
            continue

        rm = row_re.search(line)
        if rm:
            raw_name = rm.group(2).strip()
            # พยายามแยกชื่อไทยกับชื่ออังกฤษ โดยหาจุดที่เปลี่ยนภาษา
            m2 = re.match(r"([^\x00-\x7F][^A-Z]*)\s*([A-Z][A-Z\s\d\-&,\.]*)?$", raw_name)
            th = (m2.group(1).strip() if m2 else raw_name)
            en = (m2.group(2).strip() if m2 and m2.group(2) else None)
            courses.append({
                "code": rm.group(1),
                "name_th": th,
                "name_en": en,
                "credits": re.sub(r"\s", "", rm.group(3)),
                "year": None, "semester": None,
                "category": category, "type": None,
                "prerequisite": "ไม่มี",
                "flexible_year_semester": None, "note": None,
            })

    print(f"      regex แกะได้ {len(courses)} วิชา")
    return {"program": None, "plan": None, "courses": courses}


# ==============================================================================
#  ส่วนที่ 8 — PIPELINE B : Typhoon-OCR -> text LLM (แบ่ง chunk)
# ==============================================================================


def pipeline_vlm(pages: list[bytes], outdir: Path) -> dict:
    """
    ขั้น 1: Typhoon-OCR อ่านทุกหน้าเป็น Markdown
    ขั้น 2: แบ่ง Markdown เป็นก้อนละ PAGES_PER_CHUNK หน้า
            ส่งเข้า text LLM ทีละก้อน แล้วรวมผล

    ทำไมต้องแบ่งก้อน?
      ถ้าส่งทั้งเล่ม (150 หน้า ~ 200,000 token) เข้าไปทีเดียว:
        - เกิน context window ของโมเดลขนาดเล็ก --> ตัดท้ายทิ้งเงียบ ๆ
        - แม้ context พอ output ก็จะยาวเกิน num_predict --> JSON ขาดกลางคัน
        - ยิ่ง context ยาว โมเดลยิ่ง "ลืมกลาง" (lost in the middle)
          ซึ่งเป็นปรากฏการณ์ที่พบในงานวิจัยหลายชิ้น

      การแบ่งก้อนแลกมาด้วย: โมเดลไม่เห็นภาพรวมทั้งเล่ม
      เช่น อาจไม่รู้ว่าวิชานี้อยู่หมวดไหน ถ้าหัวข้อหมวดอยู่คนละก้อน
      --> ทางแก้ในระบบจริงคือใส่ "overlap" ให้ก้อนซ้อนกัน 1 หน้า
          หรือส่งหัวข้อหมวดที่เจอล่าสุดไปกับก้อนถัดไป (โจทย์ท้าทายข้อ 1)
    """
    md_pages: list[str] = []
    for i, png in enumerate(pages):
        print(f"    [ขั้น 1/2] Typhoon-OCR หน้า {i + 1}/{len(pages)}")
        md = ollama_chat(MODEL_OCR,
                         [{"role": "user", "content": TYPHOON_PROMPT}],
                         images=[png], temperature=0.1)
        md_pages.append(md)

    (outdir / "intermediate_vlm.md").write_text(
        "\n\n---\n\n".join(md_pages), encoding="utf-8")
    print(f"    บันทึก Markdown กลางทาง: {outdir / 'intermediate_vlm.md'}")

    return _text_to_json_chunked(md_pages)


def _text_to_json_chunked(md_pages: list[str]) -> dict:
    """แบ่งหน้าเป็นก้อน แล้วเรียก text LLM ทีละก้อน"""
    chunks: list[dict] = []
    n_chunks = (len(md_pages) + PAGES_PER_CHUNK - 1) // PAGES_PER_CHUNK

    for ci in range(n_chunks):
        part = md_pages[ci * PAGES_PER_CHUNK:(ci + 1) * PAGES_PER_CHUNK]
        print(f"    [ขั้น 2/2] จัด JSON ก้อนที่ {ci + 1}/{n_chunks} "
              f"({len(part)} หน้า)")
        try:
            raw = ollama_chat(
                MODEL_TEXT,
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": EXTRACT_PROMPT.format(
                     document_text="\n\n".join(part))}],
                fmt=COURSE_SCHEMA,
            )
            d = parse_json(raw)
            print(f"      ได้ {len(d.get('courses') or [])} วิชา")
            chunks.append(d)
        except Exception as e:
            # ก้อนหนึ่งพัง ไม่ควรทำให้ทั้งงานพัง — ข้ามไปทำก้อนถัดไป
            print(f"      ❌ ก้อนที่ {ci + 1} ล้มเหลว: {e}")

    return merge_chunks(chunks)


def pipeline_text(pdf_path: str, page_spec: str | None) -> dict:
    """
    ⭐ pipeline พิเศษของกลุ่ม B: ข้าม OCR ไปเลย

    ถ้า PDF มีข้อความฝังอยู่แล้ว การดึงข้อความตรง ๆ จะ:
      - เร็วกว่า 50-100 เท่า (ไม่ต้องรัน VLM)
      - แม่นกว่า (ไม่มีโอกาสอ่านตัวอักษรผิดเลย)

    บทเรียน: เครื่องมือที่ทันสมัยที่สุดไม่ใช่เครื่องมือที่ดีที่สุดเสมอไป
             ต้องดูก่อนว่าปัญหาที่แท้จริงคืออะไร
    """
    print("    ดึงข้อความจาก PDF โดยตรง (ไม่ผ่าน OCR)...")
    text = extract_pdf_text(pdf_path, page_spec)

    # แยกเป็นรายหน้าตามเครื่องหมายที่ extract_pdf_text ใส่ไว้
    pages_text = re.split(r"\n=== หน้า \d+ ===\n", text)
    pages_text = [p for p in pages_text if p.strip()]
    n_all = len(re.findall(r"=== หน้า \d+ ===", text))
    n_empty = n_all - len(pages_text)

    print(f"    ได้ข้อความ {len(text):,} ตัวอักษร จาก {len(pages_text)}/{n_all} หน้า")

    if not pages_text:
        print("    ⚠ ไม่มีหน้าไหนดึงข้อความได้เลย — เล่มนี้เป็น PDF สแกน")
        print("      ให้ใช้ --pipeline vlm แทน")
        return {}

    # ⚠️ จุดสำคัญ: ถ้ามีหน้าที่ดึงข้อความไม่ได้ปนอยู่ ต้องเตือนให้ดัง
    #    ไม่ใช่ข้ามไปเงียบ ๆ เพราะวิชาในหน้านั้นจะหายทั้งหมด
    #    แล้วนักศึกษาจะเห็นแค่ Recall ต่ำ โดยไม่รู้ว่าข้อมูลไม่เคยถูกส่งเข้าไป
    if n_empty:
        print(f"    ⚠ มี {n_empty} หน้าที่ดึงข้อความไม่ได้ (น่าจะเป็นหน้าสแกน)")
        print("      วิชาในหน้าเหล่านั้นจะหายไป --> Recall จะต่ำกว่าความจริง")
        print("      ถ้าเล่มมีหน้าสแกนปน ให้ใช้ --pipeline vlm แทน")

    return _text_to_json_chunked(pages_text)



# ==============================================================================
#  ส่วนที่ 10 — ตรวจความสอดคล้องภายใน
# ==============================================================================
#
#  กลุ่ม A ใช้ GPA เป็นตัวตรวจ  แต่หลักสูตรไม่มี GPA
#  เราจึงใช้กฎเชิงโครงสร้าง 5 ข้อแทน — ทุกข้อตรวจได้โดยไม่ต้องมีเฉลย
# ==============================================================================

VALID_CATEGORIES = {"หมวดวิชาศึกษาทั่วไป", "หมวดวิชาเฉพาะ", "หมวดวิชาเลือกเสรี"}
VALID_TYPES = {"บังคับ", "เลือก"}
CREDIT_RE = re.compile(r"^\d+\(\d+-\d+-\d+\)$")

# วิชาที่มีหน่วยกิตตั้งแต่เท่านี้ขึ้นไป ถือเป็น "วิชาก้อนใหญ่"
# เช่น สหกิจศึกษา (6 หน่วยกิต) หรือโครงงานพิเศษ
# ภาคที่มีวิชาแบบนี้ มักลงวิชาเดียวทั้งภาค จึงยกเว้นการตรวจหน่วยกิตขั้นต่ำ
BLOCK_COURSE_CREDITS = 6


def _valid_code(code: Any) -> bool:
    """
    ตรวจรูปแบบรหัสวิชา รองรับทั้งรหัสเดี่ยวและรหัสแบบ "เลือกอย่างใดอย่างหนึ่ง"

        "06026240"                -> True
        "06026xxx"                -> True   (ช่องวิชาเลือก)
        "06026259 หรือ 06026260"  -> True   (สหกิจในประเทศ / ต่างประเทศ)
        "หมายเหตุ: คอลัมน์..."     -> False  (แถวขยะจาก Excel)
    """
    raw = str(code or "")
    parts = [x for x in re.split(r"หรือ|/", raw) if x.strip()]
    if not parts:
        return False
    return all(re.fullmatch(r"[0-9x]{8}", M.normalize(x, "strict")) for x in parts)


def verify_internal(data: dict) -> dict:
    """ตรวจ 5 กฎ — เป็นสิ่งที่ทำได้ในระบบจริงที่ไม่มีเฉลย"""
    issues: list[str] = []
    courses = data.get("courses") or []
    # ชุดรหัสทั้งหมด — แตกรหัสแบบ "A หรือ B" ออกเป็นรายตัว
    # เพื่อให้การตรวจ prerequisite (กฎ 5) หาเจอ
    codes: set[str] = set()
    for c in courses:
        for part in re.split(r"หรือ|/", str(c.get("code") or "")):
            n = M.normalize(part, "strict")
            if n:
                codes.add(n)

    # ⚠️ กุญแจนับซ้ำต้องรวม name_th ด้วย ให้ตรงกับ merge_chunks
    #    ถ้าใช้แค่ (รหัส, ปี, ภาค) แถว "06026xxx" ที่มีสองแถวในภาคเดียวกัน
    #    (วิชาเลือกกลุ่มฯ 1 และ 2) จะถูกนับว่าซ้ำทั้งที่เป็นข้อมูลจริง
    dup = Counter((M.normalize(c.get("code"), "strict"),
                   str(c.get("year")), str(c.get("semester")),
                   M.normalize(c.get("name_th"), "strict")) for c in courses)
    credits_by_term: dict[str, int] = defaultdict(int)
    has_block_course: set[str] = set()   # ภาคที่มีวิชาก้อนใหญ่ เช่น สหกิจศึกษา

    for c in courses:
        code = c.get("code")

        # --- กฎ 1: รูปแบบรหัสวิชา ---
        # รูปแบบที่ถูกต้องมี 2 แบบ:
        #   ก) รหัสเดี่ยว 8 ตัว เป็นเลขหรือ x ("06026240", "06026xxx", "xxxxxxxx")
        #   ข) ⭐ รหัสแบบ "เลือกอย่างใดอย่างหนึ่ง" คั่นด้วยคำว่า "หรือ"
        #      เช่น "06026259 หรือ 06026260" (สหกิจศึกษาในประเทศ / ต่างประเทศ)
        #      แบบนี้พบจริงในหลักสูตร DSBA แผนสหกิจ ห้ามนับเป็นข้อผิดพลาด
        #
        # ⚠️ ตอนออกแบบกฎนี้ครั้งแรก เรารองรับแค่แบบ ก) แล้วพบว่ามันแจ้งเตือน
        #    ground truth ของจริงทันที  ซึ่งละเมิดหลักการที่เราวางไว้เองว่า
        #    "ถ้ากฎแจ้งเตือน ต้องแปลว่าผิดจริงแน่นอน"
        #    บทเรียน: ต้องทดสอบกฎกับ ground truth ก่อนเสมอ ถ้ากฎจับเฉลยผิด
        #             แปลว่ากฎผิด ไม่ใช่เฉลยผิด
        if not _valid_code(code):
            issues.append(f"รหัสวิชาผิดรูปแบบ: {code!r}")

        # --- กฎ 2: รูปแบบหน่วยกิต ---
        cr = c.get("credits") or ""
        if cr and not CREDIT_RE.match(cr.replace(" ", "")) and "หรือ" not in cr:
            issues.append(f"หน่วยกิตผิดรูปแบบ: {code} -> {cr!r}")

        # --- กฎ 3: ค่าที่เป็นหมวดหมู่ ต้องอยู่ในชุดที่กำหนด ---
        if c.get("category") and c["category"] not in VALID_CATEGORIES:
            issues.append(f"category ไม่ถูกต้อง: {code} -> {c['category']!r}")
        if c.get("type") and c["type"] not in VALID_TYPES:
            issues.append(f"type ไม่ถูกต้อง: {code} -> {c['type']!r}")

        # --- กฎ 4: ความสอดคล้องของ year=0 กับ flexible_year_semester ---
        y, s = str(c.get("year")), str(c.get("semester"))
        if y == "0" and s == "0" and not c.get("flexible_year_semester"):
            issues.append(f"{code}: ปี/ภาค = 0 แต่ไม่ได้ระบุ flexible_year_semester")
        if y not in ("0", "None") and c.get("flexible_year_semester"):
            issues.append(f"{code}: ระบุปีชัดเจนแล้ว ไม่ควรมี flexible_year_semester")

        # --- กฎ 5: prerequisite ต้องอ้างถึงวิชาที่มีอยู่จริง ---
        # เรียกว่า referential integrity — หลักการเดียวกับ foreign key ในฐานข้อมูล
        pre = (c.get("prerequisite") or "").strip()
        if pre and pre != "ไม่มี":
            for pc in re.findall(r"\d{8}", pre):
                if pc not in codes:
                    issues.append(f"{code}: prerequisite {pc} ไม่มีอยู่ในรายการวิชา "
                                  f"--> อาจอ่านรหัสผิด หรืออ่านตกวิชานั้น")

        # --- สะสมหน่วยกิตรายภาค ---
        m = re.match(r"(\d+)\(", cr)
        if m and y not in ("0", "None") and s not in ("0", "None"):
            n_credit = int(m.group(1))
            credits_by_term[f"{y}/{s}"] += n_credit
            if n_credit >= BLOCK_COURSE_CREDITS:
                has_block_course.add(f"{y}/{s}")

    # --- ตรวจว่าจำนวนหน่วยกิตต่อภาคสมเหตุสมผลไหม ---
    # ระเบียบทั่วไปกำหนดให้ลงได้ 9-22 หน่วยกิตต่อภาค
    # ถ้าน้อยกว่ามาก แปลว่า "อ่านตกวิชา" ในภาคนั้น
    #
    # ⚠️ ข้อยกเว้นสำคัญ: ภาคที่ลงสหกิจศึกษา
    #    แผนสหกิจของ DSBA กำหนดให้ปี 4 ภาค 2 ลงสหกิจศึกษาเพียงวิชาเดียว
    #    6 หน่วยกิต (0-35-0) คือไปทำงานเต็มเวลาทั้งภาค
    #    ถ้าไม่ยกเว้น กฎนี้จะแจ้งเตือน ground truth ของจริงทันที
    for term, tot in sorted(credits_by_term.items()):
        if tot < 9 and term not in has_block_course:
            issues.append(f"ภาค {term} มีแค่ {tot} หน่วยกิต — น่าจะอ่านตกวิชา")
        elif tot > 25:
            issues.append(f"ภาค {term} มีถึง {tot} หน่วยกิต — น่าจะมีวิชาซ้ำ")

    return {
        "ok": len(issues) == 0,
        "n_courses": len(courses),
        "n_duplicate_keys": sum(1 for v in dup.values() if v > 1),
        "credits_by_term": dict(sorted(credits_by_term.items())),
        "total_credits_fixed_terms": sum(credits_by_term.values()),
        "issues": issues,
    }


# ==============================================================================
#  ส่วนที่ 11 — ประเมินผลเทียบ GROUND TRUTH
# ==============================================================================


def clean_gt(gt: dict) -> list[dict]:
    """
    ทำความสะอาด ground truth ก่อนใช้งาน
     ก่อนใช้ ground truth ต้อง "ตรวจ ground truth" เสียก่อน
             และเกณฑ์การกรองต้องแคบที่สุดเท่าที่จะทำได้
    """
    kept, dropped = [], []
    for c in gt.get("courses") or []:
        # เกณฑ์เดียว: ต้องมีชื่อวิชาภาษาไทย  ถ้าไม่มี = ไม่ใช่แถวรายวิชา
        if c.get("name_th"):
            kept.append(c)
        else:
            dropped.append(str(c.get("code"))[:40])
    if dropped:
        print(f"  (กรองแถวที่ไม่ใช่รายวิชาออกจาก ground truth {len(dropped)} แถว)")
    return kept


def key_strict(c: dict) -> str:
    """
    กุญแจเข้ม: รหัส + ปี + ภาค + ชื่อไทย

    ทำไมต้องมีชื่อด้วย? เพราะรหัส placeholder "06026xxx" ปรากฏ 2 แถว
    ในภาคเดียวกัน (วิชาเลือกกลุ่มวิทยาการข้อมูล 1 และ 2)
    ถ้าใช้แค่รหัส+ปี+ภาค ทั้งสองแถวจะชนกัน --> จับคู่ผิดตัว
    """
    return "|".join([
        M.normalize(c.get("code"), "strict"),
        M.normalize(c.get("year"), "strict"),
        M.normalize(c.get("semester"), "strict"),
        M.normalize(c.get("name_th"), "strict"),
    ])


def key_loose(c: dict) -> str:
    """
    กุญแจหลวม: รหัส + ปี + ภาค (ไม่สนชื่อ)

    ใช้ในรอบที่สอง เพื่อเก็บตกกรณีที่โมเดลอ่านชื่อผิดไปนิดหน่อย
    ถ้าไม่มีรอบนี้ วิชาที่อ่านชื่อผิด 1 ตัวอักษรจะถูกนับเป็น
    "ตกแถว 1 + แต่งเกิน 1" ทั้งที่โมเดลอ่านเจอจริง
    --> ทำให้ recall ดูแย่เกินความเป็นจริง
    """
    return "|".join([
        M.normalize(c.get("code"), "strict"),
        M.normalize(c.get("year"), "strict"),
        M.normalize(c.get("semester"), "strict"),
    ])


def evaluate(pred: dict, gt: dict) -> tuple[dict, dict]:
    S = M.FieldStat
    stats: dict[str, M.FieldStat] = {
        "code":      S("รหัสวิชา"),
        "name_th":   S("ชื่อวิชา (ไทย) ⭐"),
        "name_en":   S("ชื่อวิชา (อังกฤษ) ⭐"),
        "credits":   S("หน่วยกิต"),
        "year_sem":  S("ปี/ภาค"),
        "category":  S("หมวดวิชา"),
        "ctype":     S("บังคับ/เลือก"),
        "prereq":    S("วิชาบังคับก่อน"),
        "flexible":  S("ปี/ภาคยืดหยุ่น"),
    }

    g_courses = clean_gt(gt)
    p_courses = pred.get("courses") or []

    # จับคู่สองรอบ: เข้มก่อน (รวมชื่อ) แล้วผ่อน (เฉพาะรหัส+ปี+ภาค)
    align = M.align_multipass(g_courses, p_courses, [key_strict, key_loose])

    for g, p in align.matched:
        k = f"{g.get('code')}"

        # --- รหัสวิชา: ไม่วัด WER (เป็นตัวเลข ไม่มีคำ) ---
        stats["code"].add(g.get("code"), p.get("code"), k, track_wer=False)

        # ⭐ ชื่อวิชา: กลุ่ม B วัด WER ได้ เพราะ GT คงช่องว่างไว้
        #    - ภาษาไทย ใช้ pythainlp/newmm ตัดคำ
        #    - ภาษาอังกฤษ ตัดด้วยช่องว่าง
        #    ⚠️ name_en ใน GT มี \n ฝังอยู่ (ชื่อยาวถูกตัดบรรทัดใน PDF)
        #       normalize ระดับ basic ขึ้นไปจะยุบ \n เป็นช่องว่างให้อัตโนมัติ
        stats["name_th"].add(g.get("name_th"), p.get("name_th"), k, track_wer=True)
        stats["name_en"].add(g.get("name_en"), p.get("name_en"), k, track_wer=True)

        stats["credits"].add(g.get("credits"), p.get("credits"), k, track_wer=False)
        stats["year_sem"].add(f"{g.get('year')}/{g.get('semester')}",
                              f"{p.get('year')}/{p.get('semester')}",
                              k, track_wer=False)
        stats["category"].add(g.get("category"), p.get("category"), k, track_wer=False)
        stats["ctype"].add(g.get("type"), p.get("type"), k, track_wer=False)
        stats["prereq"].add(g.get("prerequisite"), p.get("prerequisite"),
                            k, track_wer=False)
        stats["flexible"].add(g.get("flexible_year_semester"),
                              p.get("flexible_year_semester"), k, track_wer=False)

    # --- วิชาที่โมเดลอ่านตก: นับเป็น deletion เต็มจำนวน ---
    # ถ้าไม่นับ โมเดลที่อ่านแค่ 10 วิชาจาก 91 วิชาจะได้ CER ต่ำเตี้ย
    # ทั้งที่ใช้งานจริงไม่ได้เลย
    for g in align.missed:
        k = f"{g.get('code')} [ตกแถว]"
        stats["code"].add(g.get("code"), "", k, track_wer=False)
        stats["name_th"].add(g.get("name_th"), "", k, track_wer=True)
        stats["name_en"].add(g.get("name_en"), "", k, track_wer=True)
        stats["credits"].add(g.get("credits"), "", k, track_wer=False)
        stats["year_sem"].add(f"{g.get('year')}/{g.get('semester')}", "",
                              k, track_wer=False)
        stats["category"].add(g.get("category"), "", k, track_wer=False)
        stats["ctype"].add(g.get("type"), "", k, track_wer=False)

    align_summary = {
        "matched": len(align.matched),
        "missed": len(align.missed),
        "spurious": len(align.spurious),
        "precision": round(align.precision, 4),
        "recall": round(align.recall, 4),
        "f1": round(align.f1, 4),
        "gt_total": len(g_courses),
        "pred_total": len(p_courses),
        "missed_codes": [g.get("code") for g in align.missed][:20],
        "spurious_codes": [p.get("code") for p in align.spurious][:20],
    }
    return stats, align_summary


# ==============================================================================
#  ส่วนที่ 12 — MAIN
# ==============================================================================


def run_pipeline(name: str, pages: list[bytes], outdir: Path,
                 pdf_path: str | None, page_spec: str | None) -> dict | None:
    print(f"\n{'─' * 70}")
    print(f"  PIPELINE: {name}")
    print(f"{'─' * 70}")
    t0 = time.time()
    try:
        if name == "baseline":
            data = pipeline_baseline(pages)
        elif name == "text":
            if not pdf_path:
                print("  ⚠ pipeline 'text' ใช้ได้กับไฟล์ PDF เท่านั้น")
                return None
            data = pipeline_text(pdf_path, page_spec)
        elif name == "vlm":
            data = pipeline_vlm(pages, outdir)
        else:
            raise ValueError(name)
    except Exception as e:
        print(f"  ❌ {name} ล้มเหลว: {e}")
        return None

    if not data or not data.get("courses"):
        print(f"  ⚠ {name} ไม่ได้ผลลัพธ์")
        return None

    data["_meta"] = {
        "pipeline": name,
        "elapsed_sec": round(time.time() - t0, 1),
        "models": {"ocr": MODEL_OCR, "text": MODEL_TEXT},
        "dpi": DPI, "pages_per_chunk": PAGES_PER_CHUNK,
    }
    path = outdir / f"pred_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ บันทึก {path}  ({len(data['courses'])} วิชา, "
          f"{data['_meta']['elapsed_sec']} วิ)")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Lab 7B — สกัดแผนการศึกษาจากเล่มหลักสูตร ด้วย LLM บนเครื่อง")
    ap.add_argument("-i", "--input", help="ไฟล์เล่มหลักสูตร (.pdf/.png)")
    ap.add_argument("-g", "--gt", help="ไฟล์ ground truth (.json)")
    ap.add_argument("-o", "--out", default="output")
    ap.add_argument("-p", "--pipeline", default="all",
                    choices=["all", "baseline", "text", "vlm"])
    ap.add_argument("--pages", help='เลือกเฉพาะบางหน้า เช่น "42-58" หรือ "3,7,10-12"')
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--eval-only", metavar="PRED_JSON")
    args = ap.parse_args()

    if args.check:
        sys.exit(0 if check_environment() else 1)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.eval_only:
        if not args.gt:
            raise SystemExit("❌ --eval-only ต้องระบุ --gt ด้วย")
        pred = json.loads(Path(args.eval_only).read_text(encoding="utf-8"))
        gt = json.loads(Path(args.gt).read_text(encoding="utf-8"))
        stats, align = evaluate(pred, gt)
        M.print_table(stats, f"ผลประเมิน: {Path(args.eval_only).name}")
        print(f"\n  จับคู่วิชา: เจอ {align['matched']}/{align['gt_total']} "
              f"| ตก {align['missed']} | แต่งเกิน {align['spurious']}")
        print(f"  P={align['precision']:.3f}  R={align['recall']:.3f}  "
              f"F1={align['f1']:.3f}")
        if align["missed_codes"]:
            print(f"  วิชาที่อ่านตก: {', '.join(map(str, align['missed_codes'][:10]))}")
        M.print_errors(stats)
        return

    if not args.input:
        raise SystemExit("❌ ต้องระบุ --input")

    print("\n" + "=" * 70)
    print("  Lab 7B — สกัดแผนการศึกษา ด้วย LLM ที่รันบนเครื่องตัวเอง")
    print("=" * 70)
    assert_offline()

    print(f"\nเตรียมข้อมูลจาก: {args.input}")
    pages = load_pages(args.input, args.pages)

    if args.pipeline == "all":
        names = ["text", "vlm"] if SKIP_BASELINE else ["baseline", "text", "vlm"]
        if SKIP_BASELINE:
            print("\n(ข้าม pipeline baseline ตามค่า LAB7_SKIP_BASELINE=1)")
    else:
        names = [args.pipeline]

    results: dict[str, dict] = {}
    for n in names:
        r = run_pipeline(n, pages, outdir, args.input, args.pages)
        if r:
            results[n] = r

    # ---------- ตรวจความสอดคล้องภายใน ----------
    print("\n" + "=" * 70)
    print("  ตรวจความสอดคล้องภายใน (ไม่ใช้เฉลย)")
    print("=" * 70)
    for n, data in results.items():
        v = verify_internal(data)
        print(f"\n  {'✓' if v['ok'] else '✗'} {n}: {v['n_courses']} วิชา, "
              f"รวม {v['total_credits_fixed_terms']} หน่วยกิต (เฉพาะภาคที่ระบุชัด)")
        for msg in v["issues"][:6]:
            print(f"      • {msg}")
        if len(v["issues"]) > 6:
            print(f"      ... และอีก {len(v['issues']) - 6} รายการ")

    # ---------- เทียบ ground truth ----------
    if not args.gt:
        print("\n(ไม่ได้ระบุ --gt จึงข้ามการเทียบกับเฉลย)")
        return

    gt = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    csv_path = outdir / "comparison.csv"
    combined: dict[str, Any] = {}
    first = True

    for n, data in results.items():
        stats, align = evaluate(data, gt)
        M.print_table(stats, f"PIPELINE = {n}")
        print(f"  จับคู่วิชา: เจอ {align['matched']}/{align['gt_total']} "
              f"| ตก {align['missed']} | แต่งเกิน {align['spurious']}   "
              f"P={align['precision']:.3f} R={align['recall']:.3f} "
              f"F1={align['f1']:.3f}")
        M.print_errors(stats, limit=2)

        d = M.stats_to_dict(stats)
        d["alignment"] = align
        d["internal_check"] = verify_internal(data)
        combined[n] = d

        tmp = outdir / f"_tmp_{n}.csv"
        M.save_csv(stats, str(tmp), extra={"pipeline": n})
        lines = tmp.read_text(encoding="utf-8-sig").splitlines()
        with open(csv_path, "w" if first else "a", encoding="utf-8-sig") as f:
            f.write("\n".join(lines if first else lines[1:]) + "\n")
        tmp.unlink()
        first = False

    (outdir / "evaluation.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n✓ เสร็จสิ้น")
    print(f"  ตารางเปรียบเทียบ (เปิดใน Excel): {csv_path}")
    print(f"  ผลละเอียด: {outdir / 'evaluation.json'}")


if __name__ == "__main__":
    main()
