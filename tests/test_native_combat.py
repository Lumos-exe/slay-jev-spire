import copy

import pytest
from slay_jev_spire.state import prepare_native_combat, potion_candidates
from slay_jev_spire.state import UnsupportedState


@pytest.fixture
def raw():
    card = {'id': 'Strike_R', 'name': 'Strike', 'uuid': 'strike', 'cost': 1,
            'type': 'ATTACK', 'rarity': 'BASIC', 'upgrades': 0, 'is_playable': True,
            'has_target': True, 'exhausts': False, 'ethereal': False}
    hand = [dict(card, id='Feel No Pain', name='Feel No Pain', uuid='feel', type='POWER', has_target=False, upgrades=3, exhausts=True, ethereal=True),
            dict(card, id='Whirlwind', uuid='whirl', cost=-1),
            dict(card, id='Free', uuid='free', cost=99),
            dict(card, id='Dazed', uuid='dazed', cost=-2, is_playable=False)]
    monster = {'name': 'Cultist', 'current_hp': 36, 'max_hp': 53, 'block': 0,
               'is_gone': False, 'half_dead': False, 'intent': 'ATTACK',
               'move_adjusted_damage': 6, 'move_hits': 1, 'powers': []}
    return {'in_game': True, 'ready_for_command': True, 'available_commands': ['play', 'end'],
            'game_state': {'class': 'IRONCLAD', 'room_phase': 'COMBAT',
                           'action_phase': 'WAITING_ON_USER', 'screen_type': 'NONE',
                           'is_screen_up': False, 'relics': [], 'potions': [],
                           'combat_state': {'turn': 2, 'hand': hand, 'limbo': [],
                                            'monsters': [monster], 'draw_pile': [dict(card, cost=-2, is_playable=False)],
                                            'discard_pile': [], 'exhaust_pile': [],
                                            'player': {'current_hp': 79, 'max_hp': 80, 'block': 0,
                                                       'energy': 3, 'powers': [], 'orbs': []}}}}


def test_native_cards_and_piles_preserve_metadata(raw):
    original = copy.deepcopy(raw)
    summary, actions = prepare_native_combat(raw)
    assert [a['command'] for a in actions] == ['PLAY 1', 'PLAY 2 0', 'PLAY 3 0', 'END']
    assert summary['hand'][0]['effect'] == 'unknown'
    assert summary['hand'][0]['upgrades'] == 3
    assert summary['hand'][0]['exhausts'] is True
    assert summary['draw_order_known'] is False
    assert any(card['cost'] == -2 for card in summary['draw_pile'])
    assert raw == original


def test_target_indices_powers_orbs_and_relics(raw):
    combat = raw['game_state']['combat_state']
    combat['player']['powers'] = [{'id': 'Anything', 'name': 'Anything', 'amount': -4}]
    combat['player']['orbs'] = [{'id': 'Dark', 'name': 'Dark', 'evoke_amount': 20}]
    raw['game_state']['relics'] = [{'id': 'Snecko Eye', 'counter': -1}]
    combat['monsters'] = [dict(combat['monsters'][0], is_gone=True), dict(combat['monsters'][0])]
    summary, actions = prepare_native_combat(raw)
    assert actions[1]['command'] == 'PLAY 2 1'
    assert summary['player']['powers'][0]['amount'] == -4
    assert summary['player']['orbs'][0]['evoke_amount'] == 20


@pytest.mark.parametrize('field,value', [('is_playable', 1), ('has_target', 'false'), ('cost', True), ('upgrades', -1), ('exhausts', None)])
def test_invalid_card_fields_are_safe(raw, field, value):
    raw['game_state']['combat_state']['hand'][0][field] = value
    with pytest.raises(UnsupportedState):
        prepare_native_combat(raw)


def test_potion_slots_and_flags(raw):
    raw['available_commands'].append('potion')
    raw['game_state']['potions'] = [
        {'id': 'Potion Slot'},
        {'id': 'Fire Potion', 'name': 'Fire Potion', 'can_use': True, 'can_discard': True, 'requires_target': True},
        {'id': 'FairyPotion', 'name': 'Fairy', 'can_use': False, 'can_discard': False, 'requires_target': False}]
    actions = potion_candidates(raw)
    assert [a['command'] for a in actions] == ['POTION USE 1 0', 'POTION DISCARD 1']
    assert actions[0]['kind'] == 'potion'
    assert actions[0]['potion_id'] == 'Fire Potion'
    assert actions[0]['subaction'] == 'use'
    assert actions[0]['potion']['name']=='Fire Potion'
    actions[0]['potion']['name']='changed copy'
    assert raw['game_state']['potions'][1]['name']=='Fire Potion'
    raw['game_state']['potions'][1]['can_use'] = 'true'
    with pytest.raises(UnsupportedState):
        potion_candidates(raw)


@pytest.mark.parametrize('field,value', [('room_phase', 'COMPLETE'), ('action_phase', 'EXECUTING_ACTIONS'), ('screen_type', 'GRID'), ('is_screen_up', True)])
def test_transitions_do_not_offer_combat_commands(raw, field, value):
    raw['game_state'][field] = value
    with pytest.raises(UnsupportedState):
        prepare_native_combat(raw)


def test_dead_targets_and_native_unplayable(raw):
    combat = raw['game_state']['combat_state']
    combat['monsters'][0]['is_dead'] = True
    combat['hand'][0]['is_playable'] = False
    assert [a['command'] for a in prepare_native_combat(raw)[1]] == ['END']


def test_native_playable_status_with_relic_override(raw):
    raw['game_state']['combat_state']['hand'][3]['is_playable'] = True
    raw['game_state']['combat_state']['hand'][3]['has_target'] = False
    assert 'PLAY 4' in [a['command'] for a in prepare_native_combat(raw)[1]]


@pytest.mark.parametrize('section,value', [('orbs', [{'id': 'Dark', 'evoke_amount': 'secret'}]), ('powers', [{'id': 'Any', 'name': 'Any', 'amount': True}])])
def test_invalid_general_player_metadata(raw, section, value):
    raw['game_state']['combat_state']['player'][section] = value
    with pytest.raises(UnsupportedState):
        prepare_native_combat(raw)
