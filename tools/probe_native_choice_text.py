"""Freeze identical shortlists for native-text/keyword presentation trials."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire import selectors
from slay_jev_spire.native_sequences import generate_plans
from slay_jev_spire.shortlist import select
from slay_jev_spire.native_choice_text import inline_actions,keyword_glossary,INLINE_SCOPE,KEYWORD_SCOPE

SPECS=[
 ('cultist_opening','logs/broad-shortlist-07/fe92ea5d-b8ee-47f5-880f-c4a98993c136.jsonl.gz',7),
 ('nob_weak_attack','logs/broad-shortlist-07/fe92ea5d-b8ee-47f5-880f-c4a98993c136.jsonl.gz',108),
 ('guardian_interrupt','logs/native-loop/series-04/298b8d25-5ebb-43ae-bba6-52d2cb43f9b0.jsonl.gz',175),
 ('slime_survival','logs/native-sequences/shortlist32-run1.jsonl.gz',118),
 ('nob_defend_control','logs/broad-shortlist-07/fe92ea5d-b8ee-47f5-880f-c4a98993c136.jsonl.gz',101),
]


def capture_body(summary,candidates):
    import httpx2,typesafe_sdk
    original=typesafe_sdk.TypeSafeClient;captured=[]
    def handler(request):
        body=json.loads(request.read());captured.append(body)
        keys=list(body['questions']['action']['criteria'])
        return httpx2.Response(200,json={'model':'offline-capture','answers':{'action':{
            'type':'choice','choice':keys[0],'confidence':1,'probabilities':{k:float(k==keys[0]) for k in keys}}},
            'usage':{'input_tokens':0,'output_tokens':0}})
    with patch.dict('os.environ',{'TYPESAFE_API_KEY':'offline-placeholder'}),patch.object(typesafe_sdk,'TypeSafeClient',
            lambda **kwargs:original(**kwargs,transport=httpx2.MockTransport(handler))):
        selectors._choose_jev_once(dict(summary,_combat_view='native'),candidates)
    return captured[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--registry',required=True,type=Path)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args();registry=json.loads(args.registry.read_text(encoding='utf-8'))
    jobs=[];sources=[]
    for name,relative,step in SPECS:
        with gzip.open(ROOT/relative,'rt',encoding='utf-8') as stream:
            row=next(r for r in map(json.loads,stream) if r['status']=='decision' and r['step_id']==step)
        summary=deepcopy(row['summary']);native=row['candidates']
        if name=='nob_defend_control':
            defend=deepcopy(next(c for c in summary['hand'] if c['id']=='Defend_R'))
            strike=deepcopy(next(c for pile in ('deck','draw_pile','discard_pile') for c in summary.get(pile,[]) if c['id']=='Strike_R'))
            strike.update(uuid='control-strike',is_playable=True)
            summary['hand']=[defend,strike];summary['player'].update(current_hp=12,energy=1,block=0,powers=[])
            summary['potions']=[];summary['relics']=[]
            enemy=summary['enemies'][0]
            enemy.update(current_hp=50,block=0,move_base_damage=14,move_adjusted_damage=14,move_hits=1,intent='ATTACK')
            enemy['powers']=[p for p in enemy['powers'] if p['id']=='Anger']
            assert len(enemy['powers'])==1 and enemy['powers'][0]['amount']==2
            for key in ('decision_context','candidate_generation','shortlist','_final_shortlist','identity'):
                summary.pop(key,None)
            native=[dict(id='defend',kind='play',card_uuid=defend['uuid'],target_index=None,command='PLAY 1'),
                    dict(id='strike',kind='play',card_uuid=strike['uuid'],target_index=0,command='PLAY 2 0'),
                    dict(id='end',kind='end',command='END')]
        pool,search=generate_plans(summary,native);candidates,short=select(pool)
        state=dict(summary,combat_choice_mode=search['policy'],candidate_generation=search,shortlist=short,_final_shortlist=True)
        original=capture_body(state,candidates)
        aliases={'p'+str(i):a['id'] for i,a in enumerate(candidates)}
        wire=original['state'].get('reference_state',original['state'])
        sources.append(dict(case=name,source_kind='synthetic_control' if name=='nob_defend_control' else 'actual_snapshot',run_id=row['run_id'],step=step,summary=summary,
                            candidates=candidates,aliases=aliases))
        for repeat in range(args.repeats):
            for profile in ('baseline','inline_native','inline_with_keywords'):
                body=deepcopy(original)
                if profile!='baseline':
                    for index,plan in enumerate(candidates):
                        entry=body['questions']['action']['criteria']['p'+str(index)]
                        encoded=[wire['turn_steps'][ref] for ref in entry['sequence']]
                        entry['actions']=inline_actions(summary,plan,encoded)
                    body['questions']['action']['instructions']+=INLINE_SCOPE
                if profile=='inline_with_keywords':
                    body['state']['native_keyword_glossary']=keyword_glossary(summary,registry)
                    body['questions']['action']['instructions']+=KEYWORD_SCOPE
                jobs.append(dict(case=name,repeat=repeat,profile=profile,body=body,aliases=aliases))
    args.directory.mkdir(parents=True,exist_ok=True)
    (args.directory/'requests.json').write_text(json.dumps(jobs,ensure_ascii=False),encoding='utf-8')
    (args.directory/'sources.json').write_text(json.dumps(sources,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'cases':len(sources),'requests':len(jobs),'candidate_counts':{s['case']:len(s['candidates']) for s in sources}}))


if __name__=='__main__':main()
