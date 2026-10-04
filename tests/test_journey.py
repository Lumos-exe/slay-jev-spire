import copy
import json
from pathlib import Path
import pytest
from slay_jev_spire.state import UnsupportedState


def reward():
    return json.loads(Path('samples/communication_mod_rewards.json').read_text(encoding='utf-8'))


def test_reward_indices_and_full_potions():
    from slay_jev_spire.journey import prepare_journey
    r=reward(); r['game_state']['potions']=[{'id':'Occupied'}]*3
    summary, actions=prepare_journey(r)
    assert [a['command'] for a in actions]==['CHOOSE 0','CHOOSE 2','PROCEED']
    assert summary['deck']==r['game_state']['deck']
    assert summary['map']==r['game_state']['map']


def test_cards_skip_and_bowl_are_native_indices():
    from slay_jev_spire.journey import prepare_journey
    r=reward(); g=r['game_state']; g['screen_type']='CARD_REWARD'
    g['choice_list']=['unknown card','bowl']; g['screen_state']={'cards':[{'id':'Unknown','name':'unknown card'}], 'bowl_available':True,'skip_available':True}
    r['available_commands']=['choose','skip','state']
    _,a=prepare_journey(r)
    assert [x['command'] for x in a]==['CHOOSE 0','CHOOSE 1','SKIP']
    r['available_commands'].remove('skip')
    assert [x['command'] for x in prepare_journey(r)[1]]==['CHOOSE 0','CHOOSE 1']


def test_map_alignment_and_unsupported_screen():
    from slay_jev_spire.journey import prepare_journey
    r=reward(); g=r['game_state']; g['screen_type']='MAP'; g['choice_list']=['x=2','x=5']
    g['screen_state']={'next_nodes':[{'x':2,'y':1,'symbol':'M'},{'x':5,'y':1,'symbol':'?'}]}
    assert [a['command'] for a in prepare_journey(r)[1]]==['CHOOSE 0','CHOOSE 1']
    g['screen_state']['next_nodes'].reverse()
    with pytest.raises(UnsupportedState): prepare_journey(r)
    g['screen_type']='EVENT'
    with pytest.raises(UnsupportedState): prepare_journey(r)

def test_misaligned_reward_metadata_is_rejected():
    from slay_jev_spire.journey import prepare_journey
    r=reward(); r['game_state']['choice_list'].reverse()
    with pytest.raises(UnsupportedState): prepare_journey(r)
