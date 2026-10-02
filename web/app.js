/**
 * Jingjok-Thorius Web UI — vanilla JS frontend
 *
 * Features:
 * - ส่งคำถามผ่าน POST /ask
 * - แสดงคำตอบพร้อม citations (แบบ chip คลิกได้)
 * - คลิก citation → GET /pages/{citation_id} แสดงหน้าเอกสาร
 * - หัวข้อยอดฮิต (quick questions) — คลิกแล้วถามทันที
 * - คัดลอกคำตอบ / อ่านออกเสียง / ให้ feedback
 */

"use strict";

const API_BASE = ""; // same origin — served by FastAPI
const MAX_CHARS = 800;

// ── DOM Elements ─────────────────────────────────────────────────────

const form = document.getElementById("ask-form");
const programSelect = document.getElementById("program-select");
const questionInput = document.getElementById("question-input");
const charCount = document.getElementById("char-count");
const askBtn = document.getElementById("ask-btn");
const clearBtn = document.getElementById("clear-btn");
const quickQuestions = document.getElementById("quick-questions");
const loading = document.getElementById("loading");
const errorDisplay = document.getElementById("error-display");
const answerSection = document.getElementById("answer-section");
const answerText = document.getElementById("answer-text");
const echoedQuestion = document.getElementById("echoed-question");
const versionBadge = document.getElementById("version-badge");
const timeBadge = document.getElementById("time-badge");
const validationStatus = document.getElementById("validation-status");
const removedCount = document.getElementById("removed-count");
const unsupportedCount = document.getElementById("unsupported-count");
const citationsList = document.getElementById("citations-list");
const sqlDetails = document.getElementById("sql-details");
const sqlCode = document.getElementById("sql-code");
const sqlSources = document.getElementById("sql-sources");
const sqlTime = document.getElementById("sql-time");
const copyBtn = document.getElementById("copy-btn");
const speakBtn = document.getElementById("speak-btn");
const feedbackUp = document.getElementById("feedback-up");
const feedbackDown = document.getElementById("feedback-down");
const pageViewer = document.getElementById("page-viewer");
const closeViewer = document.getElementById("close-viewer");
const viewerTitle = document.getElementById("viewer-title");
const viewerCanvas = document.getElementById("viewer-canvas");
const viewerInfo = document.getElementById("viewer-info");

const PROGRAM_ICONS = { IT: "💻", DSBA: "📊", AIT: "🤖", AITBA: "🎓", BIT: "🏫" };

const DOC_LABELS = {
    "a39d6db17ccc5cf4": "DSBA 2565",
    "344608973458106b": "DSBA 2560",
    "5dec80d93328c9fa": "IT 2565",
    "09c745bf0cd1fefe": "IT 2560",
    "71905b5244a14b94": "AIT 2566",
    "75085b1dd7523d89": "BIT 2565",
    "1ffe70b5db234caa": "BIT 2560",
    "bef8aad4da2cad3d": "ปร.ด. AITBA 2569",
    "430d1625db23e79b": "วท.ม. AITBA 2569",
    "a2bb37ed5f089453": "วท.ม. AITBA 2564",
    "272a77249680d878": "วท.ม. IT 2568",
    "0bb1dc8496421928": "วท.ม. IT 2563",
    "184978cecf5b14e7": "ปร.ด. IT 2566",
    "4d03ccad7edd646c": "ปร.ด. IT 2561",
};

function formatDocLabel(docId) {
    if (!docId) return "เอกสารหลักสูตร";
    if (DOC_LABELS[docId]) return DOC_LABELS[docId];
    if (docId.endsWith(".pdf")) {
        return docId.replace(/\.pdf$/i, "").replace(/^.*\//, "");
    }
    return docId;
}

// ── Character counter ────────────────────────────────────────────────

function updateCharCount() {
    const len = questionInput.value.length;
    charCount.textContent = `${len} / ${MAX_CHARS}`;
}
questionInput.addEventListener("input", updateCharCount);

// ── Quick questions ──────────────────────────────────────────────────

if (quickQuestions) {
    quickQuestions.addEventListener("click", (e) => {
        const chip = e.target.closest(".quick-chip");
        if (!chip) return;
        questionInput.value = chip.dataset.question || chip.textContent.trim();
        updateCharCount();
        form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true }));
    });
}

// ── Clear ────────────────────────────────────────────────────────────

if (clearBtn) {
    clearBtn.addEventListener("click", () => {
        questionInput.value = "";
        updateCharCount();
        hideElement(errorDisplay);
        hideElement(answerSection);
        questionInput.focus();
    });
}

// ── Form submission ──────────────────────────────────────────────────

