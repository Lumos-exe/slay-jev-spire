from copy import deepcopy

from tools.abc_experiment import payload,common_summary,assess_lethal
from tools.audit_strategy import fixture,card
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans


def case():
    raw=fixture('abc',[dict(card('Bash',2,damage=10,magic=3),upgrades=1),
                       dict(card('Cleave',1,damage=8),has_target=False),
                       card('Defend_R',1,'SKILL',block=5)],enemy_hp=21,damage=4,
                enemy_powers=[('Angry',1)],relics=[{'id':'Burning Blood'}])['raw']
    raw['game_state']['combat_state']['monsters'][0]['id']='GremlinWarrior'
    summary,actions=prepare_native_combat(raw)
    candidates,_=generate_plans(summary,actions)
    return summary,candidates


def test_abc_keeps_native_state_options_order_and_instructions_identical():
    summary,candidates=case();original=deepcopy((summary,candidates))
    wires=[payload(summary,candidates,arm) for arm in 'ABC']
    assert (summary,candidates)==original
    assert wires[0]['aliases']==wires[1]['aliases']==wires[2]['aliases']
    assert wires[0]['instructions']==wires[1]['instructions']==wires[2]['instructions']
    for key in summary:
        assert wires[0]['state'][key]==wires[1]['state'][key]==wires[2]['state'][key]
    assert wires[0]['state']['turn_steps']==wires[1]['state']['turn_steps']==wires[2]['state']['turn_steps']
    for key in wires[0]['criteria']:
        assert wires[0]['criteria'][key]['sequence']==wires[1]['criteria'][key]['sequence']==wires[2]['criteria'][key]['sequence']


def test_a_has_no_forecasts_and_b_has_only_preregistered_simple_results():
    summary,candidates=case()
    a=payload(summary,candidates,'A');b=payload(summary,candidates,'B');c=payload(summary,candidates,'C')
    assert all(set(v)=={'sequence'} for v in a['criteria'].values())
    assert not {'outcome_baseline','position_baseline','position_templates','tactical_columns'} & a['state'].keys()
    assert 'outcome_baseline' not in b['state']
    for key in b['criteria']:
        assert set(b['criteria'][key]['simple_result'])=={'enemy_hp_by_target','incoming_hp_loss','player_hp_after_turn',
                                               'remaining_energy','block','combat_won','forecast_scope'}
        assert b['criteria'][key]['simple_result']==c['criteria'][key]['simple_result']
    assert 'position_baseline' not in b['state']
    assert 'position_baseline' in c['state']


def test_lethal_metric_ignores_the_simulators_claimed_results():
    summary,candidates=case()
    kill=next(p for p in candidates if [s.get('card_id') for s in p['sequence']]==['Bash','Cleave'])
    kill['outcome']={'combat_won':False,'enemy_hp':999}
    end=next(p for p in candidates if p['sequence']==[{'kind':'end'}])
    end['outcome']={'combat_won':True,'enemy_hp':0}
    assert assess_lethal(summary,kill)
    assert not assess_lethal(summary,end)


def test_common_state_drops_old_strategy_instructions_for_all_arms():
    result=common_summary({'player':{},'encounter_mechanics':['old advice'],
        'decision_context':{'objective':'old preference','recent_actions':[{'command':'PLAY 1'}]},
        'combat_choice_mode':'native_actions'})
    assert result=={'player':{},'observed_recent_actions':[{'command':'PLAY 1'}]}
