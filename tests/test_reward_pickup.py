from copy import deepcopy
import pytest

from tests.test_journey import reward
from slay_jev_spire.session import RunSession
from slay_jev_spire.selectors import choose_mock
from slay_jev_spire.session import gameplay_state


def test_free_rewards_collected_before_leaving_without_model_requests(tmp_path):
    calls = []
    def selector(summary, candidates):
        calls.append(candidates)
        return choose_mock(summary, sorted(candidates, key=lambda a: a['command'] != 'PROCEED'))
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
    assert s.receive(raw) == ['PROCEED']
    assert s.calls == 1 and len(calls) == 1


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
        g['potions'], g['relics'] = potions, relics
        s = RunSession(tmp_path / name, mode='mock', selector=lambda summary, actions:
                       choose_mock(summary, sorted(actions, key=lambda a: a['command'] != 'PROCEED')))
        assert s.receive(raw) == ['STATE']
        assert s.receive(raw) == ['PROCEED']
        assert s.calls == 1
