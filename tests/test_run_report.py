import pytest

from slay_jev_spire.records import render_run_report


def test_review_distinguishes_interruption_from_a_finished_run_and_scopes_coverage():
    from slay_jev_spire.records import review_run
    rows=[{'run_id':'other','status':'complete','after':{'game_state':{'screen_type':'GAME_OVER','screen_state':{'victory':True}}}},
          {'run_id':'one','status':'created','code_version':'v1','components':{'rules.py':'abc'}},
          {'run_id':'one','status':'action_confirmed','step_id':1,'decision':{'action':{'kind':'screen_rest'}},
           'before':{'game_state':{'act':1,'floor':8,'screen_type':'REST','current_hp':20}},
           'after':{'game_state':{'act':1,'floor':8,'screen_type':'MAP','current_hp':44}}},
          {'run_id':'one','status':'stopped','step_id':2,'reason':'state_timeout',
           'after':{'game_state':{'act':1,'floor':9,'screen_type':'SHOP_SCREEN','current_hp':44}}}]
    packet=review_run(rows,'one')
    assert not packet['outcome']['completed'] and packet['outcome']['victory'] is None
    assert packet['coverage']['REST']['confirmed_actions']==1
    assert packet['coverage']['SHOP_SCREEN']['observed'] and packet['coverage']['SHOP_SCREEN']['confirmed_actions']==0
    assert not packet['coverage']['GAME_OVER']['observed']
    assert packet['code_version']=='v1' and packet['hotspots'][0]['category']=='technical_stop'


def test_review_records_death_as_terminal_without_calling_hp_loss_a_policy_error():
    from slay_jev_spire.records import review_run
    before={'game_state':{'act':2,'floor':25,'screen_type':'NONE','current_hp':12}}
    after={'game_state':{'act':2,'floor':25,'screen_type':'GAME_OVER','current_hp':0,'screen_state':{'victory':False,'score':300}}}
    rows=[{'run_id':'one','status':'action_confirmed','step_id':3,'before':before,'after':after,'decision':{'action':{'kind':'end'}}},
          {'run_id':'one','status':'complete','after':after,'reason':'game_over'}]
    packet=review_run(rows,'one')
    assert packet['outcome']['completed'] and packet['outcome']['victory'] is False
    assert packet['outcome']['max_floor']==25
    assert packet['hotspots'][0]['evidence_status']=='review_candidate_not_proven_mistake'


def test_run_reader_uses_exact_identity_and_latest_run(tmp_path):
    from slay_jev_spire.records import read_run_records
    import json
    p=tmp_path/'runs.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in [
        {'run_id':'a','status':'created'},{'run_id':'ab','message':'mentions a'},
        {'run_id':'a','status':'complete'},{'run_id':'b','status':'created'}])+'\n',encoding='utf-8')
    assert len(read_run_records(p,'a'))==2
    assert read_run_records(p)[0]['run_id']=='b'


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
