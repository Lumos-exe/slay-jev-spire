from tools.audit_strategy import fixture,card
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans,SearchConfig
from slay_jev_spire import rules


def test_attack_cancels_slime_slam_instead_of_being_forecast_as_death():
    case=fixture('slime',[card('Strike_R',1,damage=6),card('Strike_R',1,damage=6),
                         card('Defend_R',1,'SKILL',block=5)],energy=2,hp=10,enemy_hp=60,damage=35)
    enemy=case['raw']['game_state']['combat_state']['monsters'][0]
    enemy.update(id='SlimeBoss',max_hp=100,move_id=1,powers=[dict(id='Split',name='Split',amount=1)])
    summary,actions=prepare_native_combat(case['raw'])
    assert summary['encounter_mechanics'][0]['interrupt']['hp_loss_needed']==10
    plans,_=generate_plans(summary,actions,SearchConfig(beam_width=4))
    interrupt=next(p for p in plans if p['outcome']['interruptions'])
    out=interrupt['outcome']
    assert out['interruptions'][0]['cancelled_attack_damage']==35
    assert out['interruptions'][0]['child_hp_each']==48
    assert out['standing_hp_loss_estimate']==0
    assert interrupt['checkpoint']=='slime_split_intent'
    assert out['forecast_scope']=='partial'  # Observe the real transition.


def test_already_splitting_slime_can_be_burst_lower_before_ending():
    case=fixture('split',[card('Strike_R',1,damage=6),card('Strike_R',1,damage=6)],enemy_hp=48)
    enemy=case['raw']['game_state']['combat_state']['monsters'][0]
    enemy.update(id='SlimeBoss',max_hp=100,move_id=3,intent='UNKNOWN',move_adjusted_damage=-1,move_hits=0,
                 powers=[dict(id='Split',name='Split',amount=1)])
    plans,_=generate_plans(*prepare_native_combat(case['raw']))
    best=next(p for p in plans if p['outcome']['enemy_hp']==36)
    assert best['checkpoint'] is None
    assert best['outcome']['incoming_hp_loss']==0


def test_guardian_threshold_cancels_attack_but_does_not_invent_settled_state():
    case=fixture('guardian',[card('Strike_R',1,damage=6)],hp=5,enemy_hp=100,damage=32,
                 enemy_powers=[('Mode Shift',6)])
    enemy=case['raw']['game_state']['combat_state']['monsters'][0]
    enemy.update(id='TheGuardian',move_id=2)
    plans,_=generate_plans(*prepare_native_combat(case['raw']))
    interrupt=next(p for p in plans if p['outcome']['interruptions'])
    assert interrupt['outcome']['standing_hp_loss_estimate']==0
    assert interrupt['outcome']['interruptions'][0]['pending_block']==20
    assert interrupt['checkpoint']=='enemy_reaction'
    assert not interrupt['outcome']['combat_won']


def test_thief_steals_through_full_block_and_escape_is_a_deadline():
    case=fixture('thief',[card('Impervious',2,'SKILL',block=30)],damage=10,enemy_powers=[('Thievery',15)])
    game=case['raw']['game_state'];game['gold']=100
    enemy=game['combat_state']['monsters'][0]
    enemy.update(id='Looter',move_id=1,monster_state=dict(stolenGold=30,goldAmt=15))
    summary,actions=prepare_native_combat(case['raw'])
    plans,_=generate_plans(summary,actions)
    defended=next(p for p in plans if p['outcome']['block']==30)
    assert defended['outcome']['incoming_hp_loss']==0
    assert defended['outcome']['economy']['targets'][0]['steals_this_enemy_turn']==15
    assert defended['outcome']['economy']['gold_after_known_steals']==85
    enemy.update(move_id=2,intent='DEFEND')
    assert prepare_native_combat(case['raw'])[0]['encounter_mechanics'][0]['player_turns_left_to_prevent_escape']==2
    enemy.update(move_id=3,intent='ESCAPE')
    assert prepare_native_combat(case['raw'])[0]['encounter_mechanics'][0]['player_turns_left_to_prevent_escape']==1


def test_final_candidates_keep_kill_on_escaping_thief_and_refund_is_reward():
    case=fixture('escape',[card('Strike_R',1,damage=6)],enemies=2,enemy_hp=40,damage=0)
    game=case['raw']['game_state'];game['gold']=100
    game['combat_state']['monsters'][1].update(id='Mugger',current_hp=6,move_id=3,intent='ESCAPE',
        monster_state=dict(stolenGold=30,goldAmt=15),powers=[dict(id='Thievery',name='Thievery',amount=15)])
    plans,_=generate_plans(*prepare_native_combat(case['raw']),SearchConfig(beam_width=2))
    kill=next(p for p in plans if p['sequence'][0].get('target_index')==1)
    economy=kill['outcome']['economy']
    assert economy['targets'][0]['recovered_as_reward']==30
    assert not economy['targets'][0]['escapes_this_enemy_turn']
    assert economy['gold_after_known_steals']==100


def test_hexaghost_does_not_have_an_invented_damage_interrupt():
    case=fixture('hex',[card('Strike_R',1,damage=6)],enemy_hp=100)
    case['raw']['game_state']['combat_state']['monsters'][0].update(id='Hexaghost',move_id=6)
    summary,actions=prepare_native_combat(case['raw'])
    assert summary['encounter_mechanics'][0]['interrupt'] is None
    plans,_=generate_plans(summary,actions)
    assert all(not p['outcome']['interruptions'] for p in plans)


def test_thorns_kill_refunds_gold_stolen_before_damage_resolution():
    case=fixture('thorns',[card('Defend_R',1,'SKILL',block=5)],enemy_hp=3,damage=5,
                 enemy_powers=[('Thievery',15)],relics=[{'id':'Bronze Scales'}])
    game=case['raw']['game_state'];game['gold']=100
    game['combat_state']['monsters'][0].update(id='Looter',move_id=1,monster_state=dict(stolenGold=30,goldAmt=15))
    state=rules.initial(prepare_native_combat(case['raw'])[0]);out=rules.outcome(state)
    assert out['enemy_hp_after_turn_by_target']==[0]
    assert out['economy']['targets'][0]['steals_this_enemy_turn']==15
    assert out['economy']['targets'][0]['recovered_as_reward']==45


def test_sharp_hide_is_once_per_attack_card_after_its_block_effect():
    case=fixture('hide',[card('Twin Strike',1,damage=5),card('Iron Wave',1,damage=5,block=5)],
                 enemy_hp=100,enemy_powers=[('Sharp Hide',3)])
    state=rules.initial(prepare_native_combat(case['raw'])[0])
    state=rules.play(state,next(s for s in rules.legal_steps(state) if s['card_uuid'].endswith('Twin Strike')))
    assert state['hp']==27 and not state['checkpoint'] and not state['uncertainties']
    state=rules.play(state,rules.legal_steps(state)[0])
    assert state['hp']==27 and state['block']==2


def test_sharp_hide_triggers_for_attack_on_other_enemy_but_not_skills():
    case=fixture('hide',[card('Strike_R',1,damage=6),card('Defend_R',1,'SKILL',block=5)],enemies=2)
    case['raw']['game_state']['combat_state']['monsters'][1]['powers']=[dict(id='Sharp Hide',name='Sharp Hide',amount=3)]
    state=rules.initial(prepare_native_combat(case['raw'])[0])
    state=rules.play(state,next(s for s in rules.legal_steps(state) if s['target_index']==0))
    assert state['hp']==27
    state=rules.play(state,rules.legal_steps(state)[0])
    assert state['hp']==27 and state['block']==5
