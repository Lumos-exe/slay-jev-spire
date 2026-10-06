from copy import deepcopy
from unittest.mock import patch

import pytest

from tools.audit_strategy import fixed_cases,card,fixture,objective_value
from slay_jev_spire import rules,turn_planner
from slay_jev_spire.state import prepare_native_combat
from tools.detailed_payload import plan_criteria,model_payload


@pytest.mark.parametrize('order',['original','reverse','defense_last'])
def test_live_defense_prefix_survives_search_and_final_cap(order):
    case=next(c for c in fixed_cases() if c['name']=='wide_hand_survival')
    hand=case['raw']['game_state']['combat_state']['hand']
    if order=='reverse': hand.reverse()
    if order=='defense_last': hand.sort(key=lambda c:c['type']=='SKILL')
    plans,stats=turn_planner.generate_plans(*prepare_native_combat(case['raw']))
    assert any(objective_value(p['outcome'],'survival')==(True,False,3,-75) for p in plans)
    assert len(plans)>32 and stats['beam_pruned']==0 and stats['candidate_cap_pruned']==0


def test_continuations_only_annotate_retained_candidates():
    case=fixture('draw',[card('Deep Breath',0,'SKILL',magic=1),card('Strike_R',1,damage=6)])
    draw=card('Defend_R',1,'SKILL',block=5);draw['uuid']='draw'
    case['raw']['game_state']['combat_state']['draw_pile']=[draw]
    plans,stats=turn_planner.generate_plans(*prepare_native_combat(case['raw']))
    assert stats['continuation_nodes']==0
    assert any(p['checkpoint']=='draw_cards' for p in plans)
    assert all('known_hand_continuation' not in p['outcome'] for p in plans)


def test_search_equivalence_keeps_cost_flags_and_enemy_state():
    s=rules.initial(prepare_native_combat(fixed_cases()[0]['raw'])[0])
    changed=deepcopy(s);changed['hand'][0]['free_to_play_once']=True
    assert turn_planner.search_key(s)!=turn_planner.search_key(changed)
    changed=deepcopy(s);changed['enemies'][0]['half_dead']=True
    assert turn_planner.search_key(s)!=turn_planner.search_key(changed)


def test_candidate_cap_is_reported_separately_from_enumeration():
    case=fixed_cases()[2]
    plans,stats=turn_planner.generate_plans(*prepare_native_combat(case['raw']),turn_planner.SearchConfig(beam_width=2))
    assert stats['enumeration_complete']
    assert stats['candidate_cap_pruned']==0 and stats['complete_enumeration']
    assert len(plans)>2 and stats['beam_width_ignored']


def test_position_exposes_delayed_setup_pollution_and_unknown_enemy_effects():
    case=fixture('setup',[card('Demon Form',3,'POWER',magic=2),card('Wound',-2,'STATUS')])
    combat=case['raw']['game_state']['combat_state']
    combat['energy_per_turn']=3;combat['draw_per_turn']=5
    combat['monsters'][0].update(intent='BUFF',powers=[dict(id='Ritual',name='Ritual',amount=3)],move_id=3)
    summary,actions=prepare_native_combat(case['raw'])
    plans,_=turn_planner.generate_plans(summary,actions)
    setup=next(p for p in plans if p['sequence'][0].get('card_id')=='Demon Form')
    pos=setup['outcome']['position']
    assert pos['active_cycle']['status_cards']==1
    assert pos['future_resources']['strength_at_next_start_if_no_other_effects']==2
    assert pos['future_resources']['base_energy_per_turn']==3
    assert 'enemy_move_effects:0:BUFF' in pos['uncertainties']
    assert not pos['complete_future_state']
    assert pos['enemies_after_cards'][0]['delayed_effects'][0]['amount']==3
    assert plan_criteria(setup)['position']==pos


def test_zero_time_warp_is_an_observation_boundary():
    case=fixture('time',[card('Strike_R',1,damage=6)],enemy_powers=[('Time Warp',0)])
    state=rules.initial(prepare_native_combat(case['raw'])[0])
    assert turn_planner.projection(state)['enemies'][0]['powers']['Time Warp']==0
    child=rules.play(state,rules.legal_steps(state)[0])
    assert child['checkpoint']=='time_warp'
    assert rules.outcome(child)['forecast_scope']=='partial'


def test_position_sharing_is_lossless_across_candidates():
    case=fixed_cases()[2]
    summary,actions=prepare_native_combat(case['raw'])
    plans,_=turn_planner.generate_plans(summary,actions)
    wire,criteria,_=model_payload(summary,plans)
    def expand(value):
        if isinstance(value,list): return [expand(v) for v in value]
        if not isinstance(value,dict): return value
        if '$record' in value:
            schema,values=value['$record']
            return {k:expand(v) for k,v in zip(wire['position_schemas'][schema],values)}
        if '$position_delta' in value:
            return {**expand(wire['position_baseline']),**expand(wire['position_templates'][value['$position_delta']])}
        if '$position' in value: return expand(wire['position_templates'][value['$position']])
        return {k:expand(v) for k,v in value.items()}
    for plan in plans:
        assert expand(criteria[plan['id']]['position'])==plan['outcome']['position']


def test_state_clone_isolates_cost_upgrade_powers_and_trigger_records():
    case=fixed_cases()[0]
    state=rules.initial(prepare_native_combat(case['raw'])[0]);before=deepcopy(state)
    branch=rules.clone_state(state)
    branch['hand'][0]['cost']=0
    branch['hand'][0].pop('upgrade_preview',None)
    branch['powers']['Strength']=99
    branch['enemies'][0]['powers']['Vulnerable']=2
    branch['interruptions'].append({'reason':'test'})
    branch['discard_pile'].append(branch['hand'].pop())
    assert state==before
