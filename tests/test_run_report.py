import pytest

from slay_jev_spire.run_report import render_run_report


def state(hp, gold=10, screen='COMBAT_REWARD'):
    return {'game_state': {'floor': 1, 'screen_type': screen,
                           'current_hp': hp, 'gold': gold}}


def test_report_distinguishes_sent_confirmed_and_interrupted():
    rows = [
        {'run_id': 'a', 'status': 'decision', 'step_id': 1, 'before': state(70),
         'decision': {'action': {'command': 'CHOOSE 0', 'description': '金币 | 13'},
                      'confidence': 0.8}},
        {'run_id': 'a', 'status': 'command_sent', 'step_id': 1},
        {'run_id': 'a', 'status': 'action_confirmed', 'step_id': 1,
         'after': state(70, 23), 'evidence': 'gold increased'},
        {'run_id': 'b', 'status': 'complete', 'step_id': 99},
        {'run_id': 'a', 'status': 'decision', 'step_id': 2, 'before': state(70, 23),
         'decision': {'action': {'command': 'PROCEED', 'description': '继续'}}},
        {'run_id': 'a', 'status': 'command_sent', 'step_id': 2},
        {'run_id': 'a', 'status': 'stopped', 'step_id': 2, 'reason': 'state_timeout'},
    ]
    report = render_run_report(rows, 'a')
    assert '中断' in report and 'state_timeout' in report
    assert '金币 \\| 13' in report and '+13' in report
    assert '已确认' in report and '已发送，未确认' in report
    assert 'gold increased' in report and '99' not in report
    assert '胜利' not in report


def test_report_only_labels_native_completion_as_finished():
    rows = [{'run_id': 'a', 'status': 'complete',
             'after': {'game_state': {'screen_type': 'GAME_OVER',
                       'screen_state': {'victory': False, 'score': 123}}}}]
    report = render_run_report(rows, 'a')
    assert '死亡' in report and '123' in report
    assert '尚无决策' in report
    with pytest.raises(ValueError):
        render_run_report(rows, 'missing')


def test_report_no_completion_claim_without_game_over_evidence():
    report = render_run_report([{'run_id': 'a', 'status': 'complete'}], 'a')
    assert '未确认整局结束' in report


def test_resumed_run_is_not_still_reported_as_interrupted():
    report = render_run_report([
        {'run_id': 'a', 'status': 'stopped', 'reason': 'decision_limit'},
        {'run_id': 'a', 'status': 'resumed'}], 'a')
    assert '进行中' in report and '结果：中断' not in report
