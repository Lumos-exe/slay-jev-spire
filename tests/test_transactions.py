from copy import deepcopy
import json
from pathlib import Path

from slay_jev_spire.transactions import PendingAction
from slay_jev_spire.session import RunSession


def raw(revision=7):
    value=json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    value['game_state']['combat_state']['monsters'][0]['intent']='ATTACK'
    value['jev_protocol']={'version':1,'epoch':'epoch','revision':revision,'receipt':None}
    value['game_state']['jev_identity'] = dict(version=1, run_id='transaction-game', room_id='room', encounter_id='battle')
    return value


def response(tx,status='settled',revision=8):
    value=raw(revision)
    value['jev_protocol']['receipt']={'id':tx.data['id'],'command':tx.data['command'],
        'expected_revision':7,'status':status,'settled_revision':revision}
    return value


def test_receipt_commits_identical_gameplay_state_without_effect_guess(tmp_path):
    value=raw();session=RunSession(tmp_path,mode='mock',max_actions=1,require_native_receipts=True)
    assert session.receive(value)==['STATE']
    command=session.receive(value)[0]
    assert command.startswith('JEV_ACTION epoch ')
    pending=session.transaction
    assert PendingAction.load(tmp_path/'pending-action.json').data['id']==pending.data['id']
    session.command_sent(command)
    # The gameplay data is deliberately unchanged. Only the native transaction
    # advanced through an accepted command and a later decision boundary.
    after=response(pending)
    assert after['game_state']==value['game_state']
    session.receive(after)
    rows=[json.loads(line) for line in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    confirmed=[r for r in rows if r['status']=='action_confirmed']
    assert len(confirmed)==1 and confirmed[0]['native_receipt']['id']==pending.data['id']
    assert confirmed[0]['effect_evidence'] is None
    assert not (tmp_path/'pending-action.json').exists()


def test_wrong_id_epoch_revision_and_command_never_commit(tmp_path):
    tx=PendingAction.create(tmp_path/'pending.json',raw(),{'action':{'command':'END'}},{})
    value=response(tx);value['jev_protocol']['receipt']['id']='unrelated'
    assert tx.observe(value)[0]=='waiting'
    value=response(tx);value['jev_protocol']['epoch']='restarted'
    assert tx.observe(value)[0]=='epoch_changed'
    value=response(tx);value['jev_protocol']['receipt']['command']='PLAY 1'
    assert tx.observe(value)[0]=='receipt_conflict'
    assert tx.observe(response(tx,revision=7))[0]=='receipt_conflict'
    value=response(tx);value['ready_for_command']=False
    assert tx.observe(value)[0]=='waiting'


def test_accepted_command_is_queried_never_resent(tmp_path):
    now=[0.0]
    tx=PendingAction.create(tmp_path/'pending.json',raw(),{'action':{'command':'END'}},{},clock=lambda:now[0])
    tx.sent();tx.observe(response(tx,'accepted',7))
    now[0]=6
    assert tx.poll()==tx.query
    now[0]=16
    assert tx.timeout_reason() is None
    now[0]=61
    assert tx.timeout_reason()=='native_settlement_timeout'


def test_lost_receipt_resends_same_identity_only_with_bounded_attempts(tmp_path):
    now=[0.0]
    tx=PendingAction.create(tmp_path/'pending.json',raw(),{'action':{'command':'END'}},{},clock=lambda:now[0])
    original=tx.wire;tx.sent()
    now[0]=6
    assert tx.poll()==original
    tx.sent();now[0]=12
    assert tx.poll()==tx.query
    now[0]=16
    assert tx.timeout_reason()=='native_acceptance_timeout'


def test_controller_restart_reconciles_durable_id_before_new_decision(tmp_path):
    first=RunSession(tmp_path,mode='mock',max_actions=1,require_native_receipts=True)
    first.receive(raw());wire=first.receive(raw())[0];first.command_sent(wire)
    tx=first.transaction
    restarted=RunSession(tmp_path,mode='mock',max_actions=1,require_native_receipts=True)
    restarted.receive(response(tx))
    assert restarted.transaction is None
    assert restarted.run_id==first.run_id
    assert restarted.actions==1
    assert not (tmp_path/'pending-action.json').exists()


def test_live_requirement_does_not_silently_use_legacy_effect_confirmation(tmp_path):
    value=raw();value.pop('jev_protocol')
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True)
    assert session.receive(value)==[]
    assert session.reason=='native_protocol_required'


def test_live_game_requires_native_run_identity(tmp_path):
    value = raw(); value['game_state'].pop('jev_identity')
    session = RunSession(tmp_path, mode='mock', require_native_receipts=True)
    assert session.receive(value) == []
    assert session.reason == 'native_identity_required'


