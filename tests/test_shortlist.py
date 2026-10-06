from copy import deepcopy
from itertools import permutations
import subprocess
import sys
import json
import random
from pathlib import Path

import pytest

from slay_jev_spire.shortlist import select,signature,action_prefix


def plans():
    result=[dict(id='end',sequence=[{'kind':'end'}])]
    for n in range(1,4):
        for order in permutations('abcde',n):
            steps=[dict(kind='play',card_uuid=x,target_index=0) for x in order]
            result.append(dict(id=''.join(order)+'_end',sequence=steps+[{'kind':'end'}]))
            result.append(dict(id=''.join(order)+'_observe',sequence=steps))
    return result


def test_32_options_cover_first_actions_lengths_and_endings():
    source=plans();before=deepcopy(source)
    chosen,stats=select(source)
    assert source==before and len(source)==171 and len(chosen)==32
    assert any(p['id']=='end' for p in chosen)
    assert any(len(p['sequence'])==1 and p['id']!='end' for p in chosen)
    assert any(sum(s['kind']!='end' for s in p['sequence'])==3 for p in chosen)
    assert stats['first_actions_retained']==stats['first_actions_available']==6
    assert stats['omitted_candidates']==139


def test_only_identical_commands_are_deduplicated():
    source=plans()[:10];duplicate=dict(source[-1],id='duplicate')
    chosen,stats=select([*source,duplicate])
    assert len(chosen)==10 and len({signature(p) for p in chosen})==10
    assert stats['exact_duplicates_removed']==1
    a=dict(id='ab',sequence=[{'kind':'play','card_uuid':'a'},{'kind':'play','card_uuid':'b'}])
    b=dict(id='ba',sequence=list(reversed(a['sequence'])))
    assert len(select([a,b])[0])==2


def test_ending_variants_do_not_crowd_out_distinct_action_strings():
    chosen,stats=select(plans())
    assert len({action_prefix(p) for p in chosen})==32
    assert stats['action_prefixes_retained']==32
    # With enough room both forms remain: observing is not ending the turn.
    pair=[p for p in plans() if p['id'] in {'a_end','a_observe'}]
    assert {p['id'] for p in select(pair)[0]}=={'a_end','a_observe'}


def test_cover_resource_combinations_before_more_orders_of_same_resources():
    source=plans();chosen,stats=select(source)
    def resources(plan):
        return frozenset(s['card_uuid'] for s in plan['sequence'] if s['kind']=='play')
    assert len({resources(p) for p in source})==26
    assert {resources(p) for p in chosen}=={resources(p) for p in source}
    assert stats['resource_combinations_retained']==stats['resource_combinations_available']==26


def test_runtime_uuid_renaming_cannot_change_selection_or_presentation():
    source=plans();baseline=[p['id'] for p in select(source)[0]]
    rng=random.Random(20261006)
    for _ in range(40):
        changed=deepcopy(source);names={}
        for p in changed:
            for step in p['sequence']:
                for key in ('card_uuid','selection_uuid'):
                    if step.get(key) is not None:
                        names.setdefault(step[key],f'{rng.getrandbits(128):032x}')
                        step[key]=names[step[key]]
        assert [p['id'] for p in select(changed)[0]]==baseline


def test_many_branches_are_not_crowded_out_by_reserved_forms():
    source=[dict(id='end',sequence=[{'kind':'end'}])]
    for i in range(30):
        first={'kind':'play','card_uuid':str(i),'target_index':0}
        source.extend([dict(id=str(i)+'_observe',sequence=[first]),
                       dict(id=str(i)+'_end',sequence=[first,{'kind':'end'}]),
                       dict(id=str(i)+'_combo',sequence=[first,{'kind':'play','card_uuid':'next'},{'kind':'end'}])])
    chosen,stats=select(source)
    assert len(chosen)==32
    assert stats['first_actions_retained']==stats['first_actions_available']==31


def test_outcomes_and_card_effects_cannot_change_shortlist_or_delete_end():
    source=plans();chosen,_=select(source)
    changed=deepcopy(source)
    for i,p in enumerate(changed):
        p['outcome']={'player_hp_after_turn':0 if i%2 else 100,'combat_won':i%3==0,'damage':10**6-i}
        p['uncertainties']=['unknown_relic'] if i%2 else []
        for step in p['sequence']:
            step.update(card_name='Brand new powerful card',card_id='UnregisteredCard',predicted_damage=999)
    after,_=select(changed)
    assert [p['id'] for p in chosen]==[p['id'] for p in after]
    assert any(p['id']=='end' for p in after)


def test_shortlist_does_not_load_a_simulator():
    code='''
import sys
from slay_jev_spire.shortlist import select
select([{'id':'end','sequence':[{'kind':'end'}]}])
assert 'slay_jev_spire.rules' not in sys.modules
assert 'slay_jev_spire.turn_planner' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_model_selects_once_without_intermediate_ranking(monkeypatch):
    from slay_jev_spire import selectors
    calls=[]
    def request(summary,actions):
        calls.append(actions)
        assert len(actions)==32
        return {'action':actions[-1],'model_requests':1}
    monkeypatch.setattr(selectors,'_request_with_transient_retry',request)
    monkeypatch.setattr(selectors,'_choose_sequence_groups',lambda *a: (_ for _ in ()).throw(AssertionError('Intermediate ranking')))
    chosen,_=select(plans())
    result=selectors.choose_jev({'player':{},'_final_shortlist':True},chosen)
    assert len(calls)==1 and result['action'] is chosen[-1]


@pytest.mark.parametrize('case',json.loads(Path('samples/shortlist_mechanical_recall.json').read_text()),ids=lambda c:c['name'])
def test_recorded_tactical_witness_recall(case):
    from slay_jev_spire.native_sequences import generate_plans
    pool,search=generate_plans(case['summary'],case['actions'])
    chosen,_=select(pool)
    witness=case['witness']
    def matches(plan):
        played=[s for s in plan['sequence'] if s['kind']=='play']
        if 'ordered_cards' in witness:
            return [s['card_id'] for s in played]==witness['ordered_cards'] and all(s.get('target_index')==witness['target'] for s in played)
        return any(s['card_id'] in witness['contains_any_card'] for s in played)
    assert search['complete_enumeration'] and any(matches(p) for p in pool)
    assert len(chosen)<=32 and any(matches(p) for p in chosen)
