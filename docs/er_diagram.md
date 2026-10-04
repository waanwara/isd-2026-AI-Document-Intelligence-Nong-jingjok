# ER diagram

ตารางหลักของฐานข้อมูล `artifacts/katrag.sqlite3` (ตารางทั้งหมดดูที่ `katrag/store/schema.sql`)
ทุกตารางข้อมูลมี `version_id` (ชี้ไปเวอร์ชันหลักสูตร) และ `provenance_id` (ชี้กลับพิกัดข้อความในหน้าเอกสาร)

```mermaid
erDiagram
    curriculum_version ||--o{ document : "version_id"
    document ||--o{ page : "document_id"
    page ||--o{ provenance : "document_id + page_number"

    curriculum_version ||--o{ course : "version_id"
    curriculum_version ||--o{ plan_slot : "version_id"
    curriculum_version ||--o{ rule : "version_id"
    curriculum_version ||--o{ person : "version_id"
    curriculum_version ||--o{ chunk : "version_id"

    provenance ||--o{ course : "provenance_id"
    provenance ||--o{ plan_slot : "provenance_id"
    provenance ||--o{ rule : "provenance_id"
    provenance ||--o{ person : "provenance_id"
    provenance ||--o{ chunk : "provenance_id"

    course ||--o{ plan_slot : "course_id"
    course ||--o| course_embedding : "course_id"
    chunk ||--o| chunk_embedding : "chunk_id"
    document ||--o{ document_relation : "from / to document_id"

    curriculum_version {
        int version_id PK
        text program
        int curriculum_year
        text edition_status
    }
    document {
        text document_id PK
        int version_id FK
        text sha256
        text degree_level
        text canonical_document_id FK
    }
    page {
        int page_id PK
        text document_id FK
        int page_number
        text page_text
        text extraction_method
    }
    provenance {
        int provenance_id PK
        text document_id FK
        int page_number FK
        real x0
        real y0
        real x1
        real y1
    }
    course {
        int course_id PK
        int version_id FK
        text code
        text name_th
        text name_en
        int credits_total
        int year
        int semester
        text category
        text type
        text prerequisite_json
        int provenance_id FK
    }
    plan_slot {
        int slot_id PK
        int version_id FK
        int course_id FK
        int year
        int semester
        text plan_variant
        int provenance_id FK
    }
    rule {
        int rule_id PK
        int version_id FK
        text rule_kind
        text attribute
        text comparator
        real value_numeric
        int provenance_id FK
    }
    person {
        int person_id PK
        int version_id FK
        text role
        int sequence_no
        text name_raw
        int provenance_id FK
    }
    chunk {
        int chunk_id PK
        text document_id FK
        int page_number
        int version_id FK
        text heading
        text text
        int is_boilerplate
        int provenance_id FK
    }
    chunk_embedding {
        int chunk_id PK
        text model_name
        int dim
        blob vector
    }
    course_embedding {
        int course_id PK
        int dim
        blob vector
    }
    document_relation {
        int relation_id PK
        text from_document_id FK
        text to_document_id FK
        text relation_type
    }
```

`chunk_fts` เป็น FTS5 virtual table (ดัชนีค้นด้วยคำของ `chunk.text` และ `chunk.heading`) ไม่ได้วาดในภาพ

จำนวนแถวจริง: curriculum_version 13, document 14, page 3,689, provenance 38,721, course 1,419, plan_slot 329, chunk 11,587, chunk_embedding 11,587, course_embedding 1,419, rule 2, person 126, document_relation 2
