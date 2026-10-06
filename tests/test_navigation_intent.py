from copy import deepcopy
import json
from pathlib import Path

from slay_jev_spire.navigation_intent import NavigationIntent
from slay_jev_spire.screens import prepare_journey
from slay_jev_spire.session import RunSession, describe_candidates


def example():
    return json.loads(Path('samples/shop_exit_navigation.json').read_text(encoding='utf-8'))


def test_real_shop_exit_has_one_guarded_navigation_continuation():
    row=example();raw=row['after'];actions=prepare_journey(raw)[1]
    intent=NavigationIntent.after_action(row['decision']['action'],row['before'],raw,row['step_id'])
    assert intent and intent.resolve(raw,actions)['command']=='PROCEED'
    assert NavigationIntent.from_record(intent.to_record())==intent
    changes=[('game_state','gold',raw['game_state']['gold']+1),
             ('game_state','screen_type','SHOP_SCREEN'),
             ('jev_protocol','revision',raw['jev_protocol']['revision']+1),
             ('jev_protocol','epoch','another-process')]
    for group,key,value in changes:
        changed=deepcopy(raw);changed[group][key]=value
        assert intent.resolve(changed,actions) is None
    changed=deepcopy(raw);changed['game_state']['jev_identity']['room_id']='other-room'
    assert intent.resolve(changed,actions) is None
    assert intent.resolve(raw,[a for a in actions if a['command']!='PROCEED']) is None


def test_committed_exit_does_not_reask_model_or_hit_old_room_loop_limit(tmp_path):
    row=example();raw=row['after']
    def unwanted(*args):raise AssertionError('Reasked an already chosen shop exit')
    s=RunSession(tmp_path,mode='mock',selector=unwanted,catalog={})
    s.step_id=row['step_id']
    s._record('action_confirmed',before=row['before'],after=raw,decision=row['decision'])
    s.memory.visit=lambda *args:False
    assert s.receive(raw)==['STATE']
    command=s.receive(raw)[0]
    assert command.startswith('JEV_ACTION ') and command.endswith(' PROCEED')
    rows=[json.loads(line) for line in (tmp_path/'runs.jsonl').read_text().splitlines()]
    decision=next(r for r in rows if r['status']=='decision')
    assert decision['source']=='native_navigation_commit'
    assert decision['decision']['navigation_commit_of']==row['step_id']
    recovered=RunSession(tmp_path,mode='mock',selector=unwanted,catalog={})
    recovered._restore_transaction(raw)
    assert recovered.native_navigation_intent==s.native_navigation_intent
    assert recovered.transaction.data['command']=='PROCEED'


def test_shop_close_candidate_states_the_semantic_exit():
    row=example();summary,actions=prepare_journey(row['before'])
    offered=describe_candidates(summary,actions)
    assert next(a for a in offered if a['command']=='LEAVE')['description']=='结束购物并离开商店房间。'
    assert NavigationIntent.after_action({'command':'CHOOSE 0'},row['before'],row['after'],0) is None
