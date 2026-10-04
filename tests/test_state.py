import copy
import json
from pathlib import Path

import pytest

from slay_jev_spire.state import UnsupportedState, prepare_state


@pytest.fixture
def raw():
    return json.loads((Path(__file__).resolve().parents[1] / 'samples/communication_mod_combat.json').read_text(encoding='utf-8'))


def test_official_sample_commands_and_unknown_damage(raw):
    summary, actions = prepare_state(raw)
    assert [a['command'] for a in actions] == ['PLAY 1 0', 'PLAY 2 0', 'PLAY 3', 'PLAY 4', 'PLAY 5 0', 'END']
    assert summary['enemies'][0]['move_adjusted_damage'] is None
    assert summary['enemies'][0]['intent'] == 'DEBUG'
    assert summary['hand'][0]['hand_index'] == 0
    assert summary['hand'][0]['card_uuid'] != summary['hand'][1]['card_uuid']
    assert set(summary) == {'turn', 'player', 'hand', 'enemies'}


def test_filtered_cards_and_targets_keep_original_indices(raw):
    combat = raw['game_state']['combat_state']
    combat['hand'][1]['is_playable'] = False
    combat['hand'][3]['cost'] = 9
    combat['monsters'] = [copy.deepcopy(combat['monsters'][0]) for _ in range(5)]
    combat['monsters'][1]['current_hp'] = 0
    combat['monsters'][3]['is_gone'] = True
    combat['monsters'][4]['half_dead'] = True
    _, actions = prepare_state(raw)
    assert [a['command'] for a in actions] == ['PLAY 1 0', 'PLAY 1 2', 'PLAY 3', 'PLAY 5 0', 'PLAY 5 2', 'END']
    assert actions[1]['id'] == 'play_1_2'
    assert actions[1]['hand_index'] == 0
    assert actions[1]['target_index'] == 2
    assert actions[2]['target_index'] is None
    assert actions[3]['hand_index'] == 4
    assert actions[3]['card_uuid'] == combat['hand'][4]['uuid']


def test_available_commands_gate_candidates(raw):
    raw['available_commands'] = ['end']
    assert [a['command'] for a in prepare_state(raw)[1]] == ['END']
    raw['available_commands'] = ['play']
    assert all(a['command'] != 'END' for a in prepare_state(raw)[1])
    raw['available_commands'] = []
    with pytest.raises(UnsupportedState):
        prepare_state(raw)


@pytest.mark.parametrize(('path', 'value'), [
    (('ready_for_command',), False),
    (('in_game',), False),
    (('game_state', 'class'), 'THE_SILENT'),
    (('game_state', 'room_phase'), 'COMPLETE'),
    (('game_state', 'action_phase'), 'EXECUTING_ACTIONS'),
    (('game_state', 'screen_type'), 'HAND_SELECT'),
    (('game_state', 'is_screen_up'), True),
    (('game_state', 'combat_state', 'player', 'powers'), [{'id': 'Unsupported'}]),
    (('game_state', 'combat_state', 'monsters', 0, 'powers'), [{'id': 'Curl Up'}]),
    (('game_state', 'combat_state', 'hand', 0, 'id'), 'OtherCard'),
    (('game_state', 'combat_state', 'hand', 0, 'upgrades'), 2),
    (('game_state', 'combat_state', 'hand', 0, 'has_target'), False),
    (('game_state', 'combat_state', 'hand', 0, 'cost'), -1),
    (('game_state', 'relics', 0, 'id'), 'Snecko Eye'),
    (('game_state', 'combat_state', 'limbo'), [{}]),
])
def test_unsupported_states_are_rejected(raw, path, value):
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(UnsupportedState):
        prepare_state(raw)


def test_malformed_state_is_friendly():
    with pytest.raises(UnsupportedState):
        prepare_state({})


def test_negative_damage_is_unknown_not_guessed_from_base_damage(raw):
    monster = raw['game_state']['combat_state']['monsters'][0]
    monster['move_adjusted_damage'] = -2
    monster['move_base_damage'] = 999
    assert prepare_state(raw)[0]['enemies'][0]['move_adjusted_damage'] is None
