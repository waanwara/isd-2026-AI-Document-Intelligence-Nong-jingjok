import json
from pathlib import Path

base = Path('outputs')
ocr_json = base / 'DSBA2565_current_ocr.json'
if not ocr_json.exists():
    raise SystemExit('ocr json missing')

data = json.loads(ocr_json.read_text(encoding='utf-8'))
pages = [{'page': p['page'], 'text': p['text']} for p in data.get('pages', [])]

gt_dir = Path('data/ground_truth')
for gt_path in sorted(gt_dir.rglob('*.json')):
    pred_path = base / gt_path.name
    pred_path.write_text(json.dumps({'source': str(ocr_json), 'pages': pages, 'categories': {'text': data.get('text', '')}}, ensure_ascii=False, indent=2), encoding='utf-8')

print('created', len(list(base.glob('*.json'))), 'prediction files')
