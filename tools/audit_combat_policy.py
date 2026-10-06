"""Audit real combat decisions independently of input-transport success."""
import argparse
from collections import Counter
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-id',required=True)
parser.add_argument('--include-run-id',action='append',default=[])
parser.add_argument('--offset',type=int,default=0)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
run_ids={args.run_id,*args.include_run_id}
searches=[];sources=Counter();requests={};choices=[];turns={};battles=[];model_decisions=[]
with (ROOT/'logs/live/runs.jsonl').open('rb') as stream:
    stream.seek(args.offset)
    for line in stream:
        if not any(value.encode() in line for value in run_ids) or not line.endswith(b'\n'):continue
        row=json.loads(line)
        if row.get('run_id') not in run_ids:continue
        status=row['status']
        if status=='search_completed':searches.append(row['search'])
        if status=='battle_complete':battles.append(dict(battle_id=row.get('battle_id'),**row['result']))
        game=row.get('before',{}).get('game_state',{})
        combat=game.get('combat_state',{})
        if combat and game.get('room_phase')=='COMBAT':
            key=(game.get('floor'),combat.get('turn'))
            hp=sum(e['current_hp'] for e in combat.get('monsters',[]))
            turns.setdefault(key,{'floor':key[0],'turn':key[1],'initial_enemy_hp':hp,'last_enemy_hp':hp})
            turns[key]['last_enemy_hp']=hp
        if status=='request_started' and 'player' in row.get('summary',{}):
            requests[row['step_id']]=[a['id'] for a in row['candidates']
                if a.get('outcome',{}).get('combat_won') and not a['outcome'].get('potions_used')]
        if status=='decision':sources[row.get('source')]+=1
        if status=='decision' and combat and row.get('source') in {'selected_turn_plan','native_action_fallback','selected_action'}:
            decision=row['decision']
            model_decisions.append({'step':row['step_id'],'floor':game.get('floor'),'turn':combat.get('turn'),
                'source':row.get('source'),'model_requests':decision.get('model_requests',1),
                'latency_ms':decision.get('latency_ms'),'input_tokens':decision.get('usage',{}).get('input_tokens'),
                'format':decision.get('model_input_format')})
        if status=='plan_selected':
            action=row['decision']['action']
            choices.append({'step':row['step_id'],'floor':game.get('floor'),'turn':combat.get('turn'),
                'sequence':action.get('description'),'checkpoint':action.get('checkpoint'),
                'selected_kill':bool(action.get('outcome',{}).get('combat_won')),
                'available_no_potion_kills':len(requests.get(row['step_id'],[])),
                'model_requests':row['decision'].get('model_requests',1)})
times=[r['latency_ms'] for r in model_decisions if isinstance(r['latency_ms'],(int,float))]
report={'run_id':args.run_id,'included_run_ids':sorted(run_ids),'searches':len(searches),
    'full_enumerations':sum(s.get('complete_enumeration',False) for s in searches),
    'fallbacks':sum(s.get('fallback_required',False) for s in searches),
    'fallback_reasons':dict(Counter(reason for s in searches for reason in s.get('fallback_reasons',s.get('truncated',[])))),
    'max_candidates':max((s.get('candidates',0) for s in searches),default=0),
    'max_search_elapsed_ms':max((s.get('search_elapsed_ms',0) for s in searches),default=0),
    'decision_sources':dict(sources),'choices':choices,'battles':battles,
    'model_decisions':model_decisions,
    'model_timing':{'decisions':len(model_decisions),'median_ms':statistics.median(times) if times else None,
                    'max_ms':max(times,default=None),'multi_request_decisions':sum(r['model_requests']>1 for r in model_decisions),
                    'formats':dict(Counter(r['format'] for r in model_decisions))},
    'turn_observations':list(turns.values()),
    'scope':'No-damage turns and declined modeled kills are observations, not proof of bad play. Turns may end in death, split, or a selection boundary.'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in {'choices','turn_observations','scope','model_decisions'}}))
