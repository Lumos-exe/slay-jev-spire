import json
from pathlib import Path

import pytest

from slay_jev_spire.state import prepare_state, UnsupportedState


def sample():
    return json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))


def test_common_powers_and_upgraded_basics_are_preserved():
    raw = sample()
    combat = raw['game_state']['combat_state']
    combat['player']['powers'] = [
        {'id': 'Strength', 'name': '力量', 'amount': -1},
        {'id': 'Dexterity', 'name': '敏捷', 'amount': 2},
        {'id': 'Weakened', 'name': '虚弱', 'amount': 1},
        {'id': 'Frail', 'name': '脆弱', 'amount': 1},
    ]
    combat['monsters'][0]['powers'] = [
        {'id': 'Vulnerable', 'name': '易伤', 'amount': 2},
        {'id': 'Ritual', 'name': '仪式', 'amount': 3},
    ]
    for card in combat['hand']:
        card['upgrades'] = 1
    summary, actions = prepare_state(raw)
    assert summary['player']['powers'][0]['amount'] == -1
    assert summary['enemies'][0]['powers'][0]['id'] == 'Vulnerable'
    assert [c['upgrades'] for c in summary['hand']] == [1]*5
    assert '9' in summary['hand'][0]['effect']
    assert '8' in summary['hand'][2]['effect']
    assert '10' in summary['hand'][4]['effect'] and '3' in summary['hand'][4]['effect']
    assert actions[0]['command'] == 'PLAY 1 0'


@pytest.mark.parametrize('power', [
    {'id': 'Unknown', 'name': 'unknown', 'amount': 1},
    {'id': 'Vulnerable', 'name': '易伤', 'amount': -1},
    {'id': 'Strength', 'name': '力量', 'amount': True},
])
def test_unknown_or_invalid_powers_rejected(power):
    raw = sample()
    raw['game_state']['combat_state']['player']['powers'] = [power]
    with pytest.raises(UnsupportedState):
        prepare_state(raw)
