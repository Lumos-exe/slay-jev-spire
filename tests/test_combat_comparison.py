from slay_jev_spire import selectors
from tools.detailed_payload import plan_criteria


def test_all_combat_plans_and_end_reach_the_same_model_comparison(monkeypatch):
    monkeypatch.setenv('JEV_COMBAT_PROTOCOL','baseline')
    plans=[dict(id='attack',kind='turn_plan',sequence=[{'kind':'play'}]),
           dict(id='block',kind='turn_plan',sequence=[{'kind':'play'}]),
           dict(id='end',kind='turn_plan',sequence=[{'kind':'end'}])]
    calls=[]
    def choose(summary,actions):
        calls.append([a['id'] for a in actions])
        assert 'combat_phase' not in summary
        action=actions[-1]
        return dict(action=action,probabilities={a['id']:float(a==action) for a in actions},
                    latency_ms=1,usage={'input_tokens':5,'output_tokens':1})
    monkeypatch.setattr(selectors,'_choose_with_context_limit',choose)
    result=selectors.choose_jev({'player':{}},plans)
    assert calls==[['attack','block','end']]
    assert result['action'] is plans[-1]  # Waiting remains a real choice.
    assert result['usage']['input_tokens']==5


def test_nob_permanent_strength_cost_is_directly_visible_to_ranker():
    from tools.audit_strategy import fixture,card
    from slay_jev_spire.state import prepare_native_combat
    from slay_jev_spire.turn_planner import generate_plans
    case=fixture('nob',[card('Defend_R',1,'SKILL',block=5),card('Strike_R',1,damage=6)],enemy_powers=[('Anger',2)])
    case['raw']['game_state']['combat_state']['monsters'][0]['id']='GremlinNob'
    summary,actions=prepare_native_combat(case['raw'])
    assert summary['encounter_mechanics'][0]['permanent_strength_per_skill']==2
    plans,_=generate_plans(summary,actions)
    defended=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['Defend_R',None])
    attacked=next(p for p in plans if [s.get('card_id') for s in p['sequence']]==['Strike_R',None])
    assert plan_criteria(defended)['tactical']['enemies_growing_from_skills'][0]['strength_after_actions']==2
    assert plan_criteria(attacked)['tactical']['enemies_growing_from_skills'][0]['strength_after_actions']==0
