from slay_jev_spire.session import RunSession


def test_new_run_is_explicit_refreshes_and_sends_once(tmp_path):
    menu = {'in_game': False, 'ready_for_command': True, 'available_commands': ['start', 'state']}
    session = RunSession(tmp_path, mode='mock', start_new=True)
    assert session.receive(menu) == ['STATE']
    assert session.calls == 0
    assert session.receive(menu) == ['START IRONCLAD 0']
    session.command_sent('START IRONCLAD 0')
    assert session.receive(menu) == []
    assert session.actions == 1 and session.calls == 0


def test_default_does_not_start_or_replace_existing_run(tmp_path):
    menu = {'in_game': False, 'ready_for_command': True, 'available_commands': ['start', 'state']}
    session = RunSession(tmp_path, mode='mock')
    assert session.receive(menu) == [] and session.actions == 0
