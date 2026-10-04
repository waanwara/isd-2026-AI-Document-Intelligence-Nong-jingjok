"""KatRAG API Service — FastAPI application (R19.1, R19.2, R19.3, R19.8, R19.9).

Endpoints:
- POST /ask          — ส่งคำถาม, คืนคำตอบพร้อม citations
- GET  /documents    — รายการเอกสารพร้อมเวอร์ชัน (≤500 รายการ)
- GET  /pages/{id}   — หน้าเอกสารตาม citation ID พร้อม bbox
- GET  /traces/{id}  — query_trace ตาม request_id

R19.2: bind listener ที่ 127.0.0.1
R19.3: คืน 422 พร้อมรายชื่อ field ที่ผิดทุก field
R19.8: คืน 404 เมื่อ identifier ไม่มีอยู่
R19.9: ยุติคำขอที่เกิน 120 วินาทีพร้อมบันทึก trace
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from katrag.api.schemas import (
    AskRequest,
    AskResponse,
    BBoxItem,
    CitationItem,
    DocumentItem,
    DocumentsResponse,
    ErrorDetail,
    PageResponse,
    TraceResponse,
    ValidationErrorResponse,
)
from katrag.query.pipeline import answer_question

#: หลักสูตรที่รับได้ — ผู้ใช้ต้องเลือกก่อนถาม (ไม่มีตัวเลือก "ทุกหลักสูตร"
#: เพราะข้อมูลหลักสูตรผูกกับสาขา คำถามที่ไม่ระบุสาขาจึงไม่มีคำตอบเดียวที่ถูก)
VALID_PROGRAMS = frozenset({"IT", "DSBA", "AIT", "BIT", "AITBA"})

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _db_path() -> pathlib.Path:
    """ตำแหน่งฐานข้อมูล provenance store."""
    return _PROJECT_ROOT / "artifacts" / "katrag.sqlite3"


# ══════════════════════════════════════════════════════════════════════
# Application factory
# ══════════════════════════════════════════════════════════════════════

# ── Lazy singletons (index / LLM) — โหลดครั้งเดียวแล้วแคชใน app.state ──


def _embedding_stack_available() -> bool:
    """True ถ้า torch + transformers ติดตั้งอยู่ (จำเป็นต่อการ encode คำถามด้วย bge-m3).

    ถ้าไม่มี ให้ข้าม dense/course index แล้วใช้ lexical + structured path แทน
    แทนที่จะให้ทุกคำถามล้มด้วย ModuleNotFoundError
    """
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


def _get_course_index(app: FastAPI, db_path: Any) -> Any:
    """โหลด CourseSemanticIndex ครั้งเดียวแล้วแคช (None ถ้าไม่มี embedding)."""
    cached = getattr(app.state, "course_index", "unset")
    if cached != "unset":
        return cached
    if not _embedding_stack_available():
        app.state.course_index = None
        return None
    try:
        from katrag.query.course_semantic import CourseSemanticIndex

        idx = CourseSemanticIndex(db_path)
        app.state.course_index = idx if idx.load() > 0 else None
    except Exception:
        app.state.course_index = None
    return app.state.course_index


def _get_dense_index(app: FastAPI, db_path: Any) -> Any:
    """โหลด dense index ครั้งเดียวแล้วแคช (None ถ้าไม่มี embedding → ใช้ lexical)."""
    cached = getattr(app.state, "dense_index", "unset")
    if cached != "unset":
        return cached
    if not _embedding_stack_available():
        app.state.dense_index = None
        return None
    try:
        from katrag.index.dense_search import DenseSearchIndex

        idx = DenseSearchIndex(db_path)
        app.state.dense_index = idx if idx.load() > 0 else None
    except Exception:
        app.state.dense_index = None
    return app.state.dense_index


def _get_llm(app: FastAPI) -> Any:
    """โหลด Typhoon LLM client ครั้งเดียวแล้วแคช (None ถ้า config ไม่พร้อม)."""
    cached = getattr(app.state, "llm", "unset")
    if cached != "unset":
        return cached
    try:
        from dotenv import load_dotenv

        from katrag.query.typhoon_llm import TyphoonLLM

        load_dotenv(_PROJECT_ROOT / ".env")
        app.state.llm = TyphoonLLM()
    except Exception:
        app.state.llm = None
    return app.state.llm


# Default config values (used when config module is not available)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_MAX_DOCUMENTS = 500
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_QUESTION_CHARS = 2000


def create_app(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    max_question_chars: int = DEFAULT_MAX_QUESTION_CHARS,
) -> FastAPI:
    """สร้าง FastAPI app instance พร้อม config.

    Args:
        host: bind address (R19.2 — loopback only)
        port: listen port
        max_documents: จำนวนเอกสารสูงสุดใน GET /documents response
        request_timeout_seconds: timeout ต่อ request (R19.9)
        max_question_chars: ความยาวคำถามสูงสุด (R19.3)
    """
    app = FastAPI(
        title="KatRAG API",
        version="0.1.0",
        description="Curriculum Q&A RAG API — loopback only",
    )

    # Store config in app state
    app.state.host = host
    app.state.port = port
    app.state.max_documents = max_documents
    app.state.request_timeout_seconds = request_timeout_seconds
    app.state.max_question_chars = max_question_chars

    # In-memory stores (replaced by real services when integrated)
    app.state.trace_store: dict[str, dict[str, Any]] = {}
    app.state.documents_store: list[dict[str, Any]] = []
    app.state.citations_store: dict[str, dict[str, Any]] = {}

    # ── Validation error handler (R19.3) ──────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """คืน 422 พร้อมรายชื่อ field ที่ผิดทุก field (R19.3)."""
        errors: list[dict[str, Any]] = []
        for error in exc.errors():
            loc_parts: list[str] = []
            for part in error.get("loc", []):
                loc_parts.append(str(part))
            errors.append(
                {
                    "loc": loc_parts,
                    "msg": error.get("msg", ""),
                    "type": error.get("type", ""),
                }
            )
        return JSONResponse(status_code=422, content={"detail": errors})

    # ── Timeout middleware (R19.9) ────────────────────────────────────

    @app.middleware("http")
    async def timeout_middleware(request: Request, call_next: Any) -> Any:
        """ยุติคำขอที่เกิน request_timeout_seconds พร้อมบันทึก trace."""
        timeout = app.state.request_timeout_seconds
        start_time = time.time()

        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            # บันทึก timeout trace
            request_id = str(uuid.uuid4())
            app.state.trace_store[request_id] = {
                "request_id": request_id,
                "question": "(timeout)",
                "question_level": "unknown",
                "versions_resolved": "",
                "evidence_nodes": 0,
                "citations_sent": 0,
                "citations_passed": 0,
                "citations_removed": 0,
                "unsupported_claims": 0,
                "answer_generation_time_seconds": 0.0,
                "ocr_invocations": 0,
                "preprocessor_invocations": 0,
                "adjudicator_invocations": 0,
                "total_time_seconds": elapsed,
                "halt_reason": "request_timeout",
                "cache_hit": False,
                "created_at_ns": time.time_ns(),
            }
            return JSONResponse(
                status_code=504,
                content={
                    "detail": "Request timeout exceeded",
                    "request_id": request_id,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )

    # ── POST /ask (R19.1) ─────────────────────────────────────────────

    @app.post("/ask", response_model=AskResponse)
    async def ask(body: AskRequest) -> AskResponse:
        """ส่งคำถาม, คืนคำตอบพร้อม citations.

        ชั้นนี้ทำแค่งานของ HTTP: ตรวจ request → เรียก pipeline → ประกอบ response
        ตรรกะการตอบทั้งหมดอยู่ใน `katrag.query.pipeline`
        """
        start_time = time.time()
        request_id = str(uuid.uuid4())

        question = body.question.strip()
        if len(question) < 1 or len(question) > app.state.max_question_chars:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "question"],
                        "msg": f"ความยาวคำถามต้องอยู่ในช่วง 1 ถึง {app.state.max_question_chars} อักขระ",
                        "type": "value_error",
                    }
                ],
            )

        selected_program = (body.program or "").strip().upper()
        if selected_program not in VALID_PROGRAMS:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "program"],
                        "msg": (
                            "ต้องเลือกหลักสูตรก่อนถาม — ค่าที่รับได้: "
                            + ", ".join(sorted(VALID_PROGRAMS))
                        ),
                        "type": "value_error",
                    }
                ],
            )

        db_path = _db_path()
        try:
            result = answer_question(
                db_path,
                question,
                selected_program,
                dense_index=_get_dense_index(app, db_path),
                course_index=_get_course_index(app, db_path),
                llm=_get_llm(app),
            )
            answer_text = result.answer
            citations = [
                CitationItem(
                    citation_id=c.citation_id,
                    document_id=c.document_id,
                    page=c.page,
                    heading=c.heading,
                )
                for c in result.citations
            ]
            versions_resolved = result.versions_resolved
            sql_query = result.sql_query
            # เก็บ citation ไว้ให้ GET /pages/{citation_id} เรียกดูได้
            for c in result.citations:
                app.state.citations_store[c.citation_id] = {
                    "citation_id": c.citation_id,
                    "document_id": c.document_id,
                    "page": c.page,
                    "heading": c.heading,
                    "bbox": None,
                    "page_width": 0.0,
                    "page_height": 0.0,
                    "chunk_text": c.chunk_text,
                }
        except Exception as exc:
            answer_text = f"เกิดข้อผิดพลาด: {type(exc).__name__}: {exc}"
            citations = []
            versions_resolved = []
            sql_query = ""

        elapsed = time.time() - start_time

        app.state.trace_store[request_id] = {
            "request_id": request_id,
            "question": question,
            "question_level": "L1",
            "versions_resolved": "|".join(versions_resolved),
            "evidence_nodes": len(citations),
            "citations_sent": len(citations),
            "citations_passed": len(citations),
            "citations_removed": 0,
            "unsupported_claims": 0,
            "answer_generation_time_seconds": elapsed,
            "ocr_invocations": 0,
            "preprocessor_invocations": 0,
            "adjudicator_invocations": 0,
            "total_time_seconds": elapsed,
            "halt_reason": "no_new_evidence",
            "cache_hit": False,
            "created_at_ns": time.time_ns(),
        }

        return AskResponse(
            request_id=request_id,
            answer=answer_text,
            citations=citations,
            versions_resolved=versions_resolved,
            citations_removed=0,
            unsupported_claims=0,
            total_time_seconds=round(elapsed, 4),
            sql_query=sql_query,
        )

    # ── GET /documents (R19.1) ────────────────────────────────────────

    @app.get("/documents", response_model=DocumentsResponse)
    async def list_documents() -> DocumentsResponse:
        """รายการเอกสารพร้อมเวอร์ชัน (≤500 รายการ)."""
        docs = app.state.documents_store[: app.state.max_documents]
        items = [
            DocumentItem(
                document_id=d["document_id"],
                filename=d.get("filename", ""),
                page_count=d.get("page_count", 0),
                versions=d.get("versions", []),
            )
            for d in docs
        ]
        return DocumentsResponse(
            documents=items,
            total=len(app.state.documents_store),
        )

    # ── GET /pages/{citation_id} (R19.1, R19.8) ──────────────────────

    @app.get("/pages/{citation_id}", response_model=PageResponse)
    async def get_page(citation_id: str) -> PageResponse:
        """หน้าเอกสารตาม citation ID พร้อม bbox.

        Returns 404 เมื่อ citation_id ไม่มีอยู่ (R19.8).
        """
        citation_data = app.state.citations_store.get(citation_id)
        if citation_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"citation_id '{citation_id}' ไม่พบในระบบ",
            )

        bbox_raw = citation_data.get("bbox")
        bbox = (
            BBoxItem(
                x0=bbox_raw["x0"],
                y0=bbox_raw["y0"],
                x1=bbox_raw["x1"],
                y1=bbox_raw["y1"],
            )
            if bbox_raw
            else None
        )

        return PageResponse(
            citation_id=citation_id,
            document_id=citation_data["document_id"],
            page=citation_data["page"],
            heading=citation_data.get("heading", ""),
            bbox=bbox,
            page_width=citation_data.get("page_width", 0.0),
            page_height=citation_data.get("page_height", 0.0),
            chunk_text=citation_data.get("chunk_text", ""),
        )

    # ── GET /traces/{request_id} (R19.1, R19.8) ──────────────────────

    @app.get("/traces/{request_id}", response_model=TraceResponse)
    async def get_trace(request_id: str) -> TraceResponse:
        """query_trace ตาม request_id.

        Returns 404 เมื่อ request_id ไม่มีอยู่ (R19.8).
        """
        trace_data = app.state.trace_store.get(request_id)
        if trace_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"request_id '{request_id}' ไม่พบในระบบ",
            )

        return TraceResponse(**trace_data)

    # ── Warmup ตอน startup: โหลดโมเดล/ดัชนีล่วงหน้า (R: latency คำขอแรก) ──
    # ต้นเหตุคำขอแรกช้าคือโมเดล embedding BGE-M3 (หลาย GB) ถูก lazy-load ตอน
    # encode query แรก การ warmup ย้าย latency มาไว้ตอน server ขึ้น เพื่อให้
    # คำขอ /ask แรกเร็วเท่าคำขอถัดไป
    # ปิดได้ด้วย KATRAG_SKIP_WARMUP=1 (เช่น ตอน dev ที่ไม่อยากรอ)
    @app.on_event("startup")
    async def _warmup() -> None:
        if os.environ.get("KATRAG_SKIP_WARMUP") == "1":
            return
        try:
            db_path = _db_path()
            # preload เวกเตอร์ dense/course เข้า app.state
            _get_dense_index(app, db_path)
            _get_course_index(app, db_path)
            # สร้าง LLM client ล่วงหน้า (เบา แต่ทำให้ .env ถูกโหลดครบ)
            _get_llm(app)
            # จุดสำคัญ: บังคับโหลดน้ำหนัก BGE-M3 เข้า RAM/GPU ตอนนี้
            # (นี่คือส่วนที่กินเวลาจริงของคำขอแรก)
            from katrag.index import bge_encoder

            bge_encoder.encode_one("warmup")
        except Exception:
            # warmup พลาดไม่ควรทำให้ server ไม่ขึ้น — ค่อย lazy-load ตามเดิม
            pass

    # ── Static files: serve web/ directory at root ──────────────────
    web_dir = _PROJECT_ROOT / "web"
    if web_dir.is_dir():

        @app.get("/")
        async def serve_index():
            return FileResponse(web_dir / "index.html")

        app.mount("/", StaticFiles(directory=str(web_dir)), name="static")

    return app


# ══════════════════════════════════════════════════════════════════════
# Default app instance
# ══════════════════════════════════════════════════════════════════════

def _app_kwargs_from_config() -> dict[str, Any]:
    """อ่านค่า [api] จาก katrag.toml — fallback เป็นค่า DEFAULT ถ้าโหลดไม่ได้."""
    try:
        from katrag.config import load_config

        api = load_config().api
        return {
            "host": api.host,
            "port": api.port,
            "max_documents": api.max_documents_per_response,
            "request_timeout_seconds": api.request_timeout_seconds,
            "max_question_chars": api.max_question_chars,
        }
    except Exception:
        return {}


app = create_app(**_app_kwargs_from_config())


# ══════════════════════════════════════════════════════════════════════
# Entrypoint — สำหรับ `python -m katrag.api.service`
# ══════════════════════════════════════════════════════════════════════


def main() -> None:  # pragma: no cover
    """Run API server with uvicorn — binds to 127.0.0.1 (R19.2)."""
    import uvicorn

    try:
        from katrag.config import load_config

        config = load_config()
        host = config.api.host
        port = config.api.port
    except Exception:
        host = DEFAULT_HOST
        port = DEFAULT_PORT

    uvicorn.run(
        "katrag.api.service:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
