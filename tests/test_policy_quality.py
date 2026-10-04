"""Outcome assertions, separate from protocol plumbing and model evaluation."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans, SearchConfig
from slay_jev_spire.selectors import validate_distribution, SelectionError


def card(name, cost, kind='ATTACK', damage=0, block=0, magic=0, target=True, **fields):
    return dict(id=name, uuid=name, name=name, type=kind, cost=cost, upgrades=0,
                is_playable=True, has_target=target, exhausts=False, ethereal=False,
                native_values=dict(source='game_card_fields', cost_for_turn=cost,
                base_damage=damage, damage=damage, base_block=block, block=block,
                magic_number=magic, base_magic_number=magic), **fields)


def battle(hand, energy=3, enemy_hp=40, enemies=1, powers=None, relics=None, draw=None):
    return dict(in_game=True, ready_for_command=True, available_commands=['play', 'end'],
        game_state=dict(seed='quality-fixture', class_='IRONCLAD', **{'class': 'IRONCLAD'},
          act=1, floor=1, current_hp=60, max_hp=80, room_phase='COMBAT',
          action_phase='WAITING_ON_USER', screen_type='NONE', is_screen_up=False,
          relics=relics or [], potions=[], combat_state=dict(turn=1, limbo=[],
            hand=hand, draw_pile=draw or [], discard_pile=[], exhaust_pile=[],
            player=dict(current_hp=60, max_hp=80, block=0, energy=energy, powers=powers or [], orbs=[]),
            monsters=[dict(id='Cultist', name='Cultist', current_hp=enemy_hp, max_hp=enemy_hp,
                block=0, powers=[], is_gone=False, half_dead=False, intent='ATTACK',
                move_adjusted_damage=12, move_hits=1) for _ in range(enemies)])))


def transition(raw, sequence):
    state = rules.initial(prepare_native_combat(raw)[0])
    for name, target, selection in sequence:
        step = next(s for s in rules.legal_steps(state) if s['card_uuid'] == name
                    and s['target_index'] == target and s['selection_uuid'] == selection)
        state = rules.play(state, step)
    return state


def test_bash_combo_is_searched_even_when_strike_is_first_in_hand():
    raw = battle([card('Strike_R', 1, damage=6), card('Bash', 2, damage=8, magic=2)], enemy_hp=16)
    plans, stats = generate_plans(*prepare_native_combat(raw))
    assert plans and len({p['id'] for p in plans}) == len(plans)
    assert all(p['outcome']['combat_won'] for p in plans)
    assert all([s.get('card_id') for s in p['sequence']] == ['Bash', 'Strike_R'] for p in plans)
    assert stats['expanded'] > 1


def test_inflame_changes_later_damage():
    raw = battle([card('Inflame', 1, 'POWER', magic=2, target=False), card('Strike_R', 1, damage=6)])
    state = transition(raw, [('Inflame', None, None), ('Strike_R', 0, None)])
    assert state['enemies'][0]['hp'] == 32
    assert state['energy'] == 1


def test_x_cost_aoe_uses_remaining_energy_and_chemical_x():
    raw = battle([card('Whirlwind', -1, damage=5, target=False)], enemies=2,
                 relics=[{'id': 'Chemical X', 'counter': -1}])
    state = transition(raw, [('Whirlwind', None, None)])
    assert [e['hp'] for e in state['enemies']] == [15, 15]
    assert state['energy'] == 0


def test_corruption_exhaust_sentinel_unlocks_later_attack():
    raw = battle([card('Corruption', 3, 'POWER', target=False),
        card('True Grit', 1, 'SKILL', block=7, target=False),
        card('Sentinel', 1, 'SKILL', block=5, magic=2, target=False), card('Strike_R', 1, damage=6)],
        powers=[{'id': 'Feel No Pain', 'name': 'Feel No Pain', 'amount': 3}])
    raw['game_state']['combat_state']['hand'][1]['upgrades'] = 1
    state = transition(raw, [('Corruption', None, None), ('True Grit', None, 'Sentinel'), ('Strike_R', 0, None)])
    assert state['energy'] == 1 and state['block'] == 13
    assert {c['id'] for c in state['exhaust_pile']} == {'True Grit', 'Sentinel'}
    assert state['enemies'][0]['hp'] == 34


def test_second_wind_counts_only_non_attacks_and_exhaust_triggers():
    raw = battle([card('Second Wind', 1, 'SKILL', block=5, target=False),
        card('Defend_R', 1, 'SKILL', block=5, target=False), card('Wound', -2, 'STATUS', target=False),
        card('Strike_R', 1, damage=6)], powers=[{'id':'Feel No Pain','name':'Feel No Pain','amount':3}])
    state = transition(raw, [('Second Wind', None, None)])
    assert state['block'] == 16
    assert [c['id'] for c in state['hand']] == ['Strike_R']


def test_fiend_fire_counts_exhausted_cards_and_strength_per_hit():
    raw = battle([card('Fiend Fire', 2, damage=7), card('Defend_R', 1, 'SKILL', target=False),
        card('Wound', -2, 'STATUS', target=False)], powers=[{'id':'Strength','name':'Strength','amount':2}])
    state = transition(raw, [('Fiend Fire', 0, None)])
    assert state['enemies'][0]['hp'] == 22
    assert len(state['exhaust_pile']) == 3


def test_armaments_uses_game_upgrade_preview_in_next_attack():
    strike = card('Strike_R', 1, damage=6, upgrade_preview=dict(cost=1, base_damage=9, base_block=0, magic_number=0, upgrades=1))
    raw = battle([card('Armaments', 1, 'SKILL', block=5, target=False), strike])
    state = transition(raw, [('Armaments', None, 'Strike_R'), ('Strike_R', 0, None)])
    assert state['enemies'][0]['hp'] == 31 and state['block'] == 5


def test_draw_is_an_information_boundary_not_a_guessed_followup():
    raw = battle([card('Pommel Strike', 1, damage=9, magic=1)], draw=[card('Bash', 2, damage=8)])
    plans, _ = generate_plans(*prepare_native_combat(raw))
    drawn = [p for p in plans if p['checkpoint'] == 'draw_cards']
    assert drawn
    assert all(len(p['sequence']) == 1 and not p['outcome']['combat_won'] for p in drawn)


def test_headbutt_selection_restores_known_card_for_later_draw():
    raw = battle([card('Headbutt', 1, damage=9), card('Pommel Strike', 1, damage=9, magic=1)], energy=4)
    raw['game_state']['combat_state']['discard_pile'] = [card('Bash', 2, damage=8, magic=2)]
    state = transition(raw, [('Headbutt', 0, 'Bash'), ('Pommel Strike', 0, None), ('Bash', 0, None)])
    assert state['enemies'][0]['hp'] == 14
    assert state['energy'] == 0 and not state['checkpoint']


def test_heavy_blade_strength_weak_and_vulnerable_round_once():
    raw = battle([card('Heavy Blade', 2, damage=14, magic=3)],
        powers=[{'id':'Strength','name':'Strength','amount':2},{'id':'Weakened','name':'Weak','amount':1}])
    raw['game_state']['combat_state']['monsters'][0]['powers']=[{'id':'Vulnerable','name':'Vulnerable','amount':1}]
    assert transition(raw, [('Heavy Blade',0,None)])['enemies'][0]['hp'] == 18


def test_search_width_and_truncation_are_reported():
    raw = battle([card('Strike_R',1,damage=6), card('Bash',2,damage=8,magic=2)])
    plans, stats = generate_plans(*prepare_native_combat(raw), SearchConfig(beam_width=2,max_nodes=1))
    assert len(plans) <= 2 and stats['expanded'] == 1
    assert 'node_budget' in stats['truncated'] and not stats['complete_enumeration']


def test_unknown_relic_is_visible_and_never_certifies_lethal():
    raw = battle([card('Strike_R',1,damage=6)], enemy_hp=1, relics=[{'id':'modded','counter':0}])
    plans, _ = generate_plans(*prepare_native_combat(raw))
    assert plans and all(not p['outcome']['combat_won'] for p in plans)
    assert any('unmodeled_relic:modded' in p['uncertainties'] for p in plans)


@pytest.mark.parametrize('probabilities', [None, {'A':1}, {'A':float('nan'),'B':0}, {'A':0.1,'B':0.1}, {'A':-0.1,'B':1.1}])
def test_invalid_probabilities_are_not_silently_invented(probabilities):
    answer=SimpleNamespace(choice='A', confidence=0.7, probabilities=probabilities)
    with pytest.raises(SelectionError): validate_distribution(answer,[{'id':'A'},{'id':'B'}])


def test_valid_probabilities_preserve_confidence_and_margin():
    answer=SimpleNamespace(choice='A', confidence=0.6, probabilities={'A':0.8,'B':0.2})
    distribution, margin=validate_distribution(answer,[{'id':'A'},{'id':'B'}])
    assert distribution==answer.probabilities and margin==pytest.approx(0.6)


def test_native_fixed_counts_do_not_use_unset_magic_number():
    twin = card('Twin Strike', 1, damage=5, magic=-1)
    shrug = card('Shrug It Off', 1, 'SKILL', block=8, magic=-1, target=False)
    raw = battle([twin, shrug], draw=[card('Strike_R', 1, damage=6)])
    state = transition(raw, [('Twin Strike', 0, None), ('Shrug It Off', None, None)])
    assert state['enemies'][0]['hp'] == 30
    assert state['draws'] == 1 and state['checkpoint'] == 'draw_cards'


@pytest.mark.parametrize('name,cost,kind,damage,magic,target,expected', [
    ('Clothesline',2,'ATTACK',12,2,True,9), ('Uppercut',2,'ATTACK',13,1,True,9),
    ('Berserk',0,'POWER',0,2,False,18), ('Disarm',1,'SKILL',0,2,True,10)])
def test_changed_powers_recompute_incoming_damage(name,cost,kind,damage,magic,target,expected):
    raw = battle([card(name,cost,kind,damage=damage,magic=magic,target=target)])
    state = transition(raw, [(name,0 if target else None,None)])
    assert rules.outcome(state)['incoming_hp_loss'] == expected


def test_native_corruption_marker_makes_skill_free_and_exhausts_it():
    raw = battle([card('Defend_R',1,'SKILL',block=5,target=False)], energy=0,
        powers=[{'id':'Corruption','name':'Corruption','amount':-1}])
    state = transition(raw, [('Defend_R',None,None)])
    assert state['energy'] == 0 and state['block'] == 5
    assert state['exhaust_pile'][0]['id'] == 'Defend_R'


def test_akabeko_uses_native_vigor_once():
    raw = battle([card('Strike_R',1,damage=6)], relics=[{'id':'Akabeko','counter':-1}],
        powers=[{'id':'Vigor','name':'Vigor','amount':8}])
    assert transition(raw,[('Strike_R',0,None)])['enemies'][0]['hp'] == 26


def test_end_turn_random_trigger_cannot_be_called_deterministic():
    dazed=card('Dazed',-2,'STATUS',target=False);dazed['ethereal']=True
    raw=battle([dazed],enemies=2,powers=[{'id':'Feel No Pain','name':'Feel No Pain','amount':3},
        {'id':'Juggernaut','name':'Juggernaut','amount':5}])
    out=rules.outcome(rules.initial(prepare_native_combat(raw)[0]))
    assert out['forecast_scope']=='partial' and out['incoming_hp_loss'] is None


def test_search_and_choice_share_one_decision_id(tmp_path):
    import json
    from slay_jev_spire.session import RunSession
    s=RunSession(tmp_path,mode='mock')
    s.receive(battle([card('Strike_R',1,damage=6)]))
    rows=[json.loads(x) for x in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    relevant=[r for r in rows if r['status'] in {'search_completed','request_started','plan_selected'}]
    assert len(relevant)==3 and len({r['decision_id'] for r in relevant})==1
    assert relevant[0]['decision_id'] is not None


def test_resume_keeps_planned_selection_without_spending_api_budget(tmp_path):
    from slay_jev_spire.session import RunSession, resume_session
    s=RunSession(tmp_path,mode='mock',max_decisions=1)
    s.planned_selection='Strike_R';s.plan_metadata={'plan_id':'chosen-plan'}
    s.calls=1;s.stopped=True;s.reason='paused'
    resumed=resume_session(s,1)
    assert resumed.planned_selection=='Strike_R' and resumed.plan_metadata==s.plan_metadata
    resumed.max_decisions=1
    raw=battle([card('Strike_R',1,damage=6)])
    g=raw['game_state'];g.update(screen_type='HAND_SELECT',is_screen_up=True,choice_list=['strike_r'])
    g['screen_state']={'hand':g['combat_state']['hand'],'selected':[],'max_cards':1}
    raw['available_commands']=['choose','state']
    assert resumed.receive(raw)==['STATE']
    assert resumed.receive(raw)==['CHOOSE 0']
    assert resumed.calls==1


def test_slimed_is_playable_without_medical_kit():
    state=transition(battle([card('Slimed',1,'STATUS',target=False)]), [('Slimed',None,None)])
    assert state['energy']==2 and state['exhaust_pile'][0]['id']=='Slimed'


def test_generated_wounds_allow_power_through_second_wind_combo():
    raw=battle([card('Power Through',1,'SKILL',block=15,target=False),
                card('Second Wind',1,'SKILL',block=5,target=False)])
    plans,_=generate_plans(*prepare_native_combat(raw))
    combo=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['Power Through','Second Wind',None])
    assert combo['outcome']['block']==25 and combo['outcome']['exhaust_count']==2
    assert combo['checkpoint'] is None


def test_generated_card_uuid_is_bound_from_observed_game_state():
    from slay_jev_spire.turn_planner import bind_plan_step
    raw=battle([card('Power Through',1,'SKILL',block=15,target=False),
                card('Second Wind',1,'SKILL',block=5,target=False)])
    plans,_=generate_plans(*prepare_native_combat(raw))
    combo=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['Power Through','Second Wind',None])
    after=deepcopy(raw);c=after['game_state']['combat_state']
    c['discard_pile'].append(c['hand'].pop(0));c['player'].update(energy=2,block=15)
    for uid in ['real-uuid-a','real-uuid-b']:
        wound=card('Wound',-2,'STATUS',target=False);wound['uuid']=uid
        c['hand'].append(wound)
    action=bind_plan_step(combo['steps'][1],*prepare_native_combat(after))
    assert action and action['card_uuid']=='Second Wind'


def test_fiend_fire_exhaust_block_arrives_after_thorns_damage():
    raw=battle([card('Fiend Fire',2,damage=7),card('Wound',-2,'STATUS',target=False)],enemy_hp=5,
        powers=[{'id':'Feel No Pain','name':'Feel No Pain','amount':3}])
    c=raw['game_state']['combat_state'];c['player']['current_hp']=2
    c['monsters'][0]['powers']=[{'id':'Thorns','name':'Thorns','amount':3}]
    state=transition(raw,[('Fiend Fire',0,None)])
    assert state['hp']==0 and not rules.outcome(state)['combat_won']


def test_combust_stacks_independent_hp_cost():
    a=card('Combust',1,'POWER',magic=5,target=False);b=deepcopy(a);b['uuid']='second-combust'
    raw=battle([a,b]);raw['game_state']['combat_state']['player']['current_hp']=2
    raw['game_state']['combat_state']['monsters'][0]['intent']='BUFF'
    state=transition(raw,[('Combust',None,None),('second-combust',None,None)])
    assert state['combust_hp_loss']==2 and rules.outcome(state)['player_hp_after_turn']==0


@pytest.mark.parametrize('power',['Constricted','Poison','Regeneration','Malleable','Sharp Hide'])
def test_unimplemented_triggers_do_not_claim_deterministic_survival(power):
    raw=battle([card('Defend_R',1,'SKILL',block=5,target=False)],
        powers=[{'id':power,'name':power,'amount':6}])
    raw['game_state']['combat_state']['player']['current_hp']=5
    raw['game_state']['combat_state']['monsters'][0]['intent']='BUFF'
    state=rules.initial(prepare_native_combat(raw)[0]);out=rules.outcome(state)
    assert out['forecast_scope']=='partial' and out['player_hp_after_turn'] is None
    assert 'unmodeled_power:'+power in state['uncertainties']


def test_grid_preview_and_transform_confirmation_require_exact_card_uuid():
    from slay_jev_spire.screens import prepare_screen, confirm_screen
    raw=battle([card('Strike_R',1,damage=6)])
    g=raw['game_state']; selected=g['combat_state']['hand'][0]
    g.update(screen_type='GRID',is_screen_up=True,room_phase='EVENT',deck=[selected],choice_list=['strike_r'],
        screen_state=dict(cards=[selected],selected_cards=[],for_transform=True,confirm_up=False,num_cards=1))
    raw['available_commands']=['choose']
    action=prepare_screen(raw)[0]
    preview=deepcopy(raw);p=preview['game_state'];p['choice_list']=[]
    preview['available_commands']=['confirm'];p['screen_state'].update(confirm_up=True,pending_card_uuid='Strike_R')
    assert confirm_screen(raw,preview,action)
    wrong=deepcopy(preview);wrong['game_state']['screen_state']['pending_card_uuid']='wrong-card'
    assert confirm_screen(raw,wrong,action) is None
    confirm=prepare_screen(preview)[0]
    after=deepcopy(preview);after['game_state'].update(screen_type='EVENT',screen_state={})
    assert confirm_screen(preview,after,confirm) is None
    after['game_state']['deck']=[card('Bash',2,damage=8,magic=2)]
    assert confirm_screen(preview,after,confirm)


def test_separate_end_block_events_each_trigger_juggernaut():
    raw=battle([card('Strike_R',1,damage=6)],enemy_hp=8,powers=[
        {'id':'Metallicize','name':'Metallicize','amount':3},
        {'id':'Plated Armor','name':'Plated Armor','amount':3},
        {'id':'Juggernaut','name':'Juggernaut','amount':5}])
    out=rules.outcome(rules.initial(prepare_native_combat(raw)[0]))
    assert out['incoming_hp_loss']==0


def test_orichalcum_checks_block_before_end_turn_power_gains():
    raw=battle([card('Strike_R',1,damage=6)],relics=[{'id':'Orichalcum','counter':-1}],
        powers=[{'id':'Metallicize','name':'Metallicize','amount':3}])
    out=rules.outcome(rules.initial(prepare_native_combat(raw)[0]))
    assert out['incoming_hp_loss']==3


def test_havoc_with_no_draw_or_discard_cards_has_no_invented_value():
    state=transition(battle([card('Havoc',1,'SKILL',target=False)]), [('Havoc',None,None)])
    assert state['generated']==0 and state['checkpoint'] is None


def test_card_reward_can_return_to_an_event_after_acquisition():
    from slay_jev_spire.session import confirmation
    before=battle([]);before['game_state'].update(screen_type='CARD_REWARD',deck=[])
    action={'kind':'card','command':'CHOOSE 0','card':{'id':'Shrug It Off'}}
    after=deepcopy(before);after['game_state'].update(screen_type='EVENT',deck=[{'id':'Shrug It Off'}])
    assert confirmation(before,after,action)=='card_added_to_deck'
    after['game_state']['deck']=[]
    assert confirmation(before,after,action) is None


def test_deep_breath_plus_shuffles_then_draws_without_becoming_unknown():
    breath=card('Deep Breath',0,'SKILL',magic=2,target=False);breath['upgrades']=1
    raw=battle([breath,card('Strike_R',1,damage=6)],draw=[card('Bash',2,damage=8,magic=2)])
    raw['game_state']['combat_state']['discard_pile']=[card('Defend_R',1,'SKILL',block=5,target=False)]
    state=transition(raw,[('Deep Breath',None,None)])
    assert state['draws']==2 and state['energy']==3 and state['checkpoint']=='draw_cards'
    assert not state['uncertainties']
    assert {c['id'] for c in state['draw_pile']}=={'Bash','Defend_R'}
    assert [c['id'] for c in state['discard_pile']]==['Deep Breath']
    out=rules.outcome(state)
    assert out['incoming_hp_loss'] is None and out['standing_hp_loss_estimate']==12


def test_no_draw_blocks_breath_draw_but_not_shuffle_or_sundial():
    raw=battle([card('Deep Breath',0,'SKILL',magic=2,target=False)],
        powers=[{'id':'NoDraw','name':'No Draw','amount':-1}],relics=[{'id':'Sundial','counter':2}])
    raw['game_state']['combat_state']['discard_pile']=[card('Strike_R',1,damage=6)]
    state=transition(raw,[('Deep Breath',None,None)])
    assert state['draws']==0 and state['energy']==5 and state['relics']['Sundial']==0


def test_draw_prefix_is_retained_with_energy_for_the_new_cards():
    hand=[card('Deep Breath',0,'SKILL',magic=2,target=False),card('Bash',2,damage=8,magic=2)]
    for i in range(3):
        strike=card('Strike_R',1,damage=6);strike['uuid']=f'strike-{i}';hand.append(strike)
    raw=battle(hand,draw=[card('Defend_R',1,'SKILL',block=5,target=False),card('Anger',0,damage=6)])
    plans,_=generate_plans(*prepare_native_combat(raw),SearchConfig(beam_width=4))
    assert any(p['sequence'][0].get('card_id')=='Deep Breath' and p['outcome']['remaining_energy']==3 for p in plans)


def test_zero_energy_draw_has_no_invented_affordable_cards():
    raw=battle([card('Deep Breath',0,'SKILL',magic=2,target=False)],energy=0,
        draw=[card('Strike_R',1,damage=6),card('Defend_R',1,'SKILL',block=5,target=False)])
    state=transition(raw,[('Deep Breath',None,None)])
    assert state['draw_prospects'][0]['expected_affordable_draws']==0
    assert state['draw_prospects'][0]['pool_size']==2


def test_draw_plan_includes_conditional_continuation_of_existing_hand():
    strike=card('Strike_R',1,damage=6)
    raw=battle([card('Deep Breath',0,'SKILL',magic=2,target=False),strike],
        draw=[card('Defend_R',1,'SKILL',block=5,target=False)])
    plans,_=generate_plans(*prepare_native_combat(raw))
    prefix=next(p for p in plans if len(p['sequence'])==1 and p['sequence'][0].get('card_id')=='Deep Breath')
    continuation=prefix['outcome']['known_hand_continuation']
    assert continuation['sequence']==[{'card_id':'Strike_R','target_index':0}]
    assert continuation['outcome']['enemy_hp']==34
    assert continuation['outcome']['forecast_scope']=='conditional_known_hand'
    assert prefix['outcome']['forecast_scope']=='partial' and not prefix['outcome']['combat_won']
