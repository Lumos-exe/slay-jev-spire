import copy
import json
from pathlib import Path

from slay_jev_spire.session import RunSession
from slay_jev_spire.session import resume_session
from slay_jev_spire.selectors import choose_mock
from tests.test_journey import reward


def screens():
    rewards = reward()
    g = rewards['game_state']
    g['screen_state']['rewards'] = [{'reward_type': 'EMERALD_KEY'}, {'reward_type': 'CARD'}]
    g['choice_list'] = ['emerald_key', 'card']
    cards = copy.deepcopy(rewards)
    cards['available_commands'] = ['choose', 'skip', 'state']
    g = cards['game_state']
    g['screen_type'] = 'CARD_REWARD'
    g['choice_list'] = ['warcry']
    g['screen_state'] = {'cards': [{'id': 'Warcry', 'name': 'Warcry', 'uuid': 'reward-card'}],
                         'skip_available': True, 'bowl_available': False}
    return rewards, cards


def skip_selector(summary, actions):
    wanted = 'SKIP' if summary['screen_type'] == 'CARD_REWARD' else 'CHOOSE 1'
    return choose_mock(summary, sorted(actions, key=lambda a: a['command'] != wanted))


def skipped_session(tmp_path):
    rewards, cards = screens()
    s = RunSession(tmp_path, mode='mock', selector=skip_selector, catalog={})
    assert s.receive(rewards) == ['STATE']
    assert s.receive(rewards) == ['CHOOSE 1']
    s.command_sent('CHOOSE 1')
    assert s.receive(cards) == ['STATE']
    assert s.receive(cards) == ['SKIP']
    s.command_sent('SKIP')
    return s, rewards


def test_skip_is_remembered_and_other_reward_indices_stay_native(tmp_path):
    s, rewards = skipped_session(tmp_path)
    seen = []
    def inspect(summary, actions):
        seen.append((summary, actions))
        return choose_mock(summary, actions)
    s.selector = inspect
    assert s.receive(rewards) == ['STATE']
    summary, actions = seen[-1]
    assert 'CHOOSE 1' not in [a['command'] for a in actions]
    assert 'CHOOSE 0' in [a['command'] for a in actions]
    assert summary['decision_context']['recent_actions'][-1]['command'] == 'SKIP'
    assert summary['decision_context']['declined_card_rewards']


def test_skip_memory_survives_resume_and_process_restart(tmp_path):
    s, rewards = skipped_session(tmp_path)
    s.max_decisions = 1
    s.receive(rewards)
    assert s.reason == 'decision_limit'
    resumed = resume_session(s, 20, session_factory=RunSession)
    captured = []
    def inspect(summary, actions):
        captured.append(actions)
        return choose_mock(summary, actions)
    resumed.selector = inspect
    resumed.receive(rewards)
    assert 'CHOOSE 1' not in [a['command'] for a in captured[-1]]
    restarted = RunSession(tmp_path, mode='mock', selector=inspect, catalog={})
    restarted.receive(rewards)
    assert 'CHOOSE 1' not in [a['command'] for a in captured[-1]]
    fresh = copy.deepcopy(rewards)
    fresh['game_state']['seed'] += 1
    other = RunSession(tmp_path, mode='mock', selector=inspect, catalog={})
    other.receive(fresh)
    assert other.pending[1]['action']['command'] == 'CHOOSE 1' and other.calls == 0


def test_new_game_with_same_seed_does_not_inherit_declined_rewards(tmp_path):
    previous, rewards = skipped_session(tmp_path)
    previous.receive(rewards)
    fresh = RunSession(tmp_path, mode='mock', start_new=True, catalog={})
    assert fresh.receive(rewards) == ['STATE']
    assert fresh.pending[1]['action']['command'] == 'CHOOSE 1'
    assert not fresh.memory.declined


def test_same_state_loop_stops_before_another_model_call(tmp_path):
    from slay_jev_spire.session import DecisionMemory
    memory = DecisionMemory()
    summary = {'screen_type': 'EVENT', 'floor': 2}
    actions = [{'id': 'leave', 'command': 'CHOOSE 0'}]
    assert memory.visit(summary, actions)
    assert memory.visit(summary, actions)
    assert not memory.visit(summary, actions)
    assert memory.repeated_requests == 2


