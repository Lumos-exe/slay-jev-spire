import copy
import json
from pathlib import Path

from slay_jev_spire.selectors import choose_mock, SelectionError


def sample():
    r=json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    r['game_state']['combat_state']['monsters'][0]['intent']='ATTACK'
    return r


def controller(tmp_path, **kwargs):
    from slay_jev_spire.session import CombatSession
    return CombatSession(tmp_path, mode='mock', selector=choose_mock, **kwargs)


def test_waits_for_action_confirmation_and_stops_at_rewards(tmp_path):
    s=controller(tmp_path)
    r=sample()
    assert s.receive(r)==['STATE']
    assert s.receive(r)==['STATE']
    assert s.receive(r)==['PLAY 1 0']
    assert s.receive(r)==['STATE']  # 重复旧状态不能再次出牌
    after=copy.deepcopy(r)
    c=after['game_state']['combat_state']
    played=c['hand'].pop(0)
    c['discard_pile'].append(played)
    c['player']['energy']-=1
    assert s.receive(after)==['STATE']
    assert s.receive(after)==['PLAY 1 0']
    rewards=copy.deepcopy(after)
    rewards['game_state']['room_phase']='COMPLETE'
    rewards['game_state']['screen_type']='COMBAT_REWARD'
    assert s.receive(rewards)==[]
    assert s.stopped and s.reason=='battle_finished'
    assert s.receive(sample())==[]
    assert s.calls==2 and s.actions==2


def test_call_limit_and_pause_before_send(tmp_path):
    s=controller(tmp_path,max_decisions=1)
    r=sample()
    s.receive(r);s.receive(r);s.receive(r)
    after=copy.deepcopy(r)
    after['game_state']['combat_state']['hand'].pop(0)
    assert s.receive(after)==[]
    assert s.reason=='decision_limit'
    other=tmp_path/'other'
    s=controller(other)
    s.receive(r);s.receive(r)
    (other/'pause.flag').write_text('pause')
    assert s.receive(r)==[]
    assert s.actions==0 and s.reason=='paused'


def test_changed_state_and_api_error_stop_without_action(tmp_path):
    s=controller(tmp_path)
    r=sample()
    s.receive(r);s.receive(r)
    changed=copy.deepcopy(r)
    changed['game_state']['combat_state']['player']['energy']=0
    assert s.receive(changed)==[]
    assert s.reason=='state_changed' and s.actions==0
    def fail(summary,actions):
        raise SelectionError('test error')
    from slay_jev_spire.session import CombatSession
    s=CombatSession(tmp_path/'failure',mode='mock',selector=fail)
    s.receive(r)
    assert s.receive(r)==[]
    assert s.reason=='selection_error'


def test_unsupported_state_and_different_battle_stop(tmp_path):
    r=sample()
    s=controller(tmp_path)
    s.receive(r)
    bad=copy.deepcopy(r)
    bad['game_state']['combat_state']['hand'][0]['id']='Unknown'
    assert s.receive(bad)==[]
    assert s.reason=='unsupported_state'
    s=controller(tmp_path/'other')
    s.receive(r)
    bad=copy.deepcopy(r)
    bad['game_state']['floor']+=1
    assert s.receive(bad)==[]
    assert s.reason=='battle_changed'


def test_end_waits_for_next_turn_and_idle_pause_is_checked(tmp_path):
    s=controller(tmp_path)
    r=sample()
    r['available_commands']=['end']
    s.receive(r);s.receive(r)
    assert s.receive(r)==['END']
    settling=copy.deepcopy(r)
    settling['game_state']['action_phase']='EXECUTING_ACTIONS'
    assert s.receive(settling)==[]
    assert s.calls==1
    after=copy.deepcopy(r)
    after['game_state']['combat_state']['turn']+=1
    assert s.receive(after)==['STATE']
    (tmp_path/'pause.flag').write_text('pause')
    s.tick()
    assert s.reason=='paused' and s.calls==2 and s.actions==1
