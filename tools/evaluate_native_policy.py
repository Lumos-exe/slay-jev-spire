"""Predeclared native-action protocol comparisons; never executes game commands."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import argparse
import gzip
import json
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def build_cases(directory):
    from slay_jev_spire.screens import prepare_journey
    source=ROOT/'logs/series/20261006-observed-two';cases=[]
    def add(name,raw,expected):
        summary,actions=prepare_journey(raw)
        wanted=[a['id'] for a in actions if expected(a,summary)]
        assert wanted and len(wanted)<len(actions),name
        cases.append(dict(name=name,raw=raw,acceptable_ids=wanted))
    records=[]
    with gzip.open(source/'run-0.jsonl.gz','rt',encoding='utf-8') as f:
        records=[json.loads(line) for line in f]
    free_attack=next(r['before'] for r in records if r['status']=='command_sent' and r['step_id']==68)
    add('sentry_unused_energy',free_attack,lambda a,s:a['kind']=='play')
    for step in (67,68):
        raw=json.loads((source/f'run1-case-{step}.json').read_text(encoding='utf-8'))['before']
        add(f'gremlin_idle_{step}',raw,lambda a,s:a['kind']=='play')
    raw=json.loads((source/'case-274.json').read_text(encoding='utf-8'))['before']
    add('hex_do_not_add_dazed',raw,lambda a,s:a['kind']=='end')
    # Wait control: one Defend, a nonattacking Nob, and an active Enrage penalty.
    control=deepcopy(raw);g=control['game_state'];c=g['combat_state']
    c['hand']=[next(card for card in c['hand'] if card['id']=='Defend_R')]
    c['player'].update(energy=3,powers=[])
    enemy=c['monsters'][0]
    enemy.update(id='GremlinNob',name='Gremlin Nob',intent='BUFF',move_id=3,
        move_adjusted_damage=-1,powers=[{'id':'Anger','name':'Enrage','amount':2,
            'native_description':'Whenever you play a Skill, this enemy gains 2 Strength.'}])
    c['monsters']=[enemy];g['relics']=[];g['potions']=[]
    for card in c['hand']:card['is_playable']=True
    add('wait_is_correct_against_nob',control,lambda a,s:a['kind']=='end')
    # Independent controls drawn from other actual encounters, not adjacent frames.
    used=set()
    for file in ('run-0.jsonl.gz','run-1.jsonl.gz'):
        with gzip.open(source/file,'rt',encoding='utf-8') as f:
            for line in f:
                r=json.loads(line)
                if r['status']!='request_started':continue
                raw=r['before'];g=raw.get('game_state',{});c=g.get('combat_state',{})
                key=(r['run_id'],g.get('floor'))
                if key in used or g.get('screen_type')!='NONE' or not c:continue
                live=[(i,e) for i,e in enumerate(c['monsters']) if e['current_hp']>0 and not e['is_gone']]
                if len(live)!=1:continue
                i,e=live[0]
                if {p['id'] for p in e['powers']}-{'Vulnerable','Weakened','Strength','Ritual','Artifact'}:continue
                kills=set()
                for card in c['hand']:
                    if card['id'] not in {'Strike_R','Bash','Pommel Strike','Iron Wave'} or not card['is_playable']:continue
                    preview=next((v for v in card.get('target_damage_previews',[]) if v['target_index']==i),{})
                    if preview.get('damage_before_block',0)>=e['current_hp']+e['block']:kills.add(card['uuid'])
                if not kills:continue
                add(f'kill_control_{len(used)}',raw,lambda a,s:a.get('card_uuid') in kills and a.get('target_index')==i)
                used.add(key)
                if len(used)==3:break
        if len(used)==3:break
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'cases.json').write_text(json.dumps(cases,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'cases':len(cases),'names':[c['name'] for c in cases]}))


def run(directory,repeats):
    from slay_jev_spire.config import load_jev_key
    from slay_jev_spire.screens import prepare_journey
    from slay_jev_spire.state import enrich_summary
    from slay_jev_spire.native_catalog import NativeCatalogStore
    from slay_jev_spire import selectors
    from slay_jev_spire.combat_protocol import choose_reviewed
    from slay_jev_spire.jev_provider import capture_http
    from slay_jev_spire.records import source_manifest
    load_jev_key()
    cases=json.loads((directory/'cases.json').read_text(encoding='utf-8'))
    catalog=NativeCatalogStore(ROOT/'data/native-catalog.json').refresh()
    profiles=['native_baseline','native_readable','native_compare']
    manifest={'profiles':profiles,'repeats':repeats,'cases':[c['name'] for c in cases],
        'source_hash':source_manifest()['code_version'],'catalog_hash':catalog.version,
        'scope':'Same current native legal actions and same order per repeat. No gameplay. Cases test specific tactical failures, not whole-run optimality.'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    result_path=directory/'results.jsonl'
    if result_path.exists():raise ValueError('Use a fresh result directory')
    def evaluate(case,profile,repeat):
        started=time.monotonic();summary,actions=prepare_journey(case['raw']);summary=enrich_summary(summary,catalog.localization())
        if 'player' in summary:summary['combat_choice_mode']='native_actions'
        random.Random(20261006+repeat).shuffle(actions)
        key=f'{case["name"]}:{profile}:{repeat}'
        result=dict(case=case['name'],profile=profile,repeat=repeat,options=len(actions),order=[a['id'] for a in actions])
        try:
            with capture_http(directory,key):
                decision=(selectors._choose_with_context_limit(summary,actions) if profile=='native_baseline'
                    else choose_reviewed(summary,actions,selectors._choose_with_context_limit,review=profile=='native_compare'))
            result.update(status='ok',selected_id=decision['action']['id'],selected_command=decision['action']['command'],
                accepted=decision['action']['id'] in case['acceptable_ids'],model=decision['returned_model'],
                model_requests=decision.get('model_requests',1),review=decision.get('decision_review'))
        except selectors.SelectionError as error:result.update(status=error.code or 'selection_error',accepted=False)
        result['elapsed_ms']=round((time.monotonic()-started)*1000,2)
        return result
    jobs=[(c,p,n) for n in range(repeats) for c in cases for p in profiles]
    random.Random(20261006).shuffle(jobs)
    with ThreadPoolExecutor(max_workers=4) as pool, result_path.open('a',encoding='utf-8') as out:
        for future in as_completed([pool.submit(evaluate,*job) for job in jobs]):
            result=future.result();out.write(json.dumps(result,ensure_ascii=False)+'\n');out.flush()
            print(json.dumps(result,ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--build',action='store_true');parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    build_cases(args.directory) if args.build else run(args.directory,args.repeats)