form.addEventListener("submit", async(e) => {
    e.preventDefault();

    const question = questionInput.value.trim();
    if (!question) return;

    const selectedProgram = programSelect ? programSelect.value : "";
    if (!selectedProgram) {
        showError("กรุณาเลือกหลักสูตรก่อนถาม");
        if (programSelect) programSelect.focus();
        return;
    }

    hideElement(errorDisplay);
    hideElement(answerSection);
    showElement(loading);
    askBtn.disabled = true;

    const startedAt = performance.now();

    try {
        const response = await fetch(`${API_BASE}/ask`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, program: selectedProgram }),
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => null);
            if (response.status === 422 && errData && errData.detail) {
                const msgs = errData.detail.map((d) => `${d.loc.join(".")}: ${d.msg}`);
                throw new Error(`Validation error:\n${msgs.join("\n")}`);
            }
            throw new Error((errData && errData.detail) || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (typeof data.total_time_seconds !== "number") {
            data.total_time_seconds = (performance.now() - startedAt) / 1000;
        }
        renderAnswer(data, question, selectedProgram);
    } catch (err) {
        showError(err.message || "เกิดข้อผิดพลาด");
    } finally {
        hideElement(loading);
        askBtn.disabled = false;
    }
});

// ── Render answer ────────────────────────────────────────────────────

function renderAnswer(data, question, selectedProgram) {
    echoedQuestion.textContent = question;

    answerText.innerHTML = renderAnswerHtml(data.answer || "(ไม่มีคำตอบ)");

    // Version / program badge
    const icon = PROGRAM_ICONS[selectedProgram] || "";
    if (data.versions_resolved && data.versions_resolved.length > 0) {
        versionBadge.textContent = `${icon} ${data.versions_resolved.join(", ")}`.trim();
    } else {
        versionBadge.textContent = `${icon} ${selectedProgram || "ทุกเวอร์ชัน"}`.trim();
    }

    // Time badge
    timeBadge.textContent = `⏱ ${data.total_time_seconds.toFixed(2)}s`;

    // Validation status — only show chips that are non-zero
    let anyStatus = false;
    if (data.citations_removed > 0) {
        removedCount.textContent = `ลบ: ${data.citations_removed} รายการ`;
        showElement(removedCount);
        anyStatus = true;
    } else {
        hideElement(removedCount);
    }
    if (data.unsupported_claims > 0) {
        unsupportedCount.textContent = `ไม่รองรับ: ${data.unsupported_claims} รายการ`;
        showElement(unsupportedCount);
        anyStatus = true;
    } else {
        hideElement(unsupportedCount);
    }
    validationStatus.classList.toggle("hidden", !anyStatus);
    if (anyStatus) validationStatus.classList.add("flex");

    // Citations — rendered as clean clickable chips
    citationsList.innerHTML = "";
    if (data.citations && data.citations.length > 0) {
        data.citations.forEach((cite) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white border border-kmitl-200 text-kmitl-dark text-xs font-medium shadow-sm hover:border-kmitl-primary hover:text-kmitl-primary transition cursor-pointer";
            const docLabel = formatDocLabel(cite.document_id);
            chip.setAttribute("aria-label", `ดูอ้างอิง ${docLabel} หน้า ${cite.page}`);
            chip.setAttribute("title", cite.heading ? `${docLabel} หน้า ${cite.page} (${cite.heading})` : `${docLabel} หน้า ${cite.page}`);
            chip.innerHTML = `<span class="text-kmitl-primary">📄</span> <span class="font-semibold">${docLabel}</span> หน้า ${cite.page}`;
            chip.addEventListener("click", () => openPageViewer(cite.citation_id));
            citationsList.appendChild(chip);
        });
    } else {
        const span = document.createElement("span");
        span.textContent = "ไม่มี citation";
        span.className = "text-kmitl-dark/30";
        citationsList.appendChild(span);
    }

    // SQL box — only shown when this answer was backed by a SQL query
    const sqlText = data.sql || data.sql_query || "";
    if (sqlDetails && sqlText) {
        sqlCode.innerHTML = highlightSql(sqlText);
        sqlDetails.open = false;

        const sources = Array.isArray(data.sources) ? data.sources.join(", ") : (data.sources || "");
        sqlSources.textContent = sources ? `แหล่งข้อมูล: ${sources}` : "";
        sqlTime.textContent = `ใช้เวลา ${data.total_time_seconds.toFixed(1)} วินาที`;

        showElement(sqlDetails);
    } else if (sqlDetails) {
        hideElement(sqlDetails);
    }

    // Reset feedback button state for the new answer
    [feedbackUp, feedbackDown].forEach((btn) => {
        if (!btn) return;
        btn.classList.remove("bg-kmitl-100", "border-kmitl-primary");
        btn.dataset.selected = "";
    });

    showElement(answerSection);
}

