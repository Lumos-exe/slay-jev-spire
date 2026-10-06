"""Validate production B formatting on the ABC states and candidate orders."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire import selectors
from slay_jev_spire.config import load_jev_key
from tools.abc_experiment import assess_lethal

directory=ROOT/'logs/b-live/production-replays';directory.mkdir(parents=True,exist_ok=True)
cases=json.loads((ROOT/'logs/abc/20261005-controlled/cases.json').read_text(encoding='utf-8'))
orders=[json.loads(line) for line in (ROOT/'logs/abc/20261005-controlled/results.jsonl').read_text(encoding='utf-8').splitlines()]
load_jev_key();results=[]
for row in [r for r in orders if r['arm']=='B']:
    case=next(c for c in cases if c['name']==row['case'])
    mapping={a['id']:a for a in case['candidates']}
    candidates=[mapping[ident] for ident in row['candidate_order']]
    state,criteria,refs=selectors.simple_combat_payload(case['summary'],candidates)
    key=f"{row['case']}-{row['repeat']}"
    (directory/(key+'-input.json')).write_text(json.dumps({'state':state,'criteria':criteria,
        'card_aliases':refs,'instructions':selectors.instructions_for(case['summary'])},ensure_ascii=False),encoding='utf-8')
    started=time.monotonic()
    try:
        decision=selectors.choose_jev(case['summary'],candidates)
        result={'status':'ok','selected_id':decision['action']['id'],
                'selected_description':decision['action']['description'],
                'model':decision['returned_model'],'usage':decision.get('usage'),
                'format':decision['model_input_format'],'metadata_warning':decision.get('metadata_warning'),
                'request_count':decision.get('model_requests',1),'encoding_retry':decision.get('encoding_retry')}
        if case['acceptable_ids'] is not None:result['lethal_hit']=assess_lethal(case['summary'],decision['action'])
    except selectors.SelectionError as error:
        result={'status':error.code or 'selection_error'}
    result.update(case=case['name'],repeat=row['repeat'],candidate_count=len(candidates),
                  wire_chars=len(json.dumps([state,criteria],ensure_ascii=False)),
                  latency_ms=round((time.monotonic()-started)*1000,2))
    results.append(result)
    (directory/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
