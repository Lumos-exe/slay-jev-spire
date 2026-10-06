"""Replay incident inputs and optionally ask Jev; never send game commands."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans
from slay_jev_spire.selectors import choose_jev
from tools.audit_strategy import fixture,card

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--jev',action='store_true')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
with gzip.open(ROOT/'logs/latest-investigation.jsonl.gz','rt',encoding='utf-8') as f:
    requests=[r for line in f if (r:=json.loads(line))['status']=='request_started' and 'player' in r.get('summary',{})]
report={'scope':'Same saved combat states, current machine; full enumeration or explicit native-action fallback.', 'cases':[]}
def save():
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
for r in requests:
    summary,actions=prepare_native_combat(r['before'])
    plans,stats=generate_plans(summary,actions)
    report['cases'].append({'step':r['step_id'],'turn':summary['turn'],
        'floor':r['before']['game_state'].get('floor'),'search':stats,
        'old_candidates':len(r['candidates']),
        'kills':[p['description'] for p in plans if p.get('outcome',{}).get('combat_won')]})
case=fixture('3_energy_3_potions_5_cards',[card('Strike_R',1,damage=6) for _ in range(3)] +
             [card('Defend_R',1,'SKILL',block=5) for _ in range(2)],enemy_hp=100)
case['raw']['available_commands'].append('potion')
case['raw']['game_state']['potions']=[dict(id=cid,name=cid,potency=n,requires_target=False,
    can_use=True,can_discard=True) for cid,n in [('Block Potion',12),('Strength Potion',2),('Dexterity Potion',2)]]
plans,stats=generate_plans(*prepare_native_combat(case['raw']))
report['three_energy_three_potions_five_cards']=stats
report['aggregate']={'searches':len(report['cases']),
    'full_enumerations':sum(c['search']['complete_enumeration'] for c in report['cases']),
    'fallbacks':sum(c['search']['fallback_required'] for c in report['cases']),
    'max_candidates':max(c['search']['candidates'] for c in report['cases']),
    'max_elapsed_ms':max(c['search']['elapsed_ms'] for c in report['cases'])}
save()
print(json.dumps({'aggregate':report['aggregate'],'three_potions':stats}),flush=True)
if args.jev:
    from slay_jev_spire.config import load_jev_key
    load_jev_key();report['model_replays']=[]
    for step in [87,89,134]:
        r=next(r for r in requests if r['step_id']==step)
        summary,actions=prepare_native_combat(r['before'])
        plans,stats=generate_plans(summary,actions)
        if stats['fallback_required']:
            summary=dict(summary,combat_choice_mode='native_actions',search_fallback=stats['truncated'])
            candidates=actions
        else:
            candidates=plans+[a for a in actions if a.get('kind')=='potion' and a['id'] not in stats['planned_potion_uses']]
        decision=choose_jev(summary,candidates)
        evidence={'step':step,'choice':decision['action']['id'],'description':decision['action']['description'],
                  'outcome':decision['action'].get('outcome'),'candidate_count':len(candidates),
                  'model':decision.get('returned_model'),'model_requests':decision.get('model_requests'),
                  'usage':decision.get('usage'),'probabilities':decision.get('probabilities')}
        report['model_replays'].append(evidence);save()
        print(json.dumps({k:evidence[k] for k in ('step','description','candidate_count','model_requests')},ensure_ascii=True),flush=True)
