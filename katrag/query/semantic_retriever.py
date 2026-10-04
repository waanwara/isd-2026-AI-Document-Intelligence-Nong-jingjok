"""Semantic Retriever — Hybrid (lexical + dense) ด้วย Reciprocal Rank Fusion.

รวมผลจาก:
1. Lexical retriever เดิม (katrag/query/retriever.py) — substring/heuristic
2. Dense search ใหม่ (katrag/index/dense_search.py) — cosine similarity

ด้วย RRF: score(d) = w_lex/(k+rank_lex) + w_dense/(k+rank_dense)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from katrag.query.retriever import (
    RetrievedChunk,
    detect_program,
    detect_year,
    search as lexical_search,
)
from katrag.index.dense_search import DenseSearchIndex, DenseSearchHit


@dataclass
class HybridHit:
    chunk_id: int
    page_number: int
    heading: str
    text: str
    program: str
    curriculum_year: int
    edition_status: str
    fused_score: float
    lexical_rank: int | None
    dense_rank: int | None
    # เอกสารต้นทาง — จำเป็นสำหรับ citation ที่ตรวจย้อนกลับได้
    # (เดิมไม่มี ทำให้ service ใส่ chunk_id ลงช่อง document_id ของ citation)
    document_id: str = ""


# RRF parameters
RRF_K = 60
LEXICAL_WEIGHT = 0.5
DENSE_WEIGHT = 0.5


def hybrid_search(
    conn: sqlite3.Connection,
    dense_index: DenseSearchIndex,
    question: str,
    *,
    limit: int = 10,
    lexical_top_k: int = 30,
    dense_top_k: int = 30,
) -> list[HybridHit]:
    """Hybrid retrieval: lexical + dense RRF fusion."""

    # Detect program/year for version filtering
    program = detect_program(question)
    year = detect_year(question)
    version_filter = (program, year) if program and year else (program, 0) if program else None

    # คำถามที่ระบุเวอร์ชันชัด (เช่น "IT 2563 กับ 2568", "AIT 2566 กับ IT 2565")
    # ต้องค้นทุกเวอร์ชันนั้น ไม่ใช่แค่เวอร์ชันปัจจุบันของหลักสูตรแรก
    from katrag.query.structured_query import detect_versions

    named = detect_versions(conn, question)
    if named:
        lexical_hits = lexical_search(
            conn, question, limit=lexical_top_k, version_ids=[v[0] for v in named]
        )
        per_version = max(5, dense_top_k // len(named))
        dense_hits = []
        for _vid, prog, yr in named:
            dense_hits.extend(
                dense_index.search(question, version_filter=(prog, yr), top_k=per_version)
            )
        dense_hits.sort(key=lambda h: -h.score)
        return _fuse(conn, lexical_hits, dense_hits, limit)

    # 1. Lexical search
    lexical_hits = lexical_search(conn, question, limit=lexical_top_k)

    # 2. Dense search
    dense_filter = None
    if program:
        # ใช้ current version ของ program
        conn.row_factory = sqlite3.Row
        ver_row = conn.execute(
            "SELECT curriculum_year FROM curriculum_version WHERE program=? AND edition_status='current' LIMIT 1",
            (program,),
        ).fetchone()
        if ver_row:
            dense_filter = (program, ver_row["curriculum_year"])

    dense_hits = dense_index.search(question, version_filter=dense_filter, top_k=dense_top_k)
    return _fuse(conn, lexical_hits, dense_hits, limit)


def _fuse(
    conn: sqlite3.Connection,
    lexical_hits: Sequence[RetrievedChunk],
    dense_hits: Sequence[DenseSearchHit],
    limit: int,
) -> list[HybridHit]:
    """รวมผล lexical + dense ด้วย RRF แล้วเติม document_id."""
    # 3. RRF Fusion
    # สร้าง rank map
    lex_rank_map: dict[int, int] = {}
    lex_data: dict[int, RetrievedChunk] = {}
    for rank, hit in enumerate(lexical_hits, 1):
        lex_rank_map[hit.chunk_id] = rank
        lex_data[hit.chunk_id] = hit

    dense_rank_map: dict[int, int] = {}
    dense_data: dict[int, DenseSearchHit] = {}
    for rank, hit in enumerate(dense_hits, 1):
        dense_rank_map[hit.chunk_id] = rank
        dense_data[hit.chunk_id] = hit

    all_ids = set(lex_rank_map.keys()) | set(dense_rank_map.keys())

    scored: list[HybridHit] = []
    for cid in all_ids:
        lex_rank = lex_rank_map.get(cid)
        dns_rank = dense_rank_map.get(cid)

        score = 0.0
        if lex_rank is not None:
            score += LEXICAL_WEIGHT / (RRF_K + lex_rank)
        if dns_rank is not None:
            score += DENSE_WEIGHT / (RRF_K + dns_rank)
        # Bonus: chunk ที่ทั้ง lexical + dense เห็นตรง → ย่อม relevant มาก
        if lex_rank is not None and dns_rank is not None:
            score *= 1.3

        # Get metadata from whichever source has it
        if cid in lex_data:
            h = lex_data[cid]
            scored.append(HybridHit(
                chunk_id=cid, page_number=h.page_number, heading=h.heading,
                text=h.text, program=h.program, curriculum_year=h.curriculum_year,
                edition_status=h.edition_status, fused_score=score,
                lexical_rank=lex_rank, dense_rank=dns_rank,
            ))
        elif cid in dense_data:
            h = dense_data[cid]
            scored.append(HybridHit(
                chunk_id=cid, page_number=h.page_number, heading=h.heading,
                text=h.text, program=h.program, curriculum_year=h.curriculum_year,
                edition_status=h.edition_status, fused_score=score,
                lexical_rank=lex_rank, dense_rank=dns_rank,
            ))

    # Sort by fused score descending, tie-break by chunk_id
    scored.sort(key=lambda x: (-x.fused_score, x.chunk_id))
    top = scored[:limit]

    # เติม document_id ให้ผลลัพธ์ที่เลือกแล้ว (query เดียว)
    if top:
        conn.row_factory = sqlite3.Row
        ids = [h.chunk_id for h in top]
        ph = ",".join("?" * len(ids))
        doc_map = {
            r["chunk_id"]: r["document_id"]
            for r in conn.execute(
                f"SELECT chunk_id, document_id FROM chunk WHERE chunk_id IN ({ph})", ids
            )
        }
        for h in top:
            h.document_id = doc_map.get(h.chunk_id, "")

    return top
