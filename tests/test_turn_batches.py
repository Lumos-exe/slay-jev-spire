from copy import deepcopy
import pytest

from tests.test_lethal_plan import combat
from slay_jev_spire.screens import prepare_journey
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock


def battle():
    raw = combat(); c = raw['game_state']['combat_state']
    c['monsters'][0].update(current_hp=40, move_adjusted_damage=12, move_hits=1)
    for card in c['hand']:
        card['native_values'].update(base_damage=6, block=0, base_block=-1, magic_number=-1, base_magic_number=-1)
    defend = deepcopy(c['hand'][0])
    defend.update(id='Defend_R', uuid='defend', name='Defend', has_target=False)
    defend['native_values'].update(base_damage=-1, damage=0, base_block=5, block=5)
    defend.pop('target_damage_previews')
    c['hand'].append(defend)
    return raw


def test_turn_candidates_simulate_attack_defense_tradeoff():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle()
    plans = turn_plans(*prepare_journey(raw))
    assert any(p['outcome']['enemy_hp'] == 22 and p['outcome']['incoming_hp_loss'] == 12 for p in plans)
    assert any(p['outcome']['enemy_hp'] == 28 and p['outcome']['incoming_hp_loss'] == 7 for p in plans)
    assert all(p['steps'][-1]['kind'] == 'end' for p in plans)


def test_one_selector_call_executes_three_attacks_and_end_with_rebound_indices(tmp_path):
    calls = []
    def select(summary, actions):
        calls.append(actions)
        assert all(a['kind'] == 'turn_plan' for a in actions)
        return choose_mock(summary, sorted(actions, key=lambda a: a['outcome']['enemy_hp']))
    raw = battle()
    s = RunSession(tmp_path, mode='mock', selector=select,planning_mode='enumerate')
    for _ in range(3):
        assert s.receive(raw) == ['STATE']
        assert s.receive(raw) == ['PLAY 1 0']
        s.command_sent('PLAY 1 0')
        raw = deepcopy(raw)
        c = raw['game_state']['combat_state']
        c['discard_pile'].append(c['hand'].pop(0)); c['player']['energy'] -= 1; c['monsters'][0]['current_hp'] -= 6
        for card in c['hand']: card['is_playable'] = c['player']['energy'] >= card['cost']
    assert s.receive(raw) == ['STATE']
    assert s.receive(raw) == ['END']
    assert len(calls) == 1 and s.calls == 1


def test_one_choice_executes_potion_then_body_slam_and_end(tmp_path):
    from tests.test_policy_quality import battle as quality_battle, card
    raw=quality_battle([card('Body Slam',1)],energy=1,enemy_hp=40)
    raw['available_commands'].append('potion')
    game=raw['game_state'];combat=game['combat_state']
    combat['player'].update(current_hp=79,block=13);game['current_hp']=79
    combat['monsters'][0].update(move_base_damage=7,move_adjusted_damage=7,move_hits=6)
    game['potions']=[{'id':'Block Potion','name':'Block Potion','potency':12,
        'can_use':True,'can_discard':True,'requires_target':False},
        {'id':'PowerPotion','name':'Power Potion','potency':1,
        'can_use':True,'can_discard':True,'requires_target':False}]
    seen=[]
    def select(summary,actions):
        seen.append(actions)
        # Known use is represented by complete plans; unknown use still exists.
        assert not any(a.get('kind')=='potion' and a.get('potion_id')=='Block Potion'
                       and a.get('subaction')=='use' for a in actions)
        assert any(a.get('kind')=='potion' and a.get('potion_id')=='PowerPotion'
                   and a.get('subaction')=='use' for a in actions)
        chosen=next(a for a in actions if a.get('kind')=='turn_plan'
                    and [s['kind'] for s in a['sequence']]==['potion','play','end'])
        assert chosen['outcome']['enemy_hp']==15
        assert chosen['outcome']['incoming_hp_loss']==17
        return choose_mock(summary,[chosen])
    session=RunSession(tmp_path,mode='mock',selector=select,catalog={},planning_mode='enumerate')
    assert session.receive(raw)==['STATE']
    assert session.receive(raw)==['POTION USE 0'];session.command_sent('POTION USE 0')
    game['potions'][0]={'id':'Potion Slot'}  # Empty slots need no potency field.
    combat['player']['block']=25
    combat['hand'][0]['native_values'].update(base_damage=25,damage=25)
    assert session.receive(raw)==['STATE']
    assert session.receive(raw)==['PLAY 1 0'];session.command_sent('PLAY 1 0')
    combat['discard_pile'].append(combat['hand'].pop())
    combat['player']['energy']=0;combat['monsters'][0]['current_hp']=15
    assert session.receive(raw)==['STATE']
    assert session.receive(raw)==['END']
    assert session.calls==1 and len(seen)==1


