from slay_jev_spire.records import run_metrics


def event(status, step, **kw):
    return {'status': status, 'step_id': step, 'run_id': 'run', **kw}


def test_metrics_separate_duplicates_failures_confirmations_and_inflight():
    rows = []
    for step in (1, 2):
        rows += [event('request_started', step, summary={'floor': 4, 'decision_context': {'recent_actions': [step]}}, candidates=[{'command': 'SKIP'}]),
                 event('decision', step), event('command_sent', step), event('action_confirmed', step)]
    rows += [event('request_started', 3, summary={}, candidates=[]),
             event('stopped', 3, reason='selection_error'),
             event('request_started', 4, summary={'floor': 5}, candidates=[])]
    metrics = run_metrics(rows)
    assert metrics['api_requests'] == 4
    assert metrics['valid_decisions'] == 2
    assert metrics['confirmed_actions'] == 2
    assert metrics['duplicate_requests'] == 1
    assert metrics['failed_requests'] == 1
    assert metrics['pending_requests'] == 1


def test_explicit_start_does_not_count_as_api_request_or_model_answer():
    rows = [event('decision', 1, source='explicit_launch_option'), event('command_sent', 1), event('action_confirmed', 1)]
    metrics = run_metrics(rows)
    assert metrics['api_requests'] == 0 and metrics['valid_decisions'] == 0
    assert metrics['confirmed_actions'] == 1


def test_shop_two_stage_model_calls_are_not_counted_as_one():
    rows=[event('request_started',1),event('decision',1,decision={'model_requests':2}),
          event('decision',2,decision={'model_requests':2},source='reused_shop_plan')]
    metrics=run_metrics(rows)
    assert metrics['api_requests']==2 and metrics['logical_requests']==1
    assert metrics['api_count_complete']
