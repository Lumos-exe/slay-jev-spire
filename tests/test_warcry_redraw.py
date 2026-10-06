from copy import deepcopy
import json
from pathlib import Path

from slay_jev_spire.screens import confirm_screen


def example():
    return json.loads(Path('samples/warcry_redraw_selection.json').read_text(encoding='utf-8'))


def test_actual_warcry_dark_embrace_selection_redraw_is_confirmed():
    r=example()
    assert 'selected UUID redrawn' in confirm_screen(r['before'],r['after'],r['action'])


def test_generic_closed_screen_does_not_count_as_warcry_resolution():
    r=example();r['after']['game_state']['combat_state']['exhaust_pile']=[]
    assert confirm_screen(r['before'],r['after'],r['action']) is None
    r=example();r['before']['game_state']['combat_state']['player']['powers']=[]
    assert confirm_screen(r['before'],r['after'],r['action']) is None


def test_wrong_card_redrawn_does_not_confirm_the_requested_uuid():
    r=example();hand=r['after']['game_state']['combat_state']['hand']
    hand[0],hand[-1]=hand[-1],hand[0]
    assert confirm_screen(r['before'],r['after'],r['action']) is None


def test_old_warcry_exhaust_is_not_evidence_of_a_new_selection():
    r=example();r['before']['game_state']['combat_state']['exhaust_pile']=deepcopy(r['after']['game_state']['combat_state']['exhaust_pile'])
    assert confirm_screen(r['before'],r['after'],r['action']) is None
