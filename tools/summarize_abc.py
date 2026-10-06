"""Describe the paired ABC pilot without inventing a game-value score."""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import statistics

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
args=parser.parse_args()
directory=args.directory
manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
rows=[json.loads(line) for line in (directory/'results.jsonl').read_text(encoding='utf-8').splitlines()]
identities=[(r['case'],r['repeat'],r['arm']) for r in rows]
assert len(identities)==len(set(identities))
groups=defaultdict(dict)
for row in rows:groups[(row['case'],row['repeat'])][row['arm']]=row
for group in groups.values():
    assert len({r['state_sha256'] for r in group.values()})==1
    assert len({r['options_sha256'] for r in group.values()})==1
    assert len({tuple(r['candidate_order']) for r in group.values()})==1
paired=[g for g in groups.values() if len(g)==3 and all(r['status']=='ok' for r in g.values())]
def stats(values):
    values=sorted(v for v in values if v is not None)
    return {'n':len(values),'median':statistics.median(values) if values else None,
            'p95':values[math.ceil(.95*len(values))-1] if values else None}
summary={'planned_observations':len(manifest['case_metadata'])*manifest['repeats']*3,
         'completed_observations':len(rows),'versions':sorted({r['returned_model'] for r in rows if r.get('returned_model')}),
         'paired_successful_triplets':len(paired),'arms':{},'cases':{}}
for arm in 'ABC':
    data=[r for r in rows if r['arm']==arm];ok=[r for r in data if r['status']=='ok']
    lethal=[r for r in data if 'lethal_hit' in r]
    summary['arms'][arm]={'attempts':len(data),'status_counts':dict(Counter(r['status'] for r in data)),
        'input_tokens_success':stats(r.get('usage',{}).get('input_tokens') for r in ok),
        'latency_ms_success':stats(r['latency_ms'] for r in ok),
        'latency_ms_paired_success':stats(g[arm]['latency_ms'] for g in paired),
        'wire_chars':stats(r['wire_chars'] for r in data),
        'lethal_hits':sum(r.get('lethal_hit') is True for r in lethal),
        'lethal_misses':sum(r.get('lethal_hit') is False for r in lethal),
        'lethal_no_response':sum(r.get('lethal_hit') is None for r in lethal),
        'lethal_scheduled':len(lethal)}
for case in manifest['case_metadata']:
    data=[r for r in rows if r['case']==case['name']]
    summary['cases'][case['name']]={'metric':case['metric'],'candidate_count':case['candidates'],
        'arms':{arm:{'choices':dict(Counter(r['selected_description'] for r in data if r['arm']==arm and r['status']=='ok')),
                     'statuses':dict(Counter(r['status'] for r in data if r['arm']==arm))} for arm in 'ABC'}}
summary['exact_choice_agreement']={pair:{'same':sum(g[pair[0]]['selected_id']==g[pair[1]]['selected_id'] for g in paired),
                                       'paired_triplets':len(paired)} for pair in ('AB','AC','BC')}
summary['scope']='Small observational pilot; no full-run win-rate estimate, no significance claim, no reward-weight score. Failed calls are not assigned zero latency or scored as a chosen bad plan.'
(directory/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
