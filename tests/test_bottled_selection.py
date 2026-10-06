from copy import deepcopy
import json
from pathlib import Path

from slay_jev_spire.screens import confirm_screen


def example():
    return json.loads(Path('samples/bottled_flame_selection.json').read_text(encoding='utf-8'))


def test_actual_bottled_flame_selection_is_confirmed_without_replay():
    r=example()
    assert 'bottled relic' in confirm_screen(r['before'],r['after'],r['action'])


def test_unrelated_screen_change_or_wrong_named_card_is_not_confirmation():
    r=example()
    r['after']['game_state']['relics']=deepcopy(r['before']['game_state']['relics'])
    assert confirm_screen(r['before'],r['after'],r['action']) is None
    r=example();r['after']['game_state']['relics'][1]['native_description']='Opening hand: #yWrongCard .'
    assert confirm_screen(r['before'],r['after'],r['action']) is None
    r=example();r['after']['game_state']['relics'][1]['native_description']='#y'+r['action']['card']['name']+'+ .'
    assert confirm_screen(r['before'],r['after'],r['action']) is None


def test_native_uuid_disambiguates_duplicate_names_and_overrides_description():
    r=example();card=r['action']['card']
    r['before']['game_state']['screen_state']['cards'].append(dict(card,uuid='duplicate'))
    assert confirm_screen(r['before'],r['after'],r['action']) is None
    r['after']['game_state']['relics'][1]['bottled_card_uuid']=card['uuid']
    assert 'UUID' in confirm_screen(r['before'],r['after'],r['action'])
    r['after']['game_state']['relics'][1]['bottled_card_uuid']='wrong'
    assert confirm_screen(r['before'],r['after'],r['action']) is None
