"""Validate the captured stalled request against Jev, without game commands."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.config import load_jev_key
from slay_jev_spire.selectors import choose_jev

row=json.loads((ROOT/'logs/live-debug/request.json').read_text(encoding='utf-8'))
load_jev_key()
decision=choose_jev(row['summary'],row['candidates'])
result={k:v for k,v in decision.items() if k!='action'}
result['selected_action']=decision['action']['id']
(ROOT/'logs/live-debug/replay-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result.get(k) for k in ('selected_action','returned_model','usage','model_requests','model_input_format')},ensure_ascii=True))
