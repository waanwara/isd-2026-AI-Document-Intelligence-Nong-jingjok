@echo off
chcp 65001 >nul
title Jingjok-Thorius — IT KMITL Curriculum QA Server

echo ======================================================================
echo    🦎 Jingjok-Thorius (น้องจิ้งจก-ทองหล่อ)
echo    ระบบ AI ถาม-ตอบหลักสูตร คณะเทคโนโลยีสารสนเทศ สจล.
echo ======================================================================
echo.

:: 1. ตรวจสอบการมีอยู่ของไฟล์ .env
if not exist .env (
    if exist .example.env (
        echo [INFO] ไม่พบไฟล์ .env ระบบกำลังสร้างจาก .example.env ...
        copy .example.env .env >nul
        echo [OK] สร้างไฟล์ .env เรียบร้อย
    ) else if exist .env.example (
        echo [INFO] ไม่พบไฟล์ .env ระบบกำลังสร้างจาก .env.example ...
        copy .env.example .env >nul
        echo [OK] สร้างไฟล์ .env เรียบร้อย
    )
    echo [NOTE] กรุณาตรวจสอบและตั้งค่า API Key ในไฟล์ .env หากต้องการใช้งาน LLM
    echo.
)

:: 2. ตั้งค่าสภาพแวดล้อมให้ข้าม warmup เพื่อเปิดเซิร์ฟเวอร์ได้รวดเร็ว
set KATRAG_SKIP_WARMUP=1

:: 3. ตรวจสอบคำสั่ง python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ไม่พบ Python ในระบบ! กรุณาติดตั้ง Python 3.11 และเพิ่มลงใน PATH
    echo.
    pause
    exit /b 1
)

:: 3.5 แตกไฟล์ฐานข้อมูลครั้งแรก (artifacts/katrag.sqlite3.gz -> katrag.sqlite3)
python setup_db.py
if %errorlevel% neq 0 (
    pause
    exit /b 1
)

:: 4. เปิด Web Browser อัตโนมัติหลังจากเซิร์ฟเวอร์เริ่มทำงาน
echo [INFO] กำลังเปิดเซิร์ฟเวอร์ที่ http://127.0.0.1:8000/ ...
echo [INFO] เว็บบราวเซอร์จะเปิดขึ้นโดยอัตโนมัติในอีก 2 วินาที
echo [INFO] กด Ctrl + C ในหน้าต่างนี้เมื่อต้องการหยุดเซิร์ฟเวอร์
echo ----------------------------------------------------------------------
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000/"

:: 5. รัน FastAPI Backend ผ่าน Uvicorn
python -m uvicorn katrag.api.service:app --host 127.0.0.1 --port 8000 --reload

if %errorlevel% neq 0 (
    echo.
    echo [WARN] Uvicorn ไม่สามารถเริ่มทำงานได้ กำลังลองเริ่มด้วย katrag.cli ...
    python -m katrag.cli serve
)

pause
