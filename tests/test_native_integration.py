import copy
import json
from pathlib import Path

from slay_jev_spire.screens import prepare_journey
from slay_jev_spire.session import RunSession, confirmation


def combat():
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['intent'] = 'ATTACK'
    card = raw['game_state']['combat_state']['hand'][0]
    card.update(id='Feel No Pain', name='无惧疼痛', has_target=False, type='POWER')
    return raw


def test_run_accepts_native_power_card_instead_of_strict_whitelist(tmp_path):
    raw = combat()
    summary, candidates = prepare_journey(raw)
    assert summary['hand'][0]['id'] == 'Feel No Pain'
    assert any(a['command'] == 'PLAY 1' for a in candidates)
    from slay_jev_spire.selectors import choose_mock
    def choose_power(summary, plans):
        selected = next(p for p in plans if p['sequence'][0].get('card_id') == 'Feel No Pain')
        return choose_mock(summary, [selected])
    session = RunSession(tmp_path, mode='mock', selector=choose_power)
    assert session.receive(raw) == ['STATE']
    assert session.receive(raw) == ['PLAY 1']


def test_selection_during_executing_combat_is_not_ignored(tmp_path):
    raw = combat()
    game = raw['game_state']
    game['screen_type'] = 'HAND_SELECT'
    game['action_phase'] = 'EXECUTING_ACTIONS'
    game['is_screen_up'] = True
    card = game['combat_state']['hand'][0]
    game['choice_list'] = [card['name'].lower()]
    game['screen_state'] = {'hand': [card], 'selected': [], 'max_cards': 1}
    raw['available_commands'] = ['choose', 'state']
    session = RunSession(tmp_path, mode='mock')
    assert session.receive(raw) == ['STATE']


def test_potion_confirmation_needs_original_slot_consumed():
    raw = combat()
    raw['game_state']['potions'] = [{'id': 'Fire Potion'}]
    action = {'command': 'POTION USE 0 0', 'kind': 'potion', 'potion_index': 0,
              'potion_id': 'Fire Potion', 'subaction': 'use'}
    after = copy.deepcopy(raw)
    after['game_state']['gold'] = 100
    assert confirmation(raw, after, action) is None
    after['game_state']['potions'][0] = {'id': 'Potion Slot'}
    assert confirmation(raw, after, action) == 'potion_slot_consumed'


def test_loading_between_acts_does_not_end_run(tmp_path):
    session = RunSession(tmp_path, mode='mock')
    raw = combat()
    session.receive(raw)
    # 请求前的稳定性检查阶段也可能遇到暂时不在地牢的加载消息。
    assert session.receive({'in_game': False, 'ready_for_command': False,
                            'available_commands': ['state']}) == []
    assert not session.stopped
