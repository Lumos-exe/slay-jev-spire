import json
from pathlib import Path

import pytest

from slay_jev_spire.state import UnsupportedState, prepare_state


def test_curl_up_is_visible_in_summary_and_target_description():
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['powers'] = [
        {'id': 'Curl Up', 'name': '蜷身', 'amount': 5}
    ]
    summary, actions = prepare_state(raw)
    assert summary['enemies'][0]['powers'] == [{'id': 'Curl Up', 'name': '蜷身', 'amount': 5}]
    assert '5' in actions[0]['description'] and '蜷身' in actions[0]['description']


@pytest.mark.parametrize('power', [
    {'id': 'Unsupported', 'name': 'unknown', 'amount': 2},
    {'id': 'Curl Up', 'name': '蜷身', 'amount': -1},
    {'id': 'Curl Up', 'name': '蜷身', 'amount': True},
])
def test_other_or_malformed_powers_still_rejected(power):
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['powers'] = [power]
    with pytest.raises(UnsupportedState):
        prepare_state(raw)