def test_unexpected_state_invalidates_queue_and_replans(tmp_path):
    calls = []
    def select(summary, actions):
        calls.append(actions)
        return choose_mock(summary, sorted(actions, key=lambda a: a['outcome']['enemy_hp']))
    raw = battle(); s = RunSession(tmp_path, mode='mock', selector=select,planning_mode='enumerate')
    s.receive(raw); s.receive(raw); s.command_sent('PLAY 1 0')
    c = raw['game_state']['combat_state']
    c['hand'].pop(0); c['player']['energy'] -= 1; c['monsters'][0]['current_hp'] -= 6
    c['monsters'][0]['block'] = 1
    assert s.receive(raw) == ['STATE']
    assert len(calls) == 2


def test_bash_then_strike_kill_is_locally_proven_using_vulnerability():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle(); c = raw['game_state']['combat_state']; c['monsters'][0]['current_hp'] = 15
    bash = deepcopy(c['hand'][0]); bash.update(id='Bash', uuid='bash', cost=2)
    bash['native_values'].update(base_damage=8, damage=8, cost_for_turn=2, magic_number=2, base_magic_number=2)
    bash['target_damage_previews'][0]['damage_before_block'] = 8
    c['hand'] = [bash, c['hand'][0]]
    plans = turn_plans(*prepare_journey(raw))
    assert any(p['outcome']['combat_won'] and [s.get('card_uuid') for s in p['steps']] == ['bash', 'strike-0'] for p in plans)


def test_thorns_is_included_in_plan_damage():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle()
    raw['game_state']['combat_state']['monsters'][0]['powers'] = [{'id': 'Thorns', 'name': 'Thorns', 'amount': 3}]
    plans = turn_plans(*prepare_journey(raw))
    assert plans and all(p['kind'] == 'turn_plan' for p in plans)
    assert any(p['outcome']['self_damage'] == 9 for p in plans)


def test_cost_or_intent_change_invalidates_next_planned_step():
    from slay_jev_spire.turn_planner import turn_plans, bind_plan_step
    raw = battle(); summary, actions = prepare_journey(raw)
    plan = turn_plans(summary, actions)[0]
    step = plan['steps'][0]
    changed = deepcopy(raw)
    changed['game_state']['combat_state']['hand'][0]['native_values']['cost_for_turn'] = 2
    assert bind_plan_step(step, *prepare_journey(changed)) is None
    changed = deepcopy(raw)
    changed['game_state']['combat_state']['monsters'][0]['move_adjusted_damage'] = 18
    assert bind_plan_step(step, *prepare_journey(changed)) is None