// ── Copy / speak / feedback ─────────────────────────────────────────

if (copyBtn) {
    copyBtn.addEventListener("click", async() => {
        const text = answerText.innerText.trim();
        try {
            await navigator.clipboard.writeText(text);
            const original = copyBtn.innerHTML;
            copyBtn.innerHTML = "✅ คัดลอกแล้ว";
            setTimeout(() => { copyBtn.innerHTML = original; }, 1500);
        } catch (err) {
            showError("คัดลอกไม่สำเร็จ กรุณาคัดลอกด้วยตนเอง");
        }
    });
}

let currentUtterance = null;
if (speakBtn && "speechSynthesis" in window) {
    speakBtn.addEventListener("click", () => {
        if (window.speechSynthesis.speaking) {
            window.speechSynthesis.cancel();
            speakBtn.textContent = "🔊";
            return;
        }
        const text = answerText.innerText.trim();
        if (!text) return;
        currentUtterance = new SpeechSynthesisUtterance(text);
        currentUtterance.lang = "th-TH";
        currentUtterance.onend = () => { speakBtn.textContent = "🔊"; };
        speakBtn.textContent = "⏹";
        window.speechSynthesis.speak(currentUtterance);
    });
} else if (speakBtn) {
    speakBtn.disabled = true;
    speakBtn.classList.add("opacity-40", "cursor-not-allowed");
}

function sendFeedback(helpful) {
    // Optional — ignored silently if the backend doesn't implement this endpoint yet.
    fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: echoedQuestion.textContent, helpful }),
    }).catch(() => {});
}

[
    [feedbackUp, true],
    [feedbackDown, false],
].forEach(([btn, helpful]) => {
    if (!btn) return;
    btn.addEventListener("click", () => {
        const already = btn.dataset.selected === "1";
        [feedbackUp, feedbackDown].forEach((b) => {
            b.classList.remove("bg-kmitl-100", "border-kmitl-primary");
            b.dataset.selected = "";
        });
        if (!already) {
            btn.classList.add("bg-kmitl-100", "border-kmitl-primary");
            btn.dataset.selected = "1";
            sendFeedback(helpful);
        }
    });
});

// ── Page viewer ──────────────────────────────────────────────────────

async function openPageViewer(citationId) {
    pageViewer.classList.remove("hidden");
    pageViewer.classList.add("flex");
    viewerTitle.textContent = `กำลังโหลด ${citationId}...`;
    viewerInfo.textContent = "";

    viewerCanvas.classList.add("hidden");
    const existingText = document.getElementById("viewer-text-content");
    if (existingText) existingText.classList.add("hidden");

    try {
        const response = await fetch(`${API_BASE}/pages/${encodeURIComponent(citationId)}`);
        if (!response.ok) {
            if (response.status === 404) throw new Error(`ไม่พบ citation: ${citationId}`);
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        renderPageContent(data);
    } catch (err) {
        viewerTitle.textContent = "เกิดข้อผิดพลาด";
        viewerInfo.textContent = err.message;
    }
}

function renderPageContent(data) {
    const docLabel = formatDocLabel(data.document_id);
    viewerTitle.textContent = `${docLabel} — หน้า ${data.page}`;
    viewerInfo.textContent = data.heading ? `หัวข้อ: ${data.heading}` : `เอกสารหลักสูตร ${docLabel}`;

    viewerCanvas.classList.add("hidden");

    let textEl = document.getElementById("viewer-text-content");
    if (!textEl) {
        textEl = document.createElement("div");
        textEl.id = "viewer-text-content";
        textEl.className = "whitespace-pre-wrap text-sm leading-relaxed p-4 max-h-[400px] overflow-y-auto bg-kmitl-50 border border-kmitl-200 rounded-xl mt-2";
        viewerCanvas.parentNode.insertBefore(textEl, viewerCanvas.nextSibling);
    }
    textEl.classList.remove("hidden");
    textEl.textContent = data.chunk_text || `(ไม่มีเนื้อหาข้อความ — หน้า ${data.page})`;
}

closeViewer.addEventListener("click", () => hidePageViewer());
const backdrop = document.querySelector(".page-viewer-backdrop");
if (backdrop) backdrop.addEventListener("click", () => hidePageViewer());
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pageViewer.classList.contains("hidden")) hidePageViewer();
});

function hidePageViewer() {
    pageViewer.classList.add("hidden");
    pageViewer.classList.remove("flex");
}