def test_changed_game_cannot_commit_old_pending_receipt(tmp_path):
    first = RunSession(tmp_path, mode='mock', require_native_receipts=True)
    first.receive(raw()); wire = first.receive(raw())[0]; first.command_sent(wire)
    value = response(first.transaction)
    value['game_state']['jev_identity']['run_id'] = 'another-game'
    restarted = RunSession(tmp_path, mode='mock', require_native_receipts=True)
    assert restarted.receive(value) == []
    assert restarted.reason == 'run_changed'
    assert (tmp_path / 'pending-action.json').exists()
    rows = [json.loads(line) for line in (tmp_path / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(row['status'] == 'action_confirmed' for row in rows)


def test_explicit_recovery_keeps_querying_and_can_redeliver_same_unaccepted_id(tmp_path):
    from slay_jev_spire.session import handle_resume_request
    now=[0.0]
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True)
    session.receive(raw());wire=session.receive(raw())[0];session.command_sent(wire)
    tx=session.transaction;tx.clock=lambda:now[0];tx.started=0;tx.last_poll=0
    tx.sent()  # Original bounded attempts have been used.
    session._stop('native_acceptance_timeout')
    (tmp_path/'resume.flag').write_text('20')
    same,resumed=handle_resume_request(session,20,session_factory=RunSession)
    assert not resumed and same is session and session.resume_query_pending==tx.query
    session.resume_query_pending=False;now[0]=6
    handle_resume_request(session,20,session_factory=RunSession)
    assert session.resume_query_pending==wire
    session.command_sent(wire)
    assert tx.attempts==3
    session.last_raw=response(tx)
    new,resumed=handle_resume_request(session,20,session_factory=RunSession)
    assert resumed and not new.stopped and not (tmp_path/'pending-action.json').exists()


def test_native_preflight_state_change_discards_unsent_decision_and_replans(tmp_path):
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True)
    assert session.receive(raw())==['STATE']
    fresh=raw(8);fresh['game_state']['combat_state']['player']['current_hp']-=1
    assert session.receive(fresh)==['STATE']
    assert not session.stopped and session.transaction is None and session.actions==0
    wire=session.receive(fresh)[0]
    assert wire.startswith('JEV_ACTION ') and session.transaction.data['revision']==8


def test_stale_native_rejection_is_not_committed_and_uses_a_new_revision(tmp_path):
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True)
    session.receive(raw());wire=session.receive(raw())[0];session.command_sent(wire)
    old_id=session.transaction.data['id']
    value=response(session.transaction,'rejected',8)
    value['jev_protocol']['receipt']['error']='stale_revision'
    assert session.receive(value)==['STATE']
    assert not session.stopped
    session.receive(value)
    assert session.transaction.data['id']!=old_id and session.transaction.data['revision']==8


def test_effect_audit_failure_cannot_veto_a_settled_native_receipt(tmp_path,monkeypatch):
    from slay_jev_spire import session as module
    def audit_failure(*args):raise RuntimeError('optional audit failed')
    monkeypatch.setattr(module,'effect_evidence',audit_failure)
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True,max_actions=1)
    session.receive(raw());wire=session.receive(raw())[0];session.command_sent(wire)
    session.receive(response(session.transaction))
    rows=[json.loads(line) for line in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    committed=next(r for r in rows if r['status']=='action_confirmed')
    assert committed['native_receipt']['status']=='settled'
    assert committed['effect_audit_warning']=='RuntimeError'
    assert session.transaction is None and not (tmp_path/'pending-action.json').exists()


def test_unfamiliar_native_choice_screen_needs_no_effect_specific_adapter():
    from slay_jev_spire.screens import prepare_journey
    from slay_jev_spire.state import UnsupportedState
    import pytest
    value=raw();g=value['game_state']
    g.update(screen_type='FUTURE_CHOICE_SCREEN',room_phase='EVENT',choice_list=['visible A','visible B'],screen_state={'prompt':'Choose one'})
    value['available_commands']=['choose','proceed','state']
    summary,actions=prepare_journey(value)
    assert [a['command'] for a in actions]==['CHOOSE 0','CHOOSE 1','PROCEED']
    assert summary['screen_state']=={'prompt':'Choose one'}
    value.pop('jev_protocol')
    with pytest.raises(UnsupportedState):prepare_journey(value)


def test_native_inflight_wait_does_not_inherit_legacy_effect_timeout(tmp_path):
    session=RunSession(tmp_path,mode='mock',require_native_receipts=True)
    session.receive(raw());wire=session.receive(raw())[0];session.command_sent(wire)
    value=response(session.transaction,'accepted',7);value['ready_for_command']=False
    assert session.receive(value)==[]
    assert session.deadline is None and session.transaction.accepted
