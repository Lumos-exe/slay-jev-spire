"""Run identity is native evidence; seeds and floors are not identities."""
from copy import deepcopy
import json
import pytest

from slay_jev_spire.session import RunSession, DecisionMemory
from slay_jev_spire.screens import prepare_journey
from tests.test_decision_memory import screens
from slay_jev_spire.identity import recovery_path


def save_rows(tmp_path, run_id):
    path = recovery_path(tmp_path, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(map(json.dumps, declined_rows(run_id))) + '\n')


def frames(run_id='game-a', reward_id='reward-a'):
    rewards, cards = screens()
    for raw in (rewards, cards):
        raw['game_state']['jev_identity'] = dict(version=1, run_id=run_id,
            room_id='room-a', encounter_id='encounter-a')
    rewards['game_state']['screen_state']['rewards'][1]['reward_source_id'] = reward_id
    cards['game_state']['screen_state']['reward_source_id'] = reward_id
    return rewards, cards


def declined_rows(run_id):
    rewards, cards = frames(run_id)
    claim = next(a for a in prepare_journey(rewards)[1] if a['command'] == 'CHOOSE 1')
    skip = next(a for a in prepare_journey(cards)[1] if a['command'] == 'SKIP')
    return [dict(run_id=run_id, mode='mock', status='action_confirmed',
                 before=b, after=a, decision={'action': action})
            for b, a, action in ((rewards, cards, claim), (cards, rewards, skip))]


def test_same_seed_different_native_game_never_imports_skip(tmp_path):
    save_rows(tmp_path, 'game-old')
    (tmp_path / 'runs.jsonl').write_text('\n'.join(map(json.dumps, declined_rows('game-old'))) + '\n')
    session = RunSession(tmp_path, mode='mock', catalog={})
    session.receive(frames('game-new')[0])
    assert not session.memory.declined
    assert session.run_id == 'game-new'


@pytest.mark.parametrize('start_new', [False, True])
def test_native_identity_restores_same_game_across_controller_restart(tmp_path, start_new):
    save_rows(tmp_path, 'game-a')
    (tmp_path / 'runs.jsonl').write_text('\n'.join(map(json.dumps, declined_rows('game-a'))) + '\n')
    session = RunSession(tmp_path, mode='mock', catalog={}, start_new=start_new)
    session.receive(frames()[0])
    assert session.run_id == 'game-a'
    assert session.memory.declined


def test_same_floor_different_reward_source_stays_available():
    memory = DecisionMemory()
    for row in declined_rows('game-a'):
        memory.observe(row['before'], row['after'], row['decision'])
    current = frames(reward_id='reward-b')[0]
    actions = prepare_journey(current)[1]
    assert memory.filter(current, actions) == actions


def test_anonymous_reward_cannot_be_hidden_by_floor_history():
    memory = DecisionMemory()
    for row in declined_rows('game-a'):
        memory.observe(row['before'], row['after'], row['decision'])
    current = screens()[0]
    current['game_state'].pop('jev_identity')
    assert memory.filter(current, prepare_journey(current)[1]) == prepare_journey(current)[1]


def test_game_change_with_same_seed_invalidates_pending_decision(tmp_path):
    session = RunSession(tmp_path, mode='mock', catalog={})
    session.receive(frames('game-a')[0])
    assert session.receive(frames('game-b')[0]) == []
    assert session.reason == 'run_changed'


def test_missing_native_identity_does_not_restore_by_seed(tmp_path):
    rows = declined_rows('old')
    for row in rows:
        for key in ('before', 'after'):
            row[key]['game_state'].pop('jev_identity', None)
    (tmp_path / 'runs.jsonl').write_text('\n'.join(map(json.dumps, rows)) + '\n')
    session = RunSession(tmp_path, mode='mock', catalog={})
    current = screens()[0]
    current['game_state'].pop('jev_identity')
    session.receive(current)
    assert not session.memory.recent
