"""Read-only causal diagnostics for the recorded avoidable-death decision.

No gameplay commands, model-choice overrides, or runtime policy changes.
"""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire import selectors
from slay_jev_spire.records import safe_text,source_manifest


def load_case():
    path=ROOT/'logs/series/20261005-b-live/failure-decisions-0.jsonl.gz'
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        rows=[json.loads(line) for line in stream]
    request=next(r for r in rows if r['step_id']==227 and r['status']=='request_started')
    return request,[r for r in rows if r['step_id']==227]


def independent_result(raw,plan):
    """Independent evaluator, deliberately limited to this exact native hand."""
    game=raw['game_state'];combat=game['combat_state'];player=combat['player']
    assert player['current_hp']==25 and player['energy']==3 and not player['powers']
    assert {r['id'] for r in game['relics']}=={'Burning Blood','Magic Flower','Unceasing Top','Incense Burner'}
    cards={c['uuid']:deepcopy(c) for c in combat['hand']}
    hp=[e['current_hp'] for e in combat['monsters']]
    assert hp==[62,0,62]
    assert [combat['monsters'][i]['move_base_damage'] for i in (0,2)]==[16,11]
    assert all({p['id'] for p in combat['monsters'][i]['powers']}=={'Split'} for i in (0,2))
    energy=3;block=0;weak=False;vulnerable=False
    for step in plan['sequence']:
        if step['kind']=='end':break
        assert step['kind']=='play'
        c=cards.pop(step['card_uuid']);cid=c['id'];native=c['native_values']
        energy-=native['cost_for_turn'];assert energy>=0
        if cid=='Armaments':
            block+=native['base_block']
            chosen=cards[step['selection_uuid']];preview=chosen['upgrade_preview']
            chosen['native_values'].update({k:v for k,v in preview.items() if k!='cost'})
            chosen['native_values']['cost_for_turn']=preview['cost']
        elif cid=='Shockwave':
            weak=vulnerable=True
        else:
            assert cid in {'Heavy Blade','Twin Strike','Body Slam'}
            target=step['target_index'];assert target in (0,2)
            amount=block if cid=='Body Slam' else native['base_damage']
            if vulnerable:amount=amount*3//2
            hp[target]-=amount*(2 if cid=='Twin Strike' else 1)
            # No option in this hand crosses a split threshold; verify this
            # restriction instead of silently approximating that mechanism.
            assert hp[target]>31
    assert cards  # Unceasing Top cannot trigger in these sequences.
    incoming=(16*3//4+11*3//4) if weak else 27
    loss=min(25,max(0,incoming-block))
    return {'enemy_hp_by_target':hp,'block':block,'remaining_energy':energy,
            'incoming_hp_loss':loss,'player_hp_after_turn':25-loss}


def static_checks(case,rows,directory):
    raw=case['before'];candidates=case['candidates'];mapping={}
    for plan in candidates:
        assert plan['kind']=='turn_plan'
        independent=independent_result(raw,plan)
        assert all(plan['outcome'][k]==v for k,v in independent.items()),plan['id']
        mapping[plan['id']]=independent
    decision=next(r['decision'] for r in rows if r['status']=='plan_selected')
    receipt=next(r for r in rows if r['status']=='action_confirmed')
    report={'recorded_source_hash':case['code_version'],'current_source_hash':source_manifest()['code_version'],
        'independently_checked_plans':len(mapping),'surviving_plans':sum(r['player_hp_after_turn']>0 for r in mapping.values()),
        'chosen_id':decision['action']['id'],'chosen_result':mapping[decision['action']['id']],
        'decision_command':next(r['decision']['action']['command'] for r in rows if r['status']=='decision'),
        'sent_command':next(r['command'] for r in rows if r['status']=='command_sent'),
        'receipt':receipt['native_receipt'],'observed_hp_after':receipt['after']['game_state']['current_hp'],
        'scope':'Independent calculation limited to this five-card hand and two slimes; does not certify the general simulator.'}
    from slay_jev_spire.state import prepare_native_combat
    from slay_jev_spire.turn_planner import generate_plans
    regenerated, stats = generate_plans(case['summary'], prepare_native_combat(raw)[1])
    assert stats['enumeration_complete'] and not stats.get('fallback_required')
    assert {p['id'] for p in regenerated} == set(mapping)
    for plan in regenerated:
        assert all(plan['outcome'][k] == v for k, v in independent_result(raw, plan).items())
    report['regenerated_plans_independently_checked'] = len(regenerated)
    report['regenerated_candidate_ids_unchanged'] = True
    # Test the real SDK request and parser for every possible returned alias.
    import typesafe_sdk,httpx2
    original_client=typesafe_sdk.TypeSafeClient
    state,criteria,_=selectors.simple_combat_payload(case['summary'],candidates)
    wire_criteria={f'p{i}':criteria[p['id']] for i,p in enumerate(candidates)}
    selected=['p0'];seen=[]
    def handler(request):
        body=json.loads(request.content)
        assert body['state']==state and body['questions']['action']['criteria']==wire_criteria
        seen.append(selected[0])
        return httpx2.Response(200,json={'model':'transport-test','usage':{'input_tokens':1,'output_tokens':1},
            'answers':{'action':{'type':'choice','choice':selected[0],'confidence':1.0,
                'probabilities':{key:float(key==selected[0]) for key in wire_criteria}}}})
    def client(**kwargs):return original_client(**kwargs,transport=httpx2.MockTransport(handler))
    with patch.dict(os.environ,{'TYPESAFE_API_KEY':'diagnostic-dummy'}),patch.object(typesafe_sdk,'TypeSafeClient',client):
        for i,action in enumerate(candidates):
            selected[0]=f'p{i}'
            parsed=selectors._choose_jev_once(case['summary'],candidates)
            assert parsed['action']==action
    report['sdk_roundtrip_mappings_verified']=len(seen)
    # Demonstrate the history-identity issue in an isolated local directory.
    from slay_jev_spire.session import RunSession
    history_dir=directory/'isolated-history';history_dir.mkdir(exist_ok=True)
    game={'seed':123,'class':'IRONCLAD','ascension_level':0,'act':1,'floor':5,
          'screen_type':'COMBAT_REWARD','screen_state':{'rewards':[{'reward_type':'CARD'}]}}
    old=[{'run_id':'old-finished-run','mode':'mock','status':'action_confirmed',
          'before':{'game_state':game},'after':{'game_state':dict(game,screen_type='CARD_REWARD')},
          'decision':{'action':{'id':'card-reward','command':'CHOOSE 0','kind':'reward','reward':{'reward_type':'CARD'}}}},
         {'run_id':'old-finished-run','mode':'mock','status':'action_confirmed',
          'before':{'game_state':dict(game,screen_type='CARD_REWARD')},'after':{'game_state':game},
          'decision':{'action':{'id':'skip','command':'SKIP','kind':'skip'}}},
         {'run_id':'old-finished-run','mode':'mock','status':'complete','result':{'victory':False}}]
    (history_dir/'runs.jsonl').write_text('\n'.join(json.dumps(r) for r in old)+'\n',encoding='utf-8')
    current=RunSession(history_dir,mode='mock',run_id='different-current-run')
    current.run_identity=(123,'IRONCLAD',0);current._restore_memory()
    report['cross_run_decline_restored']=(1,5) in current.memory.declined
    native_choices=[{'id':'claim','command':'CHOOSE 0','kind':'reward','reward':{'reward_type':'CARD'}},
                    {'id':'proceed','command':'PROCEED','kind':'proceed'}]
    report['new_run_choices_before_filter']=[a['id'] for a in native_choices]
    report['new_run_choices_after_filter']=[a['id'] for a in current.memory.filter({'game_state':game},native_choices)]
    # Regression probe: effect-relevant flags must invalidate stale plans.
    from tools.audit_strategy import fixture,card
    from slay_jev_spire.state import prepare_native_combat
    from slay_jev_spire.turn_planner import generate_plans,bind_plan_step
    from slay_jev_spire import rules
    sample=fixture('free-flag',[card('Strike_R',1,damage=6,free_to_play_once=True)],energy=1)['raw']
    original_summary,original_actions=prepare_native_combat(sample)
    plans,_=generate_plans(original_summary,original_actions)
    first=next(p['steps'][0] for p in plans if p['steps'][0]['kind']=='play')
    changed=deepcopy(sample)
    changed['game_state']['combat_state']['hand'][0]['free_to_play_once']=False
    new_summary,new_actions=prepare_native_combat(changed)
    report['reuse_accepts_changed_free_to_play_once']=bind_plan_step(first,new_summary,new_actions) is not None
    energies=[]
    for summary in (original_summary,new_summary):
        sim=rules.initial(summary);sim=rules.play(sim,rules.legal_steps(sim)[0]);energies.append(sim['energy'])
    report['energy_after_same_card_before_after_flag_change']=energies
    (directory/'static-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report,mapping


def wire_variants(case):
    state,criteria,refs=selectors.simple_combat_payload(case['summary'],case['candidates'])
    aliases={f'p{i}':p['id'] for i,p in enumerate(case['candidates'])}
    base={'state':state,'criteria':{key:criteria[ident] for key,ident in aliases.items()},
          'instructions':selectors.instructions_for(case['summary']),'aliases':aliases}
    return base


def run_probes(case,mapping,directory,repeats):
    from slay_jev_spire.config import load_jev_key
    from typesafe_sdk import Choice,RetryPolicy,TypeSafeClient,TypeSafeError
    load_jev_key();base=wire_variants(case)
    safe=next(p for p in case['candidates'] if [s.get('card_id') for s in p['sequence']]==['Armaments','Shockwave',None])
    end=next(p for p in case['candidates'] if p['sequence']==[{'kind':'end'}])
    variants=['baseline','order_only','timing_explicit','readable_steps','focused_question','two_option_control']
    manifest={'variants':variants,'repeats':repeats,'seed':20261005,
        'case':case['decision_id'],'source_hash':source_manifest()['code_version'],
        'candidate_count':len(case['candidates']),
        'scope':'One failing situation, six interventions. First five retain all candidates. Pair control changes the choice set and is diagnostic only. No gameplay.'}
    (directory/'probe-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    target=directory/'probe-results.jsonl'
    if target.exists():raise ValueError('Use a fresh directory; do not overwrite diagnostic observations.')
    rng=random.Random(20261005)
    by_id={p['id']:p for p in case['candidates']}
    for repeat in range(repeats):
        order=list(variants);rng.shuffle(order)
        for name in order:
            wire=deepcopy(base)
            if name=='order_only':
                items=list(wire['criteria'].items());rng.shuffle(items);wire['criteria']=dict(items)
            elif name=='timing_explicit':
                wire['state']['result_field_semantics']={
                    'remaining_energy':'Energy after listed card plays, BEFORE END; it is not energy carried into the next turn. No Ice Cream is owned.',
                    'block':'Block after card plays, before enemy attacks. It is not next-turn block.',
                    'player_hp_after_turn':'Absolute remaining player HP after the modeled current enemy actions. Zero means predicted death, not zero damage.',
                    'incoming_hp_loss':'HP lost during modeled end-of-turn resolution; capped by remaining HP.',
                    'enemy_hp_by_target':'Enemy HP after the listed cards, before subsequent enemy actions.'}
            elif name=='readable_steps':
                cards={c['uuid']:c['name'] for c in case['summary']['hand']}
                for alias,criterion in wire['criteria'].items():
                    p=by_id[wire['aliases'][alias]]
                    criterion['readable_sequence']=p['description']
                    criterion['selected_cards']=[cards[s['selection_uuid']] for s in p['sequence'] if s.get('selection_uuid')]
            elif name=='focused_question':
                wire['instructions']='选择一个能让玩家活过当前已知敌人攻击的计划（如果存在）。仅判断当前生存，不评价后续整局胜率。'+base['instructions']
            elif name=='two_option_control':
                wire['criteria']={key:value for key,value in wire['criteria'].items() if wire['aliases'][key] in {safe['id'],end['id']}}
            key=f'{repeat}-{name}';start=time.monotonic()
            result={'repeat':repeat,'variant':name,'candidate_count':len(wire['criteria'])}
            (directory/(key+'-input.json')).write_text(json.dumps(wire,ensure_ascii=False),encoding='utf-8')
            try:
                with TypeSafeClient(api_key=os.environ['TYPESAFE_API_KEY'],base_url='https://api.typesafe.ai',
                    model=os.environ.get('JEV_MODEL','jev-latest'),retry=RetryPolicy(max_retries=0),timeout=30) as client:
                    response=client.system_one(state=wire['state'],questions={'action':Choice(
                        instructions=wire['instructions'],criteria=wire['criteria'])})
                raw=response.raw_http_response
                actual=json.loads(raw.request.content)
                assert actual['state']==wire['state'] and actual['questions']['action']['criteria']==wire['criteria']
                (directory/(key+'-http-request.json')).write_text(safe_text(raw.request.content.decode()),encoding='utf-8')
                (directory/(key+'-http-response.json')).write_text(safe_text(raw.content.decode()),encoding='utf-8')
                answer=response.answers['action'];raw_answer=json.loads(raw.content)['answers']['action']
                assert answer.choice==raw_answer['choice'] and answer.choice in wire['criteria']
                ident=wire['aliases'][answer.choice]
                result.update(status='ok',selected_id=ident,selected=by_id[ident]['description'],
                    independent_hp=mapping[ident]['player_hp_after_turn'],model=response.model,
                    raw_choice=raw_answer['choice'],mapped_choice_correct=True,
                    choice_is_argmax=answer.probabilities[answer.choice]>=max(answer.probabilities.values()),
                    actual_option_order=list(actual['questions']['action']['criteria']),
                    input_tokens=response.usage.input_tokens)
            except TypeSafeError as error:
                result.update(status='context_limit' if 'max_tokens_exceeded' in str(error) else 'provider_error',error_type=type(error).__name__)
            result['latency_ms']=round((time.monotonic()-start)*1000,2)
            with target.open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(json.dumps(result,ensure_ascii=True),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--probe',action='store_true')
    parser.add_argument('--repeats',type=int,default=5)
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    case,rows=load_case();report,mapping=static_checks(case,rows,args.directory)
    print(json.dumps(report,ensure_ascii=True),flush=True)
    if args.probe:run_probes(case,mapping,args.directory,args.repeats)


if __name__=='__main__':main()
