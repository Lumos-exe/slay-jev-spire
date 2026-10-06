from copy import deepcopy
import pytest
from tests.test_policy_quality import battle, card
from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans


def test_boss_start_relic_does_not_disable_observed_turn():
    raw=battle([card('Strike_R',1,damage=6)],relics=[{'id':'Pantograph'}])
    plans,stats=generate_plans(*prepare_native_combat(raw))
    assert plans and not stats['fallback_required']


def test_confusion_uses_observed_cost_until_next_draw_even_for_known_card():
    raw=battle([card('Strike_R',0,damage=6)],powers=[{'id':'Confusion','name':'Confusion','amount':-1}])
    plans,stats=generate_plans(*prepare_native_combat(raw))
    assert plans and not stats['fallback_required']
    state=rules.initial(prepare_native_combat(raw)[0])
    held=state['hand'].pop();state['draw_pile']=[held];state['known_top']=[held['uuid']]
    rules.draw(state,1)
    assert state['checkpoint']=='confusion_draw_cost'
    assert not state['hand']  # Never claim the old zero cost survived redrawing.


def test_hex_adds_status_without_disabling_known_attacks_or_defense():
    raw=battle([card('Defend_R',1,'SKILL',block=5,target=False),card('Strike_R',1,damage=6)],
        powers=[{'id':'Hex','name':'Hex','amount':1}])
    plans,stats=generate_plans(*prepare_native_combat(raw))
    assert plans and not stats['fallback_required']
    state=rules.initial(prepare_native_combat(raw)[0])
    state=rules.play(state,next(s for s in rules.legal_steps(state) if s['card_uuid']=='Defend_R'))
    assert state['checkpoint'] is None
    assert [(c['id'],c['ethereal']) for c in state['draw_pile']]==[('Dazed',True)]
    assert rules.outcome(state)['new_status_cards']==1
    state=rules.play(state,rules.legal_steps(state)[0])
    assert len(state['draw_pile'])==1


@pytest.mark.parametrize('intent',['UNKNOWN','ATTACK'])
def test_wizard_charge_is_not_an_unknown_attack(intent):
    raw=battle([card('Defend_R',1,'SKILL',block=5,target=False)],enemies=2)
    wizard,warrior=raw['game_state']['combat_state']['monsters']
    wizard.update(id='GremlinWizard',intent=intent,move_id=2,move_adjusted_damage=-1)
    warrior.update(id='GremlinWarrior',move_adjusted_damage=4)
    state=rules.initial(prepare_native_combat(raw)[0])
    assert rules.outcome(state)['player_hp_after_turn']==56
    state=rules.play(state,rules.legal_steps(state)[0])
    assert rules.outcome(state)['player_hp_after_turn']==60