@pytest.mark.parametrize('field,value', [
    ('free_to_play_once', True), ('exhaust_on_use_once', True),
    ('retain', True), ('self_retain', True), ('purge_on_use', True),
    ('ethereal', True), ('exhausts', True), ('target_type', 'ALL_ENEMY'),
    ('has_target', False), ('can_upgrade', False),
    ('upgrade_preview', {'cost':0, 'base_damage':9, 'base_block':0, 'magic_number':0, 'upgrades':1}),
])
def test_effect_relevant_card_change_invalidates_segment(field, value):
    from slay_jev_spire.turn_planner import turn_plans, bind_plan_step
    raw = battle()
    step = turn_plans(*prepare_journey(raw))[0]['steps'][0]
    changed = deepcopy(raw)
    changed['game_state']['combat_state']['hand'][0][field] = value
    assert bind_plan_step(step, *prepare_journey(changed)) is None


def test_same_named_enemy_replacement_invalidates_segment():
    from slay_jev_spire.turn_planner import turn_plans, bind_plan_step
    raw = battle()
    raw['game_state']['combat_state']['monsters'][0]['entity_id'] = 'monster-a'
    step = turn_plans(*prepare_journey(raw))[0]['steps'][0]
    changed = deepcopy(raw)
    changed['game_state']['combat_state']['monsters'][0]['entity_id'] = 'monster-b'
    assert bind_plan_step(step, *prepare_journey(changed)) is None


def test_hand_order_change_invalidates_order_dependent_segment():
    from slay_jev_spire.turn_planner import turn_plans, bind_plan_step
    raw = battle()
    step = turn_plans(*prepare_journey(raw))[0]['steps'][0]
    raw['game_state']['combat_state']['hand'].reverse()
    assert bind_plan_step(step, *prepare_journey(raw)) is None


def test_looter_one_hp_is_presented_to_judge_as_lethal_plan(tmp_path):
    raw = battle(); c = raw['game_state']['combat_state']
    c['monsters'][0].update(id='Looter', current_hp=1, powers=[{'id': 'Thievery', 'name': 'Thievery', 'amount': 15}])
    c['player']['powers'] = [{'id': 'Plated Armor', 'name': 'Plated Armor', 'amount': 3}]
    c['player']['energy'] = 1
    for card in c['hand']: card['is_playable'] = True
    s = RunSession(tmp_path, mode='mock')
    assert s.receive(raw) == ['STATE']
    assert s.receive(raw)[0].startswith('PLAY 1 0')
    assert s.calls == 1


def test_multiple_slimes_plan_targets_survivor_and_preserves_native_indices():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle(); c = raw['game_state']['combat_state']
    c['monsters'][0].update(id='AcidSlime_S', current_hp=6)
    other = deepcopy(c['monsters'][0]); other.update(id='SpikeSlime_M', current_hp=12)
    c['monsters'].append(other)
    for card in c['hand']:
        if card.get('target_damage_previews'):
            card['target_damage_previews'].append(dict(card['target_damage_previews'][0], target_index=1))
    plans = turn_plans(*prepare_journey(raw))
    assert any(p['outcome']['combat_won'] and {s['target_index'] for s in p['steps']} == {0, 1} for p in plans)


def test_curl_up_block_prevents_false_multi_enemy_lethal():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle(); c = raw['game_state']['combat_state']
    c['monsters'][0].update(id='FuzzyLouseDefensive', current_hp=11,
                          powers=[{'id': 'Curl Up', 'name': 'Curl Up', 'amount': 4}])
    c['player']['energy'] = 2
    plans = turn_plans(*prepare_journey(raw))
    assert plans and not any(p['outcome']['combat_won'] for p in plans)
    c['player']['energy'] = 3
    assert any(p['outcome']['combat_won'] for p in turn_plans(*prepare_journey(raw)))


def test_rage_before_attacks_generates_block_in_whole_turn():
    from slay_jev_spire.turn_planner import turn_plans
    raw = battle(); c = raw['game_state']['combat_state']
    rage = deepcopy(c['hand'][-1]); rage.update(id='Rage', uuid='rage', cost=0)
    rage['native_values'].update(cost_for_turn=0, base_block=-1, block=0, magic_number=3, base_magic_number=3)
    c['hand'].append(rage)
    plans = turn_plans(*prepare_journey(raw))
    assert plans and any(p['outcome']['enemy_hp'] == 22 and p['outcome']['incoming_hp_loss'] == 3 for p in plans)


