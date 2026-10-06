from copy import deepcopy
import json
from pathlib import Path

from slay_jev_spire import selectors
from tools.abc_experiment import SIMPLE_FIELDS
from tools.audit_strategy import fixture,card
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans


def test_simple_rows_reconstruct_experimental_b_without_dropping_candidates():
    raw=fixture('b',[card('Bash',2,damage=8,magic=2),card('Strike_R',1,damage=6),
                     card('Defend_R',1,'SKILL',block=5)])['raw']
    summary,actions=prepare_native_combat(raw)
    plans,_=generate_plans(summary,actions);original=deepcopy((summary,plans))
    state,criteria,refs=selectors.simple_combat_payload(summary,plans,layout='rows')
    assert (summary,plans)==original
    assert tuple(state['simple_result_columns'])==SIMPLE_FIELDS
    assert set(criteria)=={p['id'] for p in plans}
    assert not {'position_templates','outcome_baseline','position_baseline'} & state.keys()
    for plan in plans:
        option=criteria[plan['id']]
        assert dict(zip(state['simple_result_columns'],option['simple_result']))=={
            key:plan['outcome'].get(key) for key in SIMPLE_FIELDS}
        sequence=[state['turn_steps'][s] for s in option['sequence']]
        decoded=[{k:refs.get(v,v) if k in {'card_uuid','selection_uuid'} else v for k,v in s.items()} for s in sequence]
        assert decoded==[{k:v for k,v in s.items() if k!='card_name' and v is not None} for s in plan['sequence']]


def test_native_facts_and_duplicate_card_identities_remain_available():
    raw=fixture('facts',[card('Strike_R',1,damage=6),card('Strike_R',1,damage=6)])['raw']
    summary,actions=prepare_native_combat(raw);plans,_=generate_plans(summary,actions)
    state,_,refs=selectors.simple_combat_payload(summary,plans)
    def expand(v):
        if isinstance(v,list):return [expand(x) for x in v]
        if not isinstance(v,dict):return v
        if '$native' in v:return expand(state['native_value_templates'][v['$native']])
        if '$card' in v:
            remove=v.get('$remove',[])
            v={**state['card_templates'][v['$card']],**{k:x for k,x in v.items() if k not in {'$card','$remove'}}}
            for k in remove:v.pop(k,None)
        return {k:refs.get(x,x) if k in {'uuid','card_uuid'} and isinstance(x,str) else expand(x) for k,x in v.items()}
    assert expand({k:state[k] for k in summary if k!='encounter_mechanics'})=={
        k:v for k,v in summary.items() if k!='encounter_mechanics'}
    assert len({c['uuid'] for c in state['hand']})==2


def test_big_actual_fixture_keeps_every_choice_with_direct_simple_rows():
    fixture_data=json.loads(Path('samples/context_overflow_combat.json').read_text(encoding='utf-8'))
    plans,stats=generate_plans(fixture_data['summary'],fixture_data['actions'])
    actions=plans+[a for a in fixture_data['actions'] if a['kind']=='potion' and a['id'] not in stats['planned_potion_uses']]
    state,criteria,_=selectors.simple_combat_payload(fixture_data['summary'],actions,layout='rows')
    assert len(criteria)>32 and set(criteria)=={a['id'] for a in actions}
    assert all(isinstance(criteria[p['id']]['simple_result'],list) for p in plans)
    assert len(json.dumps([state,criteria],ensure_ascii=False))<45000


def test_context_rejection_reencodes_all_candidates_before_grouping(monkeypatch):
    actions=[{'id':str(i),'kind':'turn_plan'} for i in range(3)]
    seen=[]
    def request(summary,candidates):
        seen.append((summary.get('simple_result_layout','objects'),[a['id'] for a in candidates]))
        if summary.get('simple_result_layout')!='rows':
            raise selectors.SelectionError('context',code='context_limit',attempts=1)
        return {'action':candidates[0],'latency_ms':1,'model_requests':1,'usage':{'input_tokens':10,'output_tokens':1}}
    monkeypatch.setattr(selectors,'_request_with_transient_retry',request)
    result=selectors._choose_with_context_limit({},actions)
    assert seen==[('objects',['0','1','2']),('rows',['0','1','2'])]
    assert result['model_requests']==2 and result['encoding_retry']['retained_candidates']==3


def test_default_uses_direct_fields_from_b():
    raw=fixture('flat',[card('Strike_R',1,damage=6)])['raw']
    summary,actions=prepare_native_combat(raw);plans,_=generate_plans(summary,actions)
    state,criteria,_=selectors.simple_combat_payload(summary,plans)
    assert 'simple_result_columns' not in state
    assert all(c['simple_result']=={k:p['outcome'].get(k) for k in SIMPLE_FIELDS}
               for p in plans for c in [criteria[p['id']]])
