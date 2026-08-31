# Lab 7B - สกัดแผนการศึกษาด้วย LLM บนเครื่องตัวเอง

> วิชา 06026240 การพัฒนาระบบอัจฉริยะ | KMITL Information Technology

## ภาพรวม

สกัดข้อมูลรายวิชาจากเล่มหลักสูตร DSBA (PDF) ด้วย LLM ที่รันบนเครื่องตัวเองผ่าน Ollama รันออฟไลน์ 100%

## โครงสร้างโปรเจค

```
Lab7_groupB_curriculum/
|-- lab7_metrics.py
|-- README.md
|-- .gitignore
|-- groupB_curriculum/
    |-- lab7b_curriculum.py
    |-- gt/
    |   |-- DSBA_academic_plan_coop.json
    |-- data/ 
    |-- output/ 
```

## การติดตั้ง

### 1. ติดตั้ง Ollama

https://ollama.com/download

### 2. ดาวน์โหลดโมเดล (~5.5 GB)

```
ollama pull scb10x/typhoon-ocr1.5-3b
ollama pull qwen3:4b
```

### 3. ติดตั้ง Python dependencies

```
pip install requests pymupdf pillow pythainlp pdfplumber
```

## วิธีใช้

### ตรวจความพร้อม

```
cd groupB_curriculum
python lab7b_curriculum.py --check
```

### รัน pipeline ทั้งหมด

```
python lab7b_curriculum.py --input data/DSBA_curriculum.pdf --pages "42-58" --gt gt/DSBA_academic_plan_coop.json --pipeline all --out output/
```

## Pipeline ที่มี

| Pipeline | วิธีการ | เหมาะกับ |
|---|---|---|
| text | ดึงข้อความตรงจาก PDF | Digital PDF |
| vlm | Typhoon-OCR + Qwen3 | PDF สแกน |
| baseline | Tesseract + regex | เส้นฐานเปรียบเทียบ |

## Metrics

- CER (Character Error Rate)
- WER (Word Error Rate, ตัดคำด้วย pythainlp)
- Exact Match Accuracy
- Precision / Recall / F1
