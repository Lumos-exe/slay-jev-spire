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
    s = RunSession(tmp_path, mode='mock', selector=select)
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


def test_unexpected_state_invalidates_queue_and_replans(tmp_path):
    calls = []
    def select(summary, actions):
        calls.append(actions)
        return choose_mock(summary, sorted(actions, key=lambda a: a['outcome']['enemy_hp']))
    raw = battle(); s = RunSession(tmp_path, mode='mock', selector=select)
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
