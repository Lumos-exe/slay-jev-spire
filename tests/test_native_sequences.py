from copy import deepcopy
from itertools import permutations
import json

from tools.audit_strategy import fixture, card
from slay_jev_spire.native_sequences import generate_plans, bind_plan_step
from slay_jev_spire.planning_config import SearchConfig
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock, model_payload


def test_every_ordered_three_energy_sequence_is_present_with_both_finish_choices():
    raw = fixture('five', [card('Unregistered' + str(i), 1) for i in range(5)],
                  relics=[{'id': 'UnregisteredRelic'}], powers=[('UnregisteredPower', 2)])['raw']
    summary, actions = prepare_native_combat(raw)
    plans, stats = generate_plans(summary, actions)
    expected = {p for n in range(4) for p in permutations([c['uuid'] for c in summary['hand']], n)}
    endings = {tuple(s['card_uuid'] for s in p['sequence'][:-1])
               for p in plans if p['sequence'][-1]['kind'] == 'end'}
    observing = {tuple(s['card_uuid'] for s in p['sequence'])
                 for p in plans if p['checkpoint']}
    assert endings == expected and observing == expected - {()}
    assert len(plans) == 171 and stats['complete_enumeration']
    assert stats['multi_action_candidates'] == 160
    assert all('outcome' not in p for p in plans)
    _, criteria, _ = model_payload(dict(summary, combat_choice_mode=stats['policy']), plans)
    assert all('simple_result' not in c for c in criteria.values())


def test_budget_retains_sequences_and_every_native_start_in_same_pool():
    raw = fixture('limited', [card('Strike_R', 1) for _ in range(5)])['raw']
    summary, actions = prepare_native_combat(raw)
    plans, stats = generate_plans(summary, actions, SearchConfig(max_nodes=8))
    assert stats['truncated'] == ['node_budget'] and not stats['fallback_required']
    assert stats['multi_action_candidates'] > 0
    assert {p['sequence'][0].get('card_uuid') for p in plans} == {a.get('card_uuid') for a in actions}


def test_all_potion_orders_compete_with_complete_card_plans():
    raw = fixture('potions', [card('UnknownAttack', 1)])['raw']
    raw['available_commands'].append('potion')
    raw['game_state']['potions'] = [dict(id='Potion'+str(i), name='Potion'+str(i),
        potency=3, can_use=True, can_discard=True, requires_target=False) for i in range(3)]
    plans, stats = generate_plans(*prepare_native_combat(raw))
    sequences = {tuple(s.get('card_id', s.get('potion_id')) for s in p['sequence'][:-1])
                 for p in plans if p['sequence'][-1]['kind'] == 'end'}
    expected = {p for n in range(5) for p in permutations(['UnknownAttack','Potion0','Potion1','Potion2'], n)}
    assert sequences == expected and stats['complete_enumeration']


def test_new_observations_stop_queue_and_regenerate_sequences(tmp_path):
    raw = fixture('draw', [card('UnknownDraw', 1), card('Strike_R', 1), card('Defend_R', 1, 'SKILL')])['raw']
    seen = []
    def select(summary, plans):
        seen.append(plans)
        assert all(p['kind'] == 'turn_plan' for p in plans)
        assert any(len(p['sequence']) > 2 for p in plans)
        chosen = next(p for p in plans if len(p['sequence']) == 4
                      and p['sequence'][0].get('card_id') == ('UnknownDraw' if len(seen) == 1 else 'Strike_R'))
        return choose_mock(summary, [chosen])
    session = RunSession(tmp_path, mode='mock', selector=select)
    assert session.receive(raw) == ['STATE']
    command = session.receive(raw)[0]; session.command_sent(command)
    after = deepcopy(raw); combat = after['game_state']['combat_state']
    combat['discard_pile'].append(combat['hand'].pop(0))
    drawn = card('AnotherNewCard', 0); drawn['uuid'] = 'drawn'
    combat['hand'].append(drawn); combat['player']['energy'] = 2
    assert session.receive(after) == ['STATE']
    assert len(seen) == 2 and not session.stopped
    rows = [json.loads(line) for line in (tmp_path/'runs.jsonl').read_text().splitlines()]
    assert any(r['status'] == 'plan_invalidated' for r in rows)
    assert not any(r.get('source') == 'native_action_fallback' for r in rows)


def test_ordinary_sequence_reuses_model_choice_and_end_has_resource_guard(tmp_path):
    raw = fixture('combo', [card('UnregisteredA', 1), card('UnregisteredB', 1)])['raw']
    calls = []
    def select(summary, plans):
        calls.append(1)
        return choose_mock(summary, [next(p for p in plans if len(p['sequence']) == 3 and p['sequence'][-1]['kind'] == 'end'
                                         and p['sequence'][0].get('card_id')=='UnregisteredA')])
    session = RunSession(tmp_path, mode='mock', selector=select)
    assert session.receive(raw) == ['STATE']
    command = session.receive(raw)[0]; session.command_sent(command)
    after = deepcopy(raw); combat = after['game_state']['combat_state']
    combat['discard_pile'].append(combat['hand'].pop(0)); combat['player']['energy'] = 2
    assert session.receive(after) == ['STATE'] and len(calls) == 1
    command = session.receive(after)[0]; session.command_sent(command)
    combat['discard_pile'].append(combat['hand'].pop(0)); combat['player']['energy'] = 1
    assert session.receive(after) == ['STATE'] and len(calls) == 1
    assert session.receive(after) == ['END']


