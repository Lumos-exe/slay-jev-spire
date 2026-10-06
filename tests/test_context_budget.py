from copy import deepcopy
import json
from pathlib import Path

import pytest

from slay_jev_spire import selectors
from tools import detailed_payload
from slay_jev_spire.turn_planner import generate_plans


def test_actual_floor_three_stall_preserves_all_candidates_and_facts():
    fixture=json.loads(Path('samples/context_overflow_combat.json').read_text(encoding='utf-8'))
    plans,stats=generate_plans(fixture['summary'],fixture['actions'])
    actions=plans+[a for a in fixture['actions'] if a.get('kind')=='potion' and a['id'] not in stats['planned_potion_uses']]
    original=deepcopy(actions)
    state,criteria,refs=detailed_payload.model_payload(fixture['summary'],actions)
    assert len(criteria)>34 and set(criteria)=={a['id'] for a in actions}
    assert stats['complete_enumeration'] and stats['candidate_cap_pruned']==0
    assert actions==original
    # Fixture-specific size regression, not a claim that chars equal tokens.
    assert len(json.dumps([state,criteria],ensure_ascii=False)) < len(json.dumps([fixture['summary'],actions],ensure_ascii=False))
    def expand_position(value):
        if isinstance(value,list): return [expand_position(v) for v in value]
        if not isinstance(value,dict): return value
        if '$record' in value:
            schema,values=value['$record']
            return {k:expand_position(v) for k,v in zip(state['position_schemas'][schema],values)}
        if '$position_delta' in value:
            return {**expand_position(state['position_baseline']),
                    **expand_position(state['position_templates'][value['$position_delta']])}
        if '$position' in value: return expand_position(state['position_templates'][value['$position']])
        return {k:expand_position(v) for k,v in value.items()}
    def unalias(value):
        if isinstance(value,list): return [unalias(v) for v in value]
        if not isinstance(value,dict): return value
        return {k:refs.get(v,v) if k in {'uuid','card_uuid','selection_uuid'} and isinstance(v,str)
                else unalias(v) for k,v in value.items()}
    def expand_cards(value):
        if isinstance(value,list):return [expand_cards(v) for v in value]
        if not isinstance(value,dict):return value
        if '$native' in value:
            return expand_cards(state['native_value_templates'][value['$native']])
        if '$card' in value:
            removed=value.get('$remove',[])
            value={**state['card_templates'][value['$card']],
                   **{k:v for k,v in value.items() if k not in {'$card','$remove'}}}
            for key in removed:value.pop(key,None)
        return {k:expand_cards(v) for k,v in value.items()}
    assert unalias(expand_cards({k:state[k] for k in fixture['summary']}))==fixture['summary']
    for action in plans:
        encoded=deepcopy(criteria[action['id']])
        encoded['sequence']=[state['turn_steps'][s] for s in encoded['sequence']]
        outcome=encoded['outcome']
        encoded['outcome']={**state['outcome_baseline'],**expand_position(outcome['$delta'])}
        for key in outcome.get('$remove',[]): encoded['outcome'].pop(key,None)
        encoded['position']=expand_position(encoded['position'])
        encoded['tactical_summary']=dict(zip(state['tactical_columns'],encoded['tactical_summary']))
        assert unalias(encoded)==detailed_payload.plan_criteria(action)


def test_overflow_compares_every_candidate_and_reports_finalist_probabilities(monkeypatch):
    calls=[]
    def provider(summary,actions):
        calls.append([a['id'] for a in actions])
        if len(actions)>2: raise selectors.SelectionError('too large',code='context_limit')
        best=max(actions,key=lambda a:a['utility'])
        return dict(action=best,probabilities={a['id']:float(a==best) for a in actions},
                    latency_ms=1,usage={'input_tokens':3,'output_tokens':1})
    monkeypatch.setattr(selectors,'_choose_jev_once',provider)
    actions=[dict(id=str(i),utility=i) for i in range(8)]
    result=selectors._choose_with_context_limit({},actions)
    assert result['action']==actions[-1]
    assert set().union(*(set(c) for c in calls if len(c)==2))=={a['id'] for a in actions}
    assert result['model_requests']==len(calls)
    assert set(result['probabilities'])==set(result['context_comparison']['finalists'])


@pytest.mark.parametrize('count,code',[(8,None),(2,'context_limit'),(1,'context_limit')])
def test_other_errors_and_oversized_minimum_comparison_do_not_retry(monkeypatch,count,code):
    calls=[]
    def rejected(summary,actions):
        calls.append(1)
        raise selectors.SelectionError('failure',code=code)
    monkeypatch.setattr(selectors,'_choose_jev_once',rejected)
    with pytest.raises(selectors.SelectionError):
        selectors._choose_with_context_limit({},[{'id':str(i)} for i in range(count)])
    assert len(calls)==1


def test_transient_inference_retries_are_bounded_and_counted(monkeypatch):
    calls=[]
    action={'id':'safe'}
    def provider(*args):
        calls.append(1)
        if len(calls)<3:raise selectors.SelectionError('temporary',code='transient_service',attempts=1)
        return {'action':action,'latency_ms':0,'usage':{'input_tokens':5,'output_tokens':1}}
    monkeypatch.setattr(selectors,'_choose_jev_once',provider)
    monkeypatch.setattr(selectors.time,'sleep',lambda _:None)
    result=selectors._choose_with_context_limit({},[action])
    assert result['action'] is action and result['model_requests']==3
    assert result['usage_incomplete'] and len(calls)==3
