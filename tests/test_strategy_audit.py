"""The audit must not call an incomplete search an optimal reference."""
import json

from tools.audit_strategy import (audit_logs, audit_recall, card, exhaustive_reference,
                                 fixture, fixed_cases, objective_value, search_metrics)
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import SearchConfig


def test_log_rate_counts_search_events_only_and_deduplicates_copies(tmp_path):
    search = dict(status='search_completed',run_id='run',session_id='session',
                  decision_id='d1',step_id=1,timestamp='t1',
                  search=dict(truncated=['time_budget','time_budget'],elapsed_ms=501))
    second = dict(search,decision_id='d2',step_id=2,timestamp='t2',
                  search=dict(truncated=[],elapsed_ms=2))
    p=tmp_path/'run.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in [search,second,dict(status='decision')]))
    result=audit_logs([p,p])
    assert result['aggregate']['searches']==2
    assert result['aggregate']['truncated']=={'time_budget':1}
    assert result['aggregate']['time_budget_rate']==.5


def test_empty_logs_report_unknown_rate_not_zero():
    assert search_metrics([])['time_budget_rate'] is None


def test_exhaustive_oracle_finds_surviving_defense_without_heuristic():
    case=next(c for c in fixed_cases() if c['name']=='wide_hand_survival')
    summary,actions=prepare_native_combat(case['raw'])
    result=exhaustive_reference(summary,actions,case['objective'])
    assert result['complete'] and result['nodes']==1241
    # 8 HP, 15 block vs 20 damage: survives at 3 HP and deals 15 damage.
    assert result['optimum']==(True,False,3,-75)


def test_recall_detects_lost_optimum_instead_of_scoring_best_remaining_plan():
    case=fixture('bash', [card('Strike_R',1,damage=6),card('Bash',2,damage=8,magic=2)],enemy_hp=16)
    report=audit_recall([case],SearchConfig(max_nodes=1))
    assert report['eligible']==1 and report['hits']==0
    assert report['cases'][0]['reference']['complete']
    assert report['cases'][0]['failure_stage']=='computation_guard'
    assert not report['cases'][0]['search']['fallback_required']


def test_reference_budget_and_unknown_effect_are_not_oracles():
    case=fixed_cases()[0]
    summary,actions=prepare_native_combat(case['raw'])
    assert not exhaustive_reference(summary,actions,'survival',max_nodes=1)['complete']
    unknown=fixture('unknown',[card('Strike_R',1,damage=6)],relics=[{'id':'modded'}])
    report=audit_recall([unknown])
    assert report['eligible']==0 and report['excluded']==1
    assert report['recall_at_k'] is None


def test_objective_ties_accept_interchangeable_sequences():
    out=dict(forecast_scope='deterministic',player_hp_after_turn=3,
             enemy_hp_after_turn_by_target=[20,10],combat_won=False)
    assert objective_value(out,'survival')==(True,False,3,-30)
    assert objective_value(dict(out,forecast_scope='partial'),'survival') is None