def test_only_end_turn_requires_no_model_request(tmp_path):
    raw = battle(); c = raw['game_state']['combat_state']
    c['monsters'][0]['id'] = 'FungiBeast'
    c['player']['energy'] = 0
    for card in c['hand']: card['is_playable'] = False
    s = RunSession(tmp_path, mode='mock', selector=lambda *args: pytest.fail('Only END needs no request'))
    assert s.receive(raw) == ['STATE']
    assert s.receive(raw) == ['END']
    assert s.calls == 0


def armaments_choice_nodes():
    from tests.test_policy_quality import battle as quality_battle, card
    from slay_jev_spire import rules
    from slay_jev_spire.state import prepare_native_combat
    strike = card('Strike_R', 1, damage=6,
                  upgrade_preview={'cost':1, 'base_damage':9, 'base_block':0, 'magic_number':0, 'upgrades':1})
    other = deepcopy(strike); other['uuid'] = 'other-strike'
    raw = quality_battle([strike, other, card('Defend_R',1,'SKILL',block=5,target=False),
                         card('Armaments',1,'SKILL',block=5,target=False)], enemy_hp=29)
    raw['game_state']['combat_state']['monsters'][0]['move_adjusted_damage'] = 10
    nodes = []
    for attack in ('other-strike', 'Strike_R'):
        state = rules.initial(prepare_native_combat(raw)[0]); steps = []
        for ident, target, choice in [('Defend_R',None,None), ('Armaments',None,'Strike_R'), (attack,0,None)]:
            step = next(s for s in rules.legal_steps(state) if s['card_uuid']==ident
                        and s['target_index']==target and s['selection_uuid']==choice)
            state = rules.play(state, step); steps.append(step)
        nodes.append((state, steps+[{'kind':'end'}], rules.outcome(state)))
    return raw, nodes


def test_armaments_alternatives_remain_for_model_without_dominance_ranking():
    from slay_jev_spire.turn_planner import generate_plans
    raw, _ = armaments_choice_nodes()
    plans, stats = generate_plans(*prepare_journey(raw))
    assert stats['domination_pruned'] == 0
    matching = [p for p in plans if len(p['sequence']) == 4
                and {s.get('card_id') for s in p['sequence'][:3]} == {'Defend_R', 'Armaments', 'Strike_R'}
                and any(s.get('selection_uuid') in {'Strike_R', 'other-strike'} for s in p['sequence'])]
    assert any(p['outcome']['enemy_hp'] == 20 for p in matching)
    assert any(p['outcome']['enemy_hp'] == 23 for p in matching)


@pytest.mark.parametrize('difference', ['potion', 'energy', 'max_hp', 'power', 'counter',
                                         'relic_counter', 'one_use_flag', 'draw_pile'])
def test_distinct_resources_are_not_merged_by_search(difference):
    from slay_jev_spire.turn_planner import search_key
    _, nodes = armaments_choice_nodes()
    before = nodes[1][0]
    state = deepcopy(before)
    if difference == 'potion': state['potions_used'] = [{'potion_index':0,'potion_id':'Strength Potion'}]
    elif difference == 'energy': state['energy'] += 1
    elif difference == 'max_hp': state['max_hp'] += 1
    elif difference == 'power': state['powers']['Strength'] = 1
    elif difference == 'counter': state['attacks_this_combat'] += 1
    elif difference == 'relic_counter': state['relics']['Happy Flower'] = 1
    elif difference == 'one_use_flag': state['hand'][0]['free_to_play_once'] = True
    elif difference == 'draw_pile': state['draw_pile'].append(state['hand'].pop())
    assert search_key(before) != search_key(state)
