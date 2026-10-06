from copy import deepcopy
import pytest

from tests.test_journey import reward
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock
from slay_jev_spire.session import gameplay_state


def test_reward_choices_are_model_decisions_and_card_inspection_is_a_workflow_step(tmp_path):
    calls = []
    def selector(summary, candidates):
        calls.append(candidates)
        return choose_mock(summary, sorted(candidates, key=lambda a: a['command'] != 'CHOOSE 0'))
    raw = reward()
    raw['game_state']['potions'] = [{'id': 'Potion Slot'}] * 3
    s = RunSession(tmp_path, mode='mock', selector=selector)
    for command in ('CHOOSE 0', 'CHOOSE 0'):
        assert s.receive(raw) == ['STATE']
        assert s.receive(raw) == [command]
        s.command_sent(command)
        raw = deepcopy(raw)
        g = raw['game_state']
        item = g['screen_state']['rewards'].pop(0)
        g['choice_list'].pop(0)
        if item['reward_type'] == 'GOLD':
            g['gold'] += item['gold']
        else:
            g['potions'][0] = item['potion']
    assert s.receive(raw) == ['STATE']
    assert s.receive(raw) == ['CHOOSE 0']  # Inspect the remaining card reward first.
    assert s.calls == 2 and len(calls)==2


@pytest.mark.parametrize('monster_id', ['AcidSlime_S', 'FungiBeast'])
def test_dead_monster_power_cleanup_is_ignored_but_living_and_revivable_are_not(monster_id):
    raw = {'game_state': {'combat_state': {'monsters': [
        {'id': monster_id, 'current_hp': 0, 'is_gone': True, 'half_dead': False,
         'powers': [{'id': 'Vulnerable', 'amount': 2}]}]}}}
    changed = deepcopy(raw)
    changed['game_state']['combat_state']['monsters'][0]['powers'] = []
    assert gameplay_state(raw) == gameplay_state(changed)
    for field, value in [('current_hp', 1), ('half_dead', True), ('is_gone', False)]:
        before, after = deepcopy(raw), deepcopy(changed)
        before['game_state']['combat_state']['monsters'][0][field] = value
        after['game_state']['combat_state']['monsters'][0][field] = value
        assert gameplay_state(before) != gameplay_state(after)
    before, after = deepcopy(raw), deepcopy(changed)
    before['game_state']['combat_state']['player'] = {'powers': []}
    after['game_state']['combat_state']['player'] = {'powers': [{'id': 'Vulnerable', 'amount': 2}]}
    assert gameplay_state(before) != gameplay_state(after)


def test_full_slots_and_sozu_do_not_force_unclaimable_potion(tmp_path):
    for name, potions, relics in [('full', [{'id': 'Occupied'}] * 3, []),
                                  ('sozu', [{'id': 'Potion Slot'}] * 3, [{'id': 'Sozu'}])]:
        raw = reward()
        g = raw['game_state']
        g['screen_state']['rewards'].pop(0); g['choice_list'].pop(0)
        g['screen_state']['rewards'] = g['screen_state']['rewards'][:1]
        g['choice_list'] = g['choice_list'][:1]
        g['potions'], g['relics'] = potions, relics
        s = RunSession(tmp_path / name, mode='mock', selector=lambda summary, actions:
                       choose_mock(summary, sorted(actions, key=lambda a: a['command'] != 'PROCEED')))
        assert s.receive(raw) == ['STATE']
        assert s.receive(raw) == ['PROCEED']
        assert s.calls == 1


def test_free_relic_is_not_forced_over_the_models_choice(tmp_path):
    raw = reward();g=raw['game_state']
    g['screen_state']['rewards']=[{'reward_type':'RELIC','relic':{'id':'Happy Flower','name':'Happy Flower','counter':-1}}]
    g['choice_list']=['relic']
    s=RunSession(tmp_path,mode='mock',selector=lambda summary,actions:choose_mock(summary,[next(a for a in actions if a['command']=='PROCEED')]))
    assert s.receive(raw)==['STATE'] and s.receive(raw)==['PROCEED']
    assert s.calls==1


def test_relic_pickup_can_open_a_selection_screen():
    from slay_jev_spire.session import confirmation
    raw=reward();raw['game_state']['relics']=[]
    action={'kind':'reward','command':'CHOOSE 0','choice_index':0,'reward':{'reward_type':'RELIC','relic':{'id':'Bottled Flame'}}}
    after=deepcopy(raw);after['game_state'].update(screen_type='GRID',screen_state={},relics=[{'id':'Bottled Flame'}])
    assert confirmation(raw,after,action)=='relic_reward_collected'
    after['game_state']['relics']=[]
    assert confirmation(raw,after,action) is None