// ── Markdown → styled answer HTML ────────────────────────────────────
// รองรับ subset ที่ LLM ใช้จริง: หัวข้อ #, ตัวหนา **, ตัวเอียง *,
// inline code `, รายการ - / •, เว้นบรรทัด
// escape HTML ก่อนเสมอ เพราะข้อความคำตอบเป็น untrusted (ป้องกัน XSS)
//
// โครงสร้างผลลัพธ์:
//   - heading แรก (ถ้ามี) แสดงเป็นหัวข้อใหญ่นอกกล่อง
//   - เนื้อหาที่เหลือห่อด้วยกล่อง callout สีส้มอ่อน
//   - heading ย่อย (h4/h5) ที่ตามด้วย list ติดกัน จะถูกจัดเป็นกริดหลายคอลัมน์
//     (ตัวอย่าง: "เทอม 1" / "เทอม 2" จะเรียงข้างกันบนจอกว้าง)

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function renderInline(text) {
    return text
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
}

// Plain-text SQL → escaped HTML with keywords picked out in a lighter shade.
// Not a real parser — just a readability pass for the debug box.
const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP BY|ORDER BY|HAVING|LIMIT|AS|AND|OR|NOT|IN|IS|NULL|DISTINCT|UNION|ALL|CASE|WHEN|THEN|ELSE|END|COALESCE|SUM|COUNT|AVG|MIN|MAX)\b/g;

function highlightSql(raw) {
    return escapeHtml(raw).replace(SQL_KEYWORDS, (m) => `<span class="sql-kw">${m}</span>`);
}

// Parse raw markdown into a flat list of block objects.
function parseBlocks(raw) {
    const lines = escapeHtml(raw).split("\n");
    const blocks = [];
    let currentList = null;

    const flushList = () => {
        if (currentList) {
            blocks.push(currentList);
            currentList = null;
        }
    };

    for (const line of lines) {
        const trimmed = line.trim();

        if (trimmed === "") { flushList(); continue; }

        const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
        if (heading) {
            flushList();
            blocks.push({ type: "heading", level: heading[1].length, text: renderInline(heading[2]) });
            continue;
        }

        const bullet = trimmed.match(/^[-*•]\s+(.*)$/);
        if (bullet) {
            if (!currentList) currentList = { type: "list", items: [] };
            currentList.items.push(renderInline(bullet[1]));
            continue;
        }

        flushList();
        blocks.push({ type: "paragraph", text: renderInline(trimmed) });
    }
    flushList();
    return blocks;
}

function blockToHtml(block) {
    if (block.type === "heading") {
        const level = Math.min(block.level + 2, 5); // #→h3, ##→h4, ###/####→h5
        return `<h${level}>${block.text}</h${level}>`;
    }
    if (block.type === "list") {
        return `<ul>${block.items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
    }
    return `<p>${block.text}</p>`;
}

function renderAnswerHtml(raw) {
    const blocks = parseBlocks(raw);
    if (blocks.length === 0) return "";

    let html = "";
    let i = 0;

    // First heading (if present) renders as the big standalone title.
    if (blocks[i] && blocks[i].type === "heading") {
        html += `<h3>${blocks[i].text}</h3>`;
        i++;
    }

    const rest = blocks.slice(i);
    if (rest.length === 0) return html;

    // Group the remainder: consecutive (sub-heading + list) pairs become
    // "columns"; everything else (intro paragraphs, standalone lists) stays
    // in normal flow inside the callout box.
    let calloutInner = "";
    let columnGroup = [];

    const flushColumns = () => {
        if (columnGroup.length === 0) return;
        if (columnGroup.length === 1) {
            calloutInner += columnGroup[0];
        } else {
            calloutInner += `<div class="answer-columns">${columnGroup.map((c) => `<div>${c}</div>`).join("")}</div>`;
        }
        columnGroup = [];
    };

    for (let j = 0; j < rest.length; j++) {
        const block = rest[j];
        const next = rest[j + 1];
        if (block.type === "heading" && block.level >= 2 && next && next.type === "list") {
            columnGroup.push(blockToHtml(block) + blockToHtml(next));
            j++; // consume the list too
            continue;
        }
        flushColumns();
        calloutInner += blockToHtml(block);
    }
    flushColumns();

    html += `<div class="answer-callout">${calloutInner}</div>`;
    return html;
}

// ── Utility ──────────────────────────────────────────────────────────

function showElement(el) { el.classList.remove("hidden"); }
function hideElement(el) { el.classList.add("hidden"); }
function showError(message) {
    errorDisplay.textContent = message;
    showElement(errorDisplay);
}
