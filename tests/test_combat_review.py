from copy import deepcopy
from slay_jev_spire.combat_protocol import choose_reviewed, review_reason, temporal_view
from slay_jev_spire.selectors import simple_combat_payload
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans
from tests.test_policy_quality import battle, card


def test_review_still_allows_waiting_and_counts_every_request():
    actions=[{'id':'wait','kind':'end'},{'id':'skill','kind':'play'}];seen=[]
    def choose(summary,candidates):
        seen.append((summary['_decision_stage'],[c['id'] for c in candidates]))
        selected=next((c for c in candidates if c['id']=='wait'),candidates[0])
        return {'action':selected,'model_requests':1,'usage':{'input_tokens':10,'output_tokens':1}}
    result=choose_reviewed({},actions,choose)
    assert seen==[('initial',['wait','skill']),('challenger',['skill']),('pair',['skill','wait'])]
    assert result['action']==actions[0]
    assert not result['decision_review']['changed']
    assert result['model_requests']==3 and result['usage']['input_tokens']==30


def test_review_never_invents_or_locally_substitutes_an_action():
    actions=[{'id':'a','kind':'end'},{'id':'b','kind':'play'},{'id':'c','kind':'play'}]
    choices=iter(['a','c','c'])
    def choose(summary,candidates):
        wanted=next(choices)
        return {'action':next(a for a in candidates if a['id']==wanted),'usage':{}}
    result=choose_reviewed({},actions,choose)
    assert result['action'] is actions[2] and result['decision_review']['changed']


def test_temporal_view_keeps_cards_and_separates_status_cost_from_end_hp():
    raw=battle([card('Defend_R',1,'SKILL',block=5,target=False)],powers=[{'id':'Hex','name':'Hex','amount':1}])
    summary,actions=prepare_native_combat(raw);plans,_=generate_plans(summary,actions)
    original=deepcopy(plans)
    state,criteria,refs=simple_combat_payload(summary,plans)
    state,criteria=temporal_view(summary,plans,state,criteria,refs)
    assert plans==original and set(criteria)=={p['id'] for p in plans}
    play=next(p for p in plans if p['sequence'][0]['kind']=='play')
    row=criteria[play['id']]
    assert row['actions'][0]['card']=='Defend_R'
    assert row['after_actions']['generated_cards']=={'Dazed':1}
    assert row['after_actions']['unused_energy']==2
    assert row['if_end_now']['player_hp_remaining']==53
    assert 'turn_steps' not in state
