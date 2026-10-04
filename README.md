# 🦎 Jingjok-Thorius (น้องจิ้งจก-ทองหล่อ)
> **ระบบ AI อัจฉริยะสำหรับถาม-ตอบหลักสูตร คณะเทคโนโลยีสารสนเทศ สจล. (IT KMITL Curriculum QA & Document Intelligence)**

---

## 📋 สารบัญ (Table of Contents)
1. [ภาพรวมโครงการ (Overview)](#-ภาพรวมโครงการ-overview)
2. [ส่วนที่ 1: การออกแบบ Wireframe (Lab Part 1)](#-ส่วนที่-1-การออกแบบ-wireframe-lab-part-1)
3. [ส่วนที่ 2: ข้อกำหนด API Contract (Lab Part 2)](#-ส่วนที่-2-ข้อกำหนด-api-contract-lab-part-2)
4. [ส่วนที่ 3: การเชื่อมต่อ Web UI และ 4 สถานะ (Lab Part 3)](#-ส่วนที่-3-การเชื่อมต่อ-web-ui-และ-4-สถานะ-lab-part-3)
5. [ส่วนที่ 4: การติดตั้งและเริ่มต้นใช้งาน (Installation & Setup)](#-ส่วนที่-4-การติดตั้งและเริ่มต้นใช้งาน-installation--setup)
6. [ส่วนที่ 5: สรุปรายการไฟล์ส่งมอบ (Deliverables Checklist)](#-ส่วนที่-5-สรุปรายการไฟล์ส่งมอบ-deliverables-checklist)
7. [ส่วนที่ 6: สถาปัตยกรรมระบบ (Architecture)](#-ส่วนที่-6-สถาปัตยกรรมระบบ-architecture)
8. [ส่วนที่ 7: รายงานผลการประเมินและการทดสอบระบบ (Benchmark Evaluation)](#-ส่วนที่-7-รายงานผลการประเมินและการทดสอบระบบ-benchmark-evaluation)

---

## 🌟 ภาพรวมโครงการ (Overview)

**Jingjok-Thorius** เป็นระบบค้นหาและตอบคำถามเกี่ยวกับหลักสูตรการศึกษาของคณะเทคโนโลยีสารสนเทศ สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง (KMITL) จากเอกสารหลักสูตร มคอ.2 จำนวน 14 ฉบับ โดยมีจุดเด่นสำคัญ:
- **Provenance-First:** ทุกคำตอบระบุเอกสารต้นทางและเลขหน้า และข้อมูลทุกแถวในฐานข้อมูลผูกกับเอกสาร/หน้า/พิกัด (bbox) ของข้อความต้นทาง (หมายเหตุ: ปัจจุบัน API `/pages` ยังไม่ส่ง bbox กลับมา ดูหัวข้อ 2.4)
- **Curriculum-Aware:** รองรับการจำแนกหลักสูตรทั้ง 5 สาขาอย่างถูกต้อง (IT, DSBA, AIT, BIT, AITBA)
- **High Transparency:** แสดงคำสั่ง SQL ที่ใช้ดึงข้อมูลจากฐานข้อมูลจริง เพื่อความโปร่งใสและตรวจสอบย้อนกลับได้
- **Modern Responsive Web UI:** หน้าเว็บแบบ Single Page Application (SPA) ธีมสีประจำสถาบัน KMITL (ส้มแสด `#FF6600`)

---

## 🎨 ส่วนที่ 1: การออกแบบ Wireframe (Lab Part 1)

ภาพ Wireframe ฉบับสมบูรณ์ถูกจัดทำบน Figma และบันทึกไว้ที่ไดเรกทอรี [`wireframe/wireframe-jingjok.png`](wireframe/wireframe-jingjok.png)

![Jingjok-Thorius Wireframe](wireframe/wireframe-jingjok.png)

### 1.1 หน้าจอในระบบ (Available Screens & Views)
1. **หน้าจอค้นหาและถามคำตอบหลัก (Main Q&A Dashboard):**
   - ส่วนหัวแบรนด์เนมและมาสคอตน้องทองหล่อ
   - Dropdown สำหรับเลือกหลักสูตรที่ต้องการถาม
   - ปุ่มชิปคำถามยอดฮิต (Quick Prompt Chips) สำหรับกดถามได้ทันที
   - กล่องกรอกคำถาม Textarea พร้อมตัวนับอักขระ (0 / 800)
   - แผงแสดงผลคำตอบ พร้อมการเรนเดอร์ Markdown, ป้ายเวอร์ชัน และตัวจับเวลา Latency
   - แถบป้ายอ้างอิง (Citation Badges)
   - แผงพับดูคำสั่ง SQL (SQL Query Inspector)
2. **หน้าต่างป็อปอัปดูเอกสารต้นทาง (Document Page Viewer Modal):**
   - แสดงขึ้นมาเมื่อผู้ใช้คลิกที่ป้าย Citation ใด ๆ
   - แสดงชื่อเอกสาร มคอ.2, หัวข้อ, เลขหน้า, ข้อความเนื้อหาดิบ และ Canvas แสดงตำแหน่ง Bounding Box
3. **สถานะแสดงข้อผิดพลาด (Error Alert Banner):**
   - แสดงแถบเตือนสีแดง/ส้มเมื่อไม่ได้เลือกหลักสูตร หรือระบบขัดข้อง

### 1.2 สิทธิ์และการมองเห็นของผู้ใช้งานแต่ละกลุ่ม (Who Sees What)

| กลุ่มผู้ใช้งาน (User Persona) | วัตถุประสงค์ในการใช้งาน | หน้าจอและส่วนประกอบที่เข้าถึงได้ |
| :--- | :--- | :--- |
| **นักศึกษา / ผู้สนใจทั่วไป<br>(Students & General Users)** | ค้นหาข้อมูลรายวิชา, เช็คจำนวนหน่วยกิตปี 1, ตรวจสอบวิชาบังคับก่อน (Prerequisite) | • หน้าจอหลักสำหรับถามคำถาม<br>• ปุ่มคำถามด่วน (Quick Chips)<br>• อ่านคำตอบที่จัดรูปแบบสวยงาม<br>• คลิกดูป้าย Citation เพื่อเปิดดูหน้าเอกสารต้นทางยืนยันความถูกต้อง |
| **อาจารย์ / กรรมการหลักสูตร<br>(Faculty & Curriculum Committees)** | ตรวจสอบความถูกต้องของแผนการเรียนและการจัดหมวดหมู่วิชาในแต่ละเล่มหลักสูตร | • ทุกฟังก์ชันของนักศึกษา<br>• สามารถสลับดูข้อมูลเปรียบเทียบทั้ง 5 สาขาวิชา (IT, DSBA, AIT, BIT, AITBA)<br>• ตรวจสอบเลขหน้าและเนื้อหาที่แท้จริงจากเล่ม มคอ.2 ผ่าน Modal เอกสาร |
| **นักพัฒนา / ผู้ประเมินระบบ<br>(Developers & Evaluators)** | ตรวจสอบประสิทธิภาพ ความเร็ว และความแม่นยำในการดึงข้อมูลของระบบ RAG | • ดูตัวชี้วัดความเร็ว Latency (เช่น `⚡ 0.28s`)<br>• เปิดแผง Accordion ตรวจสอบคำสั่ง SQL จริง (`sql_query`)<br>• ดูจำนวน claim units ที่ผ่านการตรวจสอบความถูกต้อง |

### 1.3 Design Tokens & Typography
- **Primary Color:** สีส้มแสด KMITL (`#FF6600`, `#E65100`, `#C43D00`)
- **Background Color:** สีครีมสบายตา (`#FAF7F2`) และการ์ดสีขาวสะอาด (`#FFFFFF`)
- **Console Dark:** สีน้ำเงินเข้ม Slate (`#1E293B`) สำหรับกล่องโค้ด SQL
- **Font:** `Sarabun` (ฟอนต์มาตรฐานภาษาไทย มีหัว อ่านง่าย) ผสาน `Inter` (ภาษาอังกฤษและตัวเลข)

---

## 📡 ส่วนที่ 2: ข้อกำหนด API Contract (Lab Part 2)

ระบบให้บริการ REST API ทำงานที่ Base URL: `http://127.0.0.1:8000`

### 2.1 สรุป Endpoints ทั้งหมด

| Method | Endpoint Path | หน้าที่การทำงาน | Status Codes |
| :---: | :--- | :--- | :---: |
| `POST` | `/ask` | ส่งคำถามพร้อมระบุหลักสูตร ได้รับคำตอบพร้อมการอ้างอิงและ SQL trace | `200`, `422`, `504` (เกิน 120 วินาที) |
| `GET` | `/documents` | รายชื่อเอกสาร (**ปัจจุบันยังไม่ได้ต่อกับฐานข้อมูล คืนรายการว่าง**) | `200` |
| `GET` | `/pages/{citation_id}` | ดึงข้อมูลหน้าที่ถูกอ้างอิงตาม citation_id (เก็บใน memory ของ process, `bbox` เป็น `null`) | `200`, `404` |
| `GET` | `/traces/{request_id}` | ดึงประวัติและสถิติการประมวลผลของคำถามตาม request_id | `200`, `404` |

---

### 2.2 รายละเอียด Endpoint: `POST /ask`

**คำอธิบาย:** รับคำถามภาษาไทยหรืออังกฤษ และรหัสหลักสูตร ประมวลผลผ่าน RAG pipeline แล้วส่งคืนคำตอบพร้อมเอกสารอ้างอิงและคำสั่ง SQL

#### Request
- **Headers:** `Content-Type: application/json`
- **Request Body (JSON):**

```json
{
  "question": "ปี 1 เทอม 1 เรียนวิชาอะไรบ้าง มีกี่หน่วยกิต",
  "program": "IT"
}
```

| Field Name | Data Type | Required | Description | Constraints |
| :--- | :---: | :---: | :--- | :--- |
| `question` | `string` | **Yes** | ข้อความคำถามที่ต้องการถาม | ความยาว 1 - 2,000 ตัวอักษร |
| `program` | `string` | **Yes** | รหัสหลักสูตรที่เลือก | ค่าที่ยอมรับได้: `"IT"`, `"DSBA"`, `"AIT"`, `"BIT"`, `"AITBA"` |

#### Response (Success: `200 OK`)
- ตัวอย่างนี้เป็นผลจริงจากเซิร์ฟเวอร์ (ตัดรายการ citation และ SQL ให้สั้นลง) ถามว่า "วิชา data warehouse ต้องผ่านวิชาใดก่อน และวิชานั้นเรียนตอนไหน" หลักสูตร DSBA:

```json
{
  "request_id": "bc0b3e33-65b3-4d55-ba86-46d66d6f1d02",
  "answer": "วิชา 06026212 การสร้างคลังข้อมูล (DATA WAREHOUSING) — 3(2-2-5) | ปีที่ 3 ภาคการศึกษาที่ 1\n  ต้องผ่านวิชาบังคับก่อน:\n    • 06066300 แนวคิดระบบฐานข้อมูล (DATABASE SYSTEM CONCEPTS) — 3(2-2-5) | ปีที่ 2 ภาคการศึกษาที่ 1",
  "citations": [
    {
      "citation_id": "cite-001",
      "document_id": "a39d6db17ccc5cf4",
      "page": 323,
      "heading": "ตารางรายวิชา/แผนการศึกษา"
    },
    {
      "citation_id": "cite-002",
      "document_id": "a39d6db17ccc5cf4",
      "page": 18,
      "heading": "ระบบสารสนเทศเพื่อการจัดการ"
    }
  ],
  "versions_resolved": [
    "DSBA 2565 (current)"
  ],
  "citations_removed": 0,
  "unsupported_claims": 0,
  "total_time_seconds": 0.1881,
  "sql_query": "-- Query 1 SELECT code, name_th, name_en, credits_raw, year, semester, prerequisite_json, prerequisite_raw, version_id FROM course WHERE (name_th LIKE '%data%' OR name_en LIKE '%data%' OR name_th LIKE …"
}
```

| Field Name | Data Type | Description |
| :--- | :---: | :--- |
| `request_id` | `string (uuid)` | รหัสอ้างอิงคำขอ ใช้สำหรับสืบค้น trace |
| `answer` | `string (markdown)` | คำตอบที่ระบบสรุปและจัดรูปแบบ Markdown |
| `citations` | `array of objects` | รายการเอกสารและหน้าที่ใช้อ้างอิง (`citation_id`, `document_id`, `page`, `heading`) |
| `versions_resolved` | `array of strings` | เล่มหลักสูตรและเวอร์ชันที่ระบบใช้ตอบคำถาม |
| `citations_removed` | `integer` | สงวนไว้สำหรับตัวตรวจ citation (**ยังไม่ได้ต่อสาย ค่าเป็น 0 เสมอ**) |
| `unsupported_claims` | `integer` | สงวนไว้เช่นเดียวกัน (**ค่าเป็น 0 เสมอ ไม่ใช่ค่าที่วัดได้**) |
| `total_time_seconds` | `float` | ระยะเวลาที่ระบบใช้ประมวลผลทั้งหมด (วินาที) |
| `sql_query` | `string` | คำสั่ง SQL ที่รันบนฐานข้อมูล SQLite จริง |

#### Response (Validation Error: `422 Unprocessable Entity`)
เกิดเมื่อไม่ได้ส่งฟิลด์ที่จำเป็น หรือค่าไม่อยู่ในเงื่อนไขที่กำหนด (ตัวอย่างจริง: ส่ง `program` เป็นค่าที่ไม่รองรับ):
```json
{
  "detail": [
    {
      "loc": ["body", "program"],
      "msg": "ต้องเลือกหลักสูตรก่อนถาม — ค่าที่รับได้: AIT, AITBA, BIT, DSBA, IT",
      "type": "value_error"
    }
  ]
}
```
ถ้าไม่ส่งฟิลด์ `program` เลย จะได้ `"msg": "Field required"`, `"type": "missing"`

#### Response (`504 Gateway Timeout`)
เมื่อคำขอใช้เวลาเกิน 120 วินาที (ค่า `[api].request_timeout_seconds`) จะได้ `{"detail": "Request timeout exceeded", "request_id": "...", "elapsed_seconds": ...}`
หากเกิดข้อผิดพลาดภายในระหว่างตอบ ระบบยังคืน `200` โดยใส่ข้อความ `เกิดข้อผิดพลาด: ...` ไว้ในฟิลด์ `answer`

---

### 2.3 รายละเอียด Endpoint: `GET /documents`

**คำอธิบาย:** ออกแบบไว้ให้คืนรายการเล่มหลักสูตร (สูงสุด 500 รายการ) แต่ **ปัจจุบันยังไม่ได้ต่อกับตาราง `document`** จึงคืนรายการว่างเสมอ

#### Response (`200 OK`)
```json
{ "documents": [], "total": 0 }
```

---

### 2.4 รายละเอียด Endpoint: `GET /pages/{citation_id}`

**คำอธิบาย:** ดึงข้อมูลหน้าเอกสารต้นทางของ citation ที่เพิ่งถูกสร้างจากการเรียก `/ask` ล่าสุด
- `citation_id` เป็นรหัสลำดับ (`cite-001`, `cite-002`, ...) ที่เก็บใน memory ของ process และ **ถูกเขียนทับทุกครั้งที่ถามคำถามใหม่** จึงอ้างถึง citation ของคำตอบล่าสุดเท่านั้น
- ปัจจุบัน `bbox` เป็น `null` และ `page_width`/`page_height` เป็น `0.0` (ข้อมูลพิกัดมีอยู่ในฐานข้อมูล แต่ยังไม่ได้ส่งผ่าน API นี้)

#### Path Parameters
- `citation_id` (string, เช่น `cite-001`)

#### Response (`200 OK`, ผลจริง)
```json
{
  "citation_id": "cite-001",
  "document_id": "a39d6db17ccc5cf4",
  "page": 9,
  "heading": "หมวดที่ 2 ข้อมูลเฉพาะของหลักสูตร",
  "bbox": null,
  "page_width": 0.0,
  "page_height": 0.0,
  "chunk_text": "หมวดที่ 2 ข้อมูลเฉพาะของหลักสูตร
1. ปรัชญา ความสำคัญ และวัตถุประสงค์ของหลักสูตร"
}
```

#### Response (`404 Not Found`)
```json
{
  "detail": "citation_id 'cite-999' ไม่พบในระบบ"
}
```

### 2.5 รายละเอียด Endpoint: `GET /traces/{request_id}`
คืนสถิติของคำขอ (เวลา จำนวน citation ฯลฯ) ที่เก็บใน memory ของ process จึงหายเมื่อรีสตาร์ตเซิร์ฟเวอร์ ฟิลด์ `citations_removed`/`unsupported_claims` เป็น 0 เสมอ และ `question_level` เป็น `"L1"` ค่าคงที่ ตอบ `404` เมื่อไม่พบ `request_id`

---

## 💻 ส่วนที่ 3: การเชื่อมต่อ Web UI และ 4 สถานะ (Lab Part 3)

ส่วนติดต่อผู้ใช้ถูกพัฒนาแบบ Vanilla HTML/CSS/JavaScript (ไฟล์ [`web/index.html`](web/index.html), [`web/style.css`](web/style.css), และ [`web/app.js`](web/app.js)) ซึ่งเชื่อมต่อกับ API Backend ผ่านฟังก์ชัน `fetch()` และจัดการการแสดงผลตาม **4 สถานะ (State Machine)** อย่างสมบูรณ์:

```
        ┌────────────────────────────────────────────────┐
        │             1. Initial / Idle State            │
        │    ผู้ใช้เลือกหลักสูตร และพิมพ์หรือคลิกคำถามด่วน   │
        └───────────────────────┬────────────────────────┘
                                │ กดปุ่ม "ถามจิ้งจก Thorius" (Submit)
                                ▼
        ┌────────────────────────────────────────────────┐
        │               2. Loading State                 │
        │      แสดง Spinner หมุน, ปิดการกดปุ่มซ้ำ (Disabled)    │
        └───────────────┬────────────────┬───────────────┘
         fetch() สำเร็จ │ (HTTP 200)      │ เกิดข้อผิดพลาด (Network / 422 / 504)
                        ▼                ▼
        ┌────────────────────────┐  ┌────────────────────┐
        │    3. Success State    │  │   4. Error State   │
        │ แสดงคำตอบ Markdown      │  │ แสดงแบนเนอร์แจ้งเตือน │
        │ แสดง Citations Badges  │  │ ข้อความภาษาไทยชัดเจน  │
        │ แสดง Accordion SQL     │  │ ให้ผู้ใช้แก้ไขคำถามได้ │
        └────────────────────────┘  └────────────────────┘
```

---

### 3.1 รายละเอียดการทำงานของทั้ง 4 สถานะ

#### 1. Initial / Idle State (สถานะเริ่มต้นพร้อมใช้งาน)
- **พฤติกรรม UI:**
  - แสดงแบบฟอร์มให้ผู้ใช้เลือกหลักสูตรที่ Dropdown (`#program-select`)
  - มีช่อง Textarea (`#question-input`) สำหรับพิมพ์คำถาม พร้อมตัวนับอักขระ (`#char-count`)
  - แสดงปุ่ม **คำถามยอดฮิต (Quick Prompt Chips)** ซึ่งเมื่อคลิกจะคัดลอกข้อความลงกล่องคำถามและกดส่งทันที
  - ซ่อนส่วนแสดงผลคำตอบ (`#answer-section`) และข้อความแจ้งเตือน (`#error-display`)
- **โค้ด JavaScript ที่เกี่ยวข้อง:**
  ```javascript
  // ล้างค่าและกลับสู่สถานะเริ่มต้น
  clearBtn.addEventListener("click", () => {
      questionInput.value = "";
      updateCharCount();
      hideElement(errorDisplay);
      hideElement(answerSection);
      questionInput.focus();
  });
  ```

#### 2. Loading State (สถานะกำลังประมวลผลคำขอ)
- **พฤติกรรม UI:**
  - ทำงานทันทีเมื่อผู้ใช้กด Submit แบบฟอร์ม
  - ซ่อนแผงคำตอบเก่าและข้อความแจ้งเตือนเดิม
  - แสดงแอนิเมชันวงล้อหมุน Loading Spinner (`#loading`)
  - ตั้งค่าปุ่มส่งคำถามเป็น `disabled = true` เพื่อป้องกันการกดย้ำ (Debounce & Double-click prevention)
- **โค้ด JavaScript ที่เกี่ยวข้อง:**
  ```javascript
  hideElement(errorDisplay);
  hideElement(answerSection);
  showElement(loading);
  askBtn.disabled = true;
  ```

#### 3. Success State (สถานะแสดงผลลัพธ์สำเร็จ - 200 OK)
- **พฤติกรรม UI:**
  - ซ่อนสถานะ Loading และเปิดให้ปุ่มส่งคำถามใช้งานได้อีกครั้ง
  - แสดงกล่องผลลัพธ์คำตอบ (`#answer-section`)
  - แสดงข้อความทวนคำถาม (`#echoed-question`), ป้ายหลักสูตร (`#version-badge`), และเวลาที่ใช้ (`#time-badge`)
  - เรนเดอร์คำตอบที่เป็น Markdown เป็น HTML แสดงรายชื่อวิชา รหัสวิชา หน่วยกิตอย่างสวยงาม
  - สร้างชิปอ้างอิง **Citations List (`#citations-list`)** โดยเมื่อผู้ใช้คลิกชิป จะดึง API `/pages/{citation_id}` มาเปิด Modal แสดงเนื้อหาเอกสารจริง
  - แสดงแถบ Accordion คำสั่ง SQL (`#sql-details`) เพื่อให้นักศึกษาหรืออาจารย์ตรวจสอบความโปร่งใสของคำสั่งสืบค้นได้
  - มีปุ่มอำนวยความสะดวก: ปุ่มคัดลอกคำตอบ (Copy to Clipboard), ปุ่มอ่านออกเสียง (Text-to-Speech), และปุ่ม Feedback
- **โค้ด JavaScript ที่เกี่ยวข้อง:**
  ```javascript
  const response = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, program: selectedProgram }),
  });
  const data = await response.json();
  renderAnswer(data, question, selectedProgram);
  ```

#### 4. Error / Empty State (สถานะเกิดข้อผิดพลาด / ข้อมูลไม่ถูกต้อง)
- **พฤติกรรม UI:**
  - เกิดขึ้นเมื่อผู้ใช้ลืมเลือกหลักสูตร (Client Validation), กรอกคำถามว่างเปล่า, หรือ API ส่งคืนรหัส `422`, `504`, หรือเครือข่ายขัดข้อง
  - ซ่อนสถานะ Loading และเปิดปุ่มส่งคำถามให้ลองใหม่ได้
  - ซ่อนส่วนแสดงผลคำตอบ
  - แสดงแถบเตือนสีแดง/ส้ม (`#error-display`) พร้อมข้อความภาษาไทยที่เข้าใจง่าย เช่น *"กรุณาเลือกหลักสูตรก่อนถาม"* หรือรายละเอียด Error จาก Server
- **โค้ด JavaScript ที่เกี่ยวข้อง:**
  ```javascript
  if (!selectedProgram) {
      showError("กรุณาเลือกหลักสูตรก่อนถาม");
      programSelect.focus();
      return;
  }
  // จัดการ HTTP errors หรือ Network errors
  function showError(msg) {
      errorDisplay.textContent = msg;
      showElement(errorDisplay);
      errorDisplay.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  ```

---

## 🚀 ส่วนที่ 4: การติดตั้งและเริ่มต้นใช้งาน (Installation & Setup)

### 4.1 ข้อกำหนดระบบ (Prerequisites)
- **Python 3.11** (โปรเจกต์กำหนด `>=3.11,<3.12`)
- **OS:** Windows 10/11 (`start.bat` ใช้ได้เฉพาะ Windows; macOS/Linux ใช้วิธีที่ 2 ในหัวข้อ 4.4)
- เบราว์เซอร์สมัยใหม่ (Chrome, Edge, Firefox, Safari)
- **อินเทอร์เน็ต** สำหรับเรียก Typhoon LLM (ดูหัวข้อ 4.3)

### 4.2 ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```
รวม `torch` + `transformers` สำหรับ semantic search ด้วย bge-m3 (ใช้ CPU ก็ได้ ไม่ต้องมี GPU)
โมเดล `BAAI/bge-m3` (~2.3 GB) จะถูกดาวน์โหลดครั้งแรกด้วย `python setup_model.py` — `start.bat` เรียกให้อัตโนมัติ (ต้องต่ออินเทอร์เน็ต ใช้เวลาตามความเร็วเน็ต)
> ถ้าข้ามขั้นนี้ ระบบยังเปิดได้ แต่จะถอยไปใช้ lexical search และความแม่นยำของคำถามบางประเภทลดลง

### 4.3 ตั้งค่า Environment Variables
```bash
copy .example.env .env      # Windows (start.bat ทำให้อัตโนมัติถ้ายังไม่มี .env)
```
แก้ไฟล์ `.env`:
```env
TYPHOON_API_KEY=your_typhoon_api_key_here
KATRAG_SKIP_WARMUP=1
```
- `TYPHOON_API_KEY` — สมัครฟรีที่ https://opentyphoon.ai ใช้สำหรับคำถามเชิงวิเคราะห์ ("ได้ไหม/ทำไม/แนะนำ")
  ถ้าไม่ใส่ ระบบยังตอบคำถามที่มาจากตารางฐานข้อมูล (รายวิชา แผนการเรียน prerequisite เกณฑ์จบ) ได้ แต่คำถามเชิงวิเคราะห์จะคืนหลักฐานดิบแทนคำตอบสรุป
- `KATRAG_SKIP_WARMUP=1` — ข้ามการโหลดโมเดล embedding เข้า RAM ตอนเปิดเซิร์ฟเวอร์ (คำถามแรกจะช้ากว่าปกติราวครึ่งถึง 1 นาที เพราะต้องโหลดโมเดลก่อน)

> หมายเหตุ: ส่วนค้นหาและฐานข้อมูลทำงานในเครื่อง (net guard ใช้กับขั้น ingest/index) แต่การสรุปคำตอบด้วย LLM เรียก Typhoon API ผ่านอินเทอร์เน็ต

### 4.3.1 ฐานข้อมูล (ไม่ต้องทำเอง)
ฐานข้อมูล (provenance store + embeddings) ถูกบีบอัดไว้ใน repo ที่ `artifacts/katrag.sqlite3.gz` (~63 MB)
`start.bat` จะแตกเป็น `artifacts/katrag.sqlite3` (~110 MB) ให้อัตโนมัติในการรันครั้งแรก
หากรันด้วยวิธีอื่น (macOS/Linux หรือ uvicorn โดยตรง) ให้สั่งก่อนหนึ่งครั้ง:
```bash
python setup_db.py
```

### 4.4 การสั่งรันเซิร์ฟเวอร์ (Start Server)

สามารถสั่งรันเซิร์ฟเวอร์ได้ 3 วิธี:

#### วิธีที่ 1: ดับเบิลคลิกไฟล์ `start.bat` (สะดวกที่สุดบน Windows)
- เพียงดับเบิลคลิกไฟล์ [`start.bat`](start.bat) หรือรันใน Command Prompt:
  ```cmd
  start.bat
  ```
- ระบบจะตรวจสอบไฟล์ `.env`, เปิดเซิร์ฟเวอร์ และเปิดหน้าเว็บในเบราว์เซอร์ให้อัตโนมัติทันที

#### วิธีที่ 2: รันผ่าน Uvicorn โดยตรง
```bash
uvicorn katrag.api.service:app --host 127.0.0.1 --port 8000 --reload
```

#### วิธีที่ 3: รันผ่าน KatRAG CLI
```bash
katrag serve
```

### 4.5 การเข้าใช้งานผ่าน Web Browser
เมื่อเซิร์ฟเวอร์เริ่มทำงานแล้ว ให้เปิดเว็บบราวเซอร์ไปที่:
👉 **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## 📦 ส่วนที่ 5: สรุปรายการไฟล์ส่งมอบ (Deliverables Checklist)

ตามข้อกำหนดของห้องปฏิบัติการ (Lab) ทุกไฟล์ได้รับการตรวจสอบและจัดวางในโครงสร้างที่ถูกต้อง:

| รายการไฟล์ที่ส่ง | ที่ตั้งของไฟล์ (Path) | คำอธิบาย | สถานะ |
| :--- | :--- | :--- | :---: |
| **1. Wireframe** | [`wireframe/wireframe-jingjok.png`](wireframe/wireframe-jingjok.png)<br>[`wireframe/README.md`](wireframe/README.md) | ไฟล์ภาพการออกแบบ UI และเอกสารอธิบาย Layout, Components และสิทธิ์การใช้งาน | ✅ ครบถ้วน |
| **2. README** | [`README.md`](README.md) | เอกสารหลักระบุ Wireframe, API Contract และคำอธิบายการเชื่อมต่อ 4 สถานะ | ✅ ครบถ้วน |
| **3. index.html** | [`web/index.html`](web/index.html) | ไฟล์ HTML หลักของหน้าเว็บ เชื่อมต่อ Tailwind CSS, Fonts, Favicon และ `app.js` | ✅ ครบถ้วน |
| **4. style.css** | [`web/style.css`](web/style.css) | ไฟล์สไตล์ลิ่ง CSS และ Custom Glassmorphism Theme | ✅ ครบถ้วน |
| **5. app.js** | [`web/app.js`](web/app.js) | ไฟล์สคริปต์ Frontend จัดการ `fetch()`, 4 สถานะ, Clean Citation Chips และ DOM Manipulation | ✅ ครบถ้วน |
| **6. .example.env** | [`.example.env`](.example.env) (และ [`.env.example`](.env.example)) | ไฟล์เทมเพลตตัวแปรสภาพแวดล้อม พร้อมคำอธิบายการใช้งาน | ✅ ครบถ้วน |
| **7. รายงานผลทดสอบ 28 ข้อ** | [`docs/tester.xlsx`](docs/tester.xlsx) | ไฟล์ Excel รายงานผลการทดสอบระบบ 28 ข้อสดๆ ครบทั้งคำตอบ, Citation สะอาด และเวลา Latency | ✅ ผ่าน 100% |
| **8. สคริปต์ทดสอบอัตโนมัติ** | [`run_live_qa_tests.py`](run_live_qa_tests.py) | สคริปต์รัน Benchmark อัตโนมัติ 28 ข้อ ยิงเข้า `/ask` และสร้างรายงานลง Excel ทันที | ✅ ครบถ้วน |

---

## 🏗️ ส่วนที่ 6: สถาปัตยกรรมระบบ (Architecture)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Web Frontend (Single Page App)               │
│         index.html  │  style.css  │  app.js (4 States)          │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP / JSON (127.0.0.1:8000)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Service (service.py)                 │
│         POST /ask   │ GET /documents │ GET /pages │ GET /traces │
└──────┬────────────────────────┬──────────────────────────┬──────┘
       │                        │                          │
       ▼                        ▼                          ▼
┌──────────────┐       ┌──────────────────┐       ┌───────────────┐
│ Query Router │       │ Provenance Store │       │  LLM Engine   │
│ & SQL Search │       │ (SQLite + FTS5)  │       │  Typhoon API  │
└──────────────┘       └──────────────────┘       └───────────────┘
```

1. **Static Files Serving:** FastAPI ให้บริการไฟล์ Static ในโฟลเดอร์ `web/` โดยอัตโนมัติที่รูท URL `/`
2. **Provenance Store (SQLite):** ฐานข้อมูลจัดเก็บโครงสร้างรายวิชา แผนการศึกษา และข้อมูล Bounding Box พิกัดบนหน้าเอกสาร
3. **Hybrid Search & Structured SQL:** ตอบคำถามเกี่ยวกับโครงสร้างหลักสูตรและวิชาด้วยการ Query ตาราง SQLite (ส่วนที่ตอบจากตารางไม่ผ่าน LLM จึงไม่แต่งข้อมูล) ร่วมกับ Hybrid Search (FTS5 + bge-m3) สำหรับคำถามอื่น
4. **Net Guard:** ขั้น ingest/index ถูกกันไม่ให้เชื่อมต่อเครือข่ายที่ระดับ Socket (`katrag.common.net_guard`) ส่วนการสรุปคำตอบด้วย LLM เรียก Typhoon API ผ่านอินเทอร์เน็ต

---

## 🧪 ส่วนที่ 7: รายงานผลการประเมินและการทดสอบระบบ (Benchmark Evaluation)

ระบบได้รับการทดสอบความถูกต้องและวัดประสิทธิภาพจริงผ่านชุดคำถามทดสอบครอบคลุม **28 ข้อ** (ระดับ 1 ง่าย, ระดับ 2 ปานกลาง, ระดับ 3 ยาก, และระดับ 4 ท้าทาย / Challenge) โดยยิงทดสอบสดผ่าน HTTP API (`http://127.0.0.1:8000/ask`) และบันทึกผลการประเมินฉบับเต็มไว้ในไฟล์ [**`docs/tester.xlsx`**](docs/tester.xlsx)

### 7.1 สรุปผลการทดสอบแยกตามระดับความยาก (Evaluation by Level)

ตัวเลขด้านล่างมาจากการรันชุด 28 ข้อ **ซ้ำบนเซิร์ฟเวอร์ที่เปิดไว้แล้ว (warm) หลังถอดคำตอบสำเร็จรูปที่เคยเขียนไว้ในโค้ดออกแล้ว** และเปิดอ่านคำตอบเทียบกับเฉลยทีละข้อ (เวลาและคำตอบของข้อที่เรียก LLM เปลี่ยนได้ทุกรอบ)

| ระดับความยาก (Difficulty Level) | จำนวนข้อ | ผ่านการตรวจคำสำคัญ (auto) | ตรวจเทียบเฉลยด้วยคน: ถูกครบ / บางส่วน / ผิดหรือไม่ตรงเฉลย | เวลาตอบเฉลี่ย |
| :--- | :---: | :---: | :---: | :---: |
| **ระดับ 1: ง่าย (Basic Extraction)** | 9 | 9/9 | 9 / 0 / 0 | ~0.24 วินาที |
| **ระดับ 2: ปานกลาง (Multi-table & Filter)** | 9 | 9/9 | 9 / 0 / 0 | ~0.26 วินาที |
| **ระดับ 3: ยาก (Reasoning & Constraints)** | 7 | 7/7 | 6 / 1 / 0 (บางส่วน: H1) | ~0.86 วินาที |
| **ระดับ 4: ท้าทาย (Multi-hop & Cross-version)** | 3 | 2/3 | 1 / 0 / 2 (C1 ผิด, C3 ไม่ตรงเฉลย) | ~2.61 วินาที |
| **รวม** | **28** | **27/28** | **25 / 1 / 2** | **~0.65 วินาที** (เร็วสุด 0.05s, ช้าสุด 4.86s, ทุกข้อ < 5s) |

**ข้อควรอ่านเพื่อตีความตัวเลข**
- คอลัมน์ "ผ่านการตรวจคำสำคัญ" มาจากสคริปต์ `run_live_qa_tests.py` ซึ่งตรวจแค่ว่าคำสำคัญปรากฏในคำตอบ (บางข้อตรวจเพียงมีตัวเลข เช่น `"3"`) จึงเป็นเกณฑ์หลวม ไม่ใช่การยืนยันว่าคำตอบถูก
- คอลัมน์ "ตรวจเทียบเฉลยด้วยคน" คือการอ่านคำตอบเทียบเฉลยในไฟล์ทดสอบ (ไม่ได้เทียบกับ PDF ต้นฉบับโดยตรง) ข้อที่ไม่ถูกครบ:
  - **H1** (จบใน 3.5 ปี): ได้แผนบังคับทุกเทอมแต่ไม่สรุปเป็นแผนรายเทอมที่ชัดเจน
  - **C1** (เทียบ IT 2560 กับ 2565): **ผิด** ตัวเลขหน่วยกิตรวมที่ตอบ (94→93) ผิดและขัดกันเอง เพราะ intent เทียบเวอร์ชันป้อนรายชื่อวิชาให้ LLM เรียบเรียง และฐานข้อมูลไม่มีหน่วยกิตรวมของ IT 2560
  - **C3** (แผนปกติ vs สหกิจ): **ไม่ตรงเฉลย** ระบบตอบว่าต่างกันที่ปี 3 ภาค 3 / ปี 4 ภาค 1 (วิชา 06026259) แต่เฉลยว่าปี 4 ภาค 2 ยังไม่ได้ยืนยันกับ PDF ว่าฝั่งไหนถูก (intent เทียบเวอร์ชันถูกจับผิดประเภท)
- H4: ระบบนับวิชาที่หายไป **52 วิชา** ตรงกับฐานข้อมูลปัจจุบัน (เฉลยเดิมในไฟล์ทดสอบเขียน 48)
- M8 ตอบ 12 หน่วยกิตถูกในรอบที่ตรวจ แต่ไม่คงที่ (รันซ้ำ 8 ครั้งพบเลข 12 ใน 5 ครั้ง) H5 พบ 8 ใน 8 ครั้ง
- **ประวัติ:** เดิมข้อ M8, H5, C1, C3 ตอบด้วยข้อความสำเร็จรูปที่เขียนไว้ในโค้ด (`structured_query.py`) ซึ่งทำให้ผล 28/28 ดูดีเกินจริง ถูกถอดออกแล้ว (รวมถึงเกณฑ์จบของหลักสูตรอื่นที่ยังไม่ได้ยืนยัน และข้อความ GPAX 2.00 ที่ไม่มีในเล่ม) การตรวจแผนหน่วยกิต (H7) เหลือเฉพาะ DSBA 2565 ที่ตรวจทานกับ มคอ.2 หน้า 15
- ความถูกต้องของ citation ไม่ได้ตรวจรายข้อใน `docs/tester.xlsx` วัดแยกด้วย `python -m katrag.eval.qa_eval` (19 ข้อ): precision **0.57**, recall **0.53**, retrieval hit 17/19 (ผลชุดนี้วัดก่อนถอดข้อความสำเร็จรูปออก ต้องรันใหม่)

### 7.2 สิ่งที่บันทึกใน `docs/tester.xlsx`
1. **Live System Response:** ข้อความตอบจริงจาก API พร้อมผลตรวจโดยคน (`docs/manual_review.json`) และเส้นทางประมวลผลรายข้อ (trace จากโค้ด)
2. **Citations ที่อ่านง่าย:** แสดงเอกสารและเลขหน้าที่ระบบคืนมา จัดกลุ่มตามชื่อหลักสูตร ไม่มีรหัส Hash ดิบ (ความแม่นยำของหน้าที่ชี้ ดู precision/recall ด้านบน)
3. **Challenge Criteria:**
   - **C1 (Cross-version):** ยังทำได้ไม่ดี (ดูด้านบน)
   - **C2 (Document Deduplication):** ตรวจจับคู่ M_AITBA2569 / PH_D_AITBA2569 ที่เป็นไฟล์เดียวกันด้วย SHA-256 ขนาดไฟล์ และจำนวนหน้า จากตาราง `document_relation` ได้ถูกต้อง
   - **C3 (Plan Branching):** ไม่ตรงเฉลย (ดูด้านบน)

### 7.3 คำสั่งรันการทดสอบใหม่ด้วยตนเอง (Automated Test Runner)
เมื่อเปิดเซิร์ฟเวอร์แล้ว สามารถรันชุดทดสอบ 28 ข้อเพื่อสร้างและอัปเดตไฟล์ Excel ได้ทันที:
```bash
python run_live_qa_tests.py                                   # ยิงเซิร์ฟเวอร์สด
python run_live_qa_tests.py --replay docs/reviewed_run.json    # ใช้คำตอบรอบที่คนตรวจไว้ (ไม่ต้องเปิดเซิร์ฟเวอร์)
```
ถ้ารันสดแล้วคำตอบของข้อที่เรียก LLM เปลี่ยน ผลตรวจโดยคนของข้อนั้นจะขึ้นว่า "ยังไม่ได้ตรวจ" (ผูกกับข้อความคำตอบ) ต้องอ่านเทียบเฉลยใหม่