def test_cost_target_intent_and_turn_changes_invalidate_even_end():
    raw = fixture('guard', [card('Strike_R', 1)])['raw']
    summary, actions = prepare_native_combat(raw)
    plans, _ = generate_plans(summary, actions)
    step = next(p for p in plans if p['sequence'] == [{'kind': 'end'}])['steps'][0]
    assert bind_plan_step(step, summary, actions)
    for mutate in (lambda s: s['hand'][0]['native_values'].update(cost_for_turn=0),
                   lambda s: s['player'].update(energy=4), lambda s: s.update(turn=2),
                   lambda s: s['enemies'][0].update(move_id=42)):
        changed = deepcopy(summary); mutate(changed)
        assert bind_plan_step(step, changed, actions) is None


def test_grouping_compares_complete_candidates_before_choosing_a_branch(monkeypatch):
    from slay_jev_spire import selectors
    from slay_jev_spire.jev_provider import capture_http, _evidence
    calls = []
    def provider(summary, actions):
        assert _evidence.get()[1] == 'sequence-group-test'
        calls.append([a['id'] for a in actions])
        # The future combo, not its first card, wins this independent oracle.
        chosen = next((a for a in actions if a['id']=='combo'), actions[-1])
        return dict(action=chosen, probabilities={a['id']:float(a==chosen) for a in actions},
                    usage={'input_tokens':1,'output_tokens':1}, model_requests=1)
    monkeypatch.setattr(selectors, '_request_with_transient_retry', provider)
    actions = [dict(id='end', sequence=[{'kind':'end'}]),
        dict(id='weak', sequence=[{'kind':'play','card_uuid':'a'},{'kind':'end'}]),
        dict(id='combo', sequence=[{'kind':'play','card_uuid':'a'},{'kind':'play','card_uuid':'b'},{'kind':'end'}]),
        dict(id='strong', sequence=[{'kind':'play','card_uuid':'b'},{'kind':'end'}])]
    with capture_http(None, 'sequence-group-test'):
        result = selectors._choose_sequence_groups({}, actions)
    assert result['action']['id'] == 'combo'
    assert calls[0] == ['weak','combo']
    assert calls[-1] == ['end','combo','strong']
    assert set(result['context_comparison']['all_candidates']) == {a['id'] for a in actions}
    assert result['model_requests'] == 2


def test_native_free_play_change_invalidates_end_without_a_power_name_rule():
    raw=fixture('new-capability',[card('UnknownPowerCard',3,'POWER'),card('OtherCard',1)])['raw']
    summary,actions=prepare_native_combat(raw)
    plans,_=generate_plans(summary,actions)
    plan=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['UnknownPowerCard',None])
    after=deepcopy(summary)
    after['hand']=after['hand'][1:];after['player']['energy']=0
    # Native card costs need not change when a new power grants free plays.
    # END must be reconsidered even though hand/energy match the old envelope.
    after['player']['powers'].append({'id':'UnknownFreePlayPower','amount':1})
    after['hand'][0]['native_values']['free_to_play']=True
    assert bind_plan_step(plan['steps'][-1],after,[{'kind':'end','id':'end'}]) is None
    after['player']['powers']=[]
    after['hand'][0]['native_values']['free_to_play']=False
    after['relics'].append({'id':'UnknownNewRelic'})
    assert bind_plan_step(plan['steps'][-1],after,[{'kind':'end','id':'end'}]) is None


def test_native_free_play_is_used_without_interpreting_power_names():
    raw=fixture('free',[card('NewAttack',2),card('AnotherAttack',1)],energy=0)['raw']
    for c in raw['game_state']['combat_state']['hand']:
        c['is_playable']=True;c['native_values']['free_to_play']=True
    plans,_=generate_plans(*prepare_native_combat(raw))
    assert any(len(p['sequence'])==3 for p in plans)


def test_known_buff_does_not_split_an_otherwise_valid_plan():
    raw=fixture('buff',[card('Inflame',1,'POWER',magic=2),card('Strike_R',1,damage=6)])['raw']
    summary,actions=prepare_native_combat(raw)
    plans,_=generate_plans(summary,actions)
    plan=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['Inflame','Strike_R',None])
    after=deepcopy(raw);c=after['game_state']['combat_state']
    c['hand'].pop(0);c['player']['energy']=2
    c['player']['powers']=[{'id':'Strength','name':'Strength','amount':2}]
    summary,actions=prepare_native_combat(after)
    assert bind_plan_step(plan['steps'][1],summary,actions)['card_uuid']==c['hand'][0]['uuid']
