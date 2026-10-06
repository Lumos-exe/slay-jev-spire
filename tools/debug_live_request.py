"""Export the latest failed/requested decision for offline size regression."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.selectors import model_payload

p=ROOT/'logs/live/runs.jsonl'
with p.open('rb') as f:
    f.seek(max(0,p.stat().st_size-8_000_000))
    if f.tell(): f.readline()
    rows=[json.loads(l) for l in f if l.strip()]
row=next(r for r in reversed(rows) if r.get('status')=='request_started')
out=ROOT/'logs/live-debug';out.mkdir(exist_ok=True)
(out/'request.json').write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
state,criteria,_=model_payload(row['summary'],row['candidates'])
size=lambda x:len(json.dumps(x,ensure_ascii=False))
print(json.dumps(dict(step=row['step_id'],state_chars=size(state),criteria_chars=size(criteria),
    sections={k:size(v) for k,v in state.items()},criteria_sections={k:sum(size(v.get(k)) for v in criteria.values() if isinstance(v,dict))
    for k in ('sequence','outcome','position','notes','checkpoint','uncertainties')}),ensure_ascii=True))