def test_combat_context_preserves_native_damage_and_warns_about_unused_energy(tmp_path):
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['intent'] = 'ATTACK'
    seen = []
    def inspect(summary, actions):
        seen.append((summary, actions))
        return choose_mock(summary, actions)
    RunSession(tmp_path, mode='mock', selector=inspect).receive(raw)
    summary, actions = seen[-1]
    assert summary['decision_context']['playable_card_count'] > 0
    assert summary['decision_context']['remaining_energy'] == 3
    assert all(a['kind'] == 'turn_plan' for a in actions)
    assert any(a['sequence'] == [{'kind': 'end'}] for a in actions)


def test_action_and_time_limits_stop_without_model_calls(tmp_path):
    s = RunSession(tmp_path, mode='mock', max_actions=1, max_seconds=10)
    s.actions = 1
    assert s.receive(reward()) == [] and s.reason == 'action_limit' and s.calls == 0
    t = RunSession(tmp_path / 'timed', mode='mock', max_seconds=10)
    t.run_identity = (123, 'IRONCLAD', 0)
    t.started_at -= 11
    t.tick()
    assert t.reason == 'time_limit' and t.calls == 0


def test_restore_does_not_hide_anonymous_multiple_rewards(tmp_path):
    s, rewards = skipped_session(tmp_path)
    s.receive(rewards)
    multiple = copy.deepcopy(rewards)
    multiple['game_state']['screen_state']['rewards'].append({'reward_type': 'CARD'})
    multiple['game_state']['choice_list'].append('card')
    actions = __import__('slay_jev_spire.screens', fromlist=['prepare_journey']).prepare_journey(multiple)[1]
    assert len([a for a in s.memory.filter(multiple, actions) if a.get('reward', {}).get('reward_type') == 'CARD']) == 2


def test_numeric_resume_flag_can_expand_old_small_budget(tmp_path):
    from slay_jev_spire.session import handle_resume_request
    s = RunSession(tmp_path, mode='mock', max_decisions=20)
    s.calls = 20
    s._stop('decision_limit')
    (tmp_path / 'resume.flag').write_text('500')
    new, resumed = handle_resume_request(s, 20, session_factory=RunSession)
    assert resumed and new.max_decisions == 520


def test_run_cli_accepts_whole_run_budget_but_combat_stays_bounded(tmp_path):
    import subprocess
    import sys
    args = [sys.executable, 'capture_game.py', '--output-dir', str(tmp_path), '--max-decisions', '500']
    whole = subprocess.run(args + ['--run', 'mock'], input='', text=True, capture_output=True, timeout=10)
    assert whole.returncode == 0, whole.stderr
    combat = subprocess.run(args + ['--combat', 'mock'], input='', text=True, capture_output=True, timeout=10)
    assert combat.returncode == 0
    invalid = subprocess.run(args + ['--combat', 'mock', '--max-decisions', '2001'], input='', text=True, capture_output=True, timeout=10)
    assert invalid.returncode == 2 and invalid.stdout == ''


def test_candidate_shows_target_calculation_separately_from_hp_loss():
    from slay_jev_spire.session import describe_candidates
    summary = {'hand': [{'uuid': 'c', 'target_damage_previews': [
        {'target_index': 0, 'damage_before_block': 9, 'source': 'game_calculateCardDamage'}]}]}
    actions = [{'id': 'a', 'kind': 'play', 'card_uuid': 'c', 'target_index': 0,
                'command': 'PLAY 1 0', 'description': 'Strike'}]
    candidate = describe_candidates(summary, actions)[0]
    assert candidate['damage_preview']['damage_before_block'] == 9
    assert 'not final HP loss' in candidate['description']
    assert 'damage_preview' not in actions[0]


def test_cosmetic_damage_flag_change_does_not_cancel_but_numeric_change_does(tmp_path):
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['intent'] = 'ATTACK'
    card = raw['game_state']['combat_state']['hand'][0]
    card['native_values'] = {'source': 'game_card_fields', 'damage': 6, 'damage_modified': True}
    changed = copy.deepcopy(raw)
    changed['game_state']['combat_state']['hand'][0]['native_values']['damage_modified'] = False
    s = RunSession(tmp_path, mode='mock')
    assert s.receive(raw) == ['STATE']
    assert s.receive(changed)[0].startswith('PLAY')
    t = RunSession(tmp_path / 'numeric', mode='mock')
    t.receive(raw)
    changed['game_state']['combat_state']['hand'][0]['native_values']['damage'] = 7
    assert t.receive(changed) == [] and t.reason == 'state_changed'
