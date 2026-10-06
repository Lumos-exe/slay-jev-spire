"""Read-only accounting of actual sequence choices and observed boundaries."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


def audit(path):
    runs = {}
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n'):
                break
            row = json.loads(line)
            run = runs.setdefault(row['run_id'], dict(sources=Counter(), chosen_lengths=Counter(),
                boundaries=Counter(), truncated=Counter(), generation_ms=[], model_ms=[],
                plan_choices=0, searches=0, returned_candidates=[], latest_plans=[], model_requests=0))
            run['last_status'] = row['status']; run['last_step'] = row.get('step_id')
            if row['status']=='search_completed':
                search=row['search']; run['searches']+=1
                run['truncated'].update(search.get('truncated',[]))
                run['generation_ms'].append(search['elapsed_ms'])
                run['returned_candidates'].append(search['candidates'])
            if row['status']=='plan_selected':
                decision=row['decision']; plan=decision['action']
                run['plan_choices']+=1
                run['chosen_lengths'][sum(s['kind']!='end' for s in plan['sequence'])]+=1
                run['model_ms'].append(decision.get('latency_ms',0))
                run['model_requests']+=decision.get('model_requests',1)
                game=row['before']['game_state']
                run['latest_plans'].append(dict(step=row['step_id'], floor=game['floor'],
                    turn=game.get('combat_state',{}).get('turn'), description=plan['description'],
                    checkpoint=plan.get('checkpoint'), latency_ms=decision.get('latency_ms')))
                run['latest_plans']=run['latest_plans'][-6:]
            if row['status']=='decision': run['sources'].update([row.get('source')])
            if row['status'] in {'plan_invalidated','checkpoint_reached'}:
                run['boundaries'].update([row.get('reason')])
            if row['status'] in {'stopped','complete'}:
                run['result']={k:row.get(k) for k in ('status','reason','result','message')}
    for run in runs.values():
        for field in ('generation_ms','model_ms','returned_candidates'):
            values=run[field]
            run[field]={'median':statistics.median(values) if values else None,'max':max(values,default=None)}
    return runs


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log',type=Path,default=Path(__file__).resolve().parents[1]/'logs/live/runs.jsonl')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(); result=json.dumps(audit(args.log),ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(result,encoding='utf-8')
    print(result)
