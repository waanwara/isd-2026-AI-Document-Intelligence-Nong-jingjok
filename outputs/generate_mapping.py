import csv
import json
import re
from pathlib import Path

base = Path('outputs')
data = json.loads((base / 'dsba2565_current_pages.json').read_text(encoding='utf-8'))
rows = []
for item in data:
    text = item['text']
    if any(k in text for k in ['หลักสูตร', 'จำนวนหน่วยกิต', 'หน่วยกิต', 'รูปแบบ', 'อาจารย์', 'สถานที่', 'หมวดที่', 'หมวดวิชา', 'ผลการเรียนรู้', 'ระบบการจัดการศึกษา', 'รายวิชา']):
        rows.append({'page': item['page'], 'snippet': re.sub(r'\s+', ' ', text[:2500]).strip()})

out_csv = base / 'dsba2565_current_mapping.csv'
with out_csv.open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['page', 'snippet'])
    writer.writeheader()
    writer.writerows(rows)

summary = {
    'document': 'DSBA2565_current.pdf',
    'program': 'DSBA',
    'curriculum_book_pages': [r['page'] for r in rows],
    'notes': 'Pages containing curriculum content and structure from the academic plan PDF.'
}
(base / 'dsba2565_current_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print('rows', len(rows))
print('pages', [r['page'] for r in rows[:20]])
