from pathlib import Path

from slay_jev_spire.selectors import choose_mock


def test_resume_preserves_run_steps_and_adds_bounded_budget(tmp_path):
    from slay_jev_spire.session import RunSession
    from slay_jev_spire.session import resume_session
    old = RunSession(tmp_path, mode='mock', selector=choose_mock)
    old.calls, old.actions, old.step_id = 9, 9, 9
    old.run_identity = (123, 'IRONCLAD', 0)
    old._stop('unsupported_state')
    new = resume_session(old, 20, session_factory=RunSession)
    assert new.id != old.id
    assert new.run_id == old.run_id
    assert new.step_id == 9 and new.calls == 9 and new.actions == 9
    assert new.max_decisions == 29 and new.run_identity == old.run_identity
    assert not new.stopped and new.pending is None and new.deadline is None


def test_active_or_finished_session_cannot_resume(tmp_path):
    import pytest
    from slay_jev_spire.session import RunSession
    from slay_jev_spire.session import resume_session
    old = RunSession(tmp_path, mode='mock')
    with pytest.raises(ValueError):
        resume_session(old, 20)
    old._stop('game_over')
    with pytest.raises(ValueError):
        resume_session(old, 20)


def test_resume_request_pauses_active_run_before_reload(tmp_path):
    from slay_jev_spire.session import RunSession
    from slay_jev_spire.session import handle_resume_request
    old = RunSession(tmp_path, mode='mock')
    (tmp_path / 'pause.flag').write_text('pause')
    (tmp_path / 'resume.flag').write_text('resume')
    new, resumed = handle_resume_request(old, 20, session_factory=RunSession)
    assert resumed and old.stopped and old.reason == 'paused'
    assert not new.stopped and new.run_id == old.run_id
    assert not (tmp_path / 'pause.flag').exists()
    assert not (tmp_path / 'resume.flag').exists()


def test_resume_waits_for_outstanding_action_evidence(tmp_path):
    import copy
    import json
    from slay_jev_spire.session import RunSession
    from slay_jev_spire.session import handle_resume_request
    raw = json.loads(Path('samples/communication_mod_rewards.json').read_text(encoding='utf-8'))
    old = RunSession(tmp_path, mode='mock')
    old.receive(raw)
    assert old.receive(raw) == ['CHOOSE 0']
    old.command_sent('CHOOSE 0')
    (tmp_path / 'pause.flag').write_text('pause')
    (tmp_path / 'resume.flag').write_text('resume')
    same, resumed = handle_resume_request(old, 20, session_factory=RunSession)
    assert same is old and not resumed and (tmp_path / 'resume.flag').exists()
    after = copy.deepcopy(raw)
    game = after['game_state']
    game['gold'] += 13
    game['screen_state']['rewards'].pop(0)
    game['choice_list'].pop(0)
    old.receive(after)  # 已暂停，但仍保存最新观察。
    new, resumed = handle_resume_request(old, 20, session_factory=RunSession)
    assert resumed and new.actions == 1 and new.step_id == 1
    records = [json.loads(line) for line in (tmp_path / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(row['status'] == 'action_confirmed' and row.get('after') == after for row in records)


def test_resume_can_reconcile_start_before_identity_was_adopted(tmp_path):
    import json
    from slay_jev_spire.session import RunSession
    from slay_jev_spire.session import handle_resume_request
    menu = {'in_game': False, 'ready_for_command': True, 'available_commands': ['start', 'state']}
    old = RunSession(tmp_path, mode='mock', start_new=True)
    old.receive(menu)
    assert old.receive(menu) == ['START IRONCLAD 0']
    old.command_sent('START IRONCLAD 0')
    (tmp_path / 'pause.flag').write_text('pause')
    (tmp_path / 'resume.flag').write_text('resume')
    after = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    after['game_state']['class'] = 'IRONCLAD'
    after['game_state']['ascension_level'] = 0
    old.receive(after)
    assert old.run_identity is None
    new, resumed = handle_resume_request(old, 20, session_factory=RunSession)
    assert resumed
    assert new.run_identity == (after['game_state']['seed'], 'IRONCLAD', 0)
