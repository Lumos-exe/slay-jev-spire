from copy import deepcopy
from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import projection
from tests.test_policy_quality import battle, card


def test_thunderclap_native_unused_magic_field_does_not_remove_vulnerable():
    # Live steps 67 and 164: native ThunderClap.use constructs VulnerablePower
    # with iconst_1; magicNumber/baseMagicNumber are both -1 (not applicable).
    raw = battle([card('Thunderclap', 1, damage=4, magic=-1, target=False),
                  card('Strike_R', 1, damage=6)], energy=2)
    state = rules.initial(prepare_native_combat(raw)[0])
    state = rules.play(state, next(s for s in rules.legal_steps(state) if s['card_uuid']=='Thunderclap'))
    assert state['enemies'][0]['powers'].get('Vulnerable') == 1
    state = rules.play(state, next(s for s in rules.legal_steps(state) if s['card_uuid']=='Strike_R'))
    assert state['enemies'][0]['hp'] == 40 - 4 - 9


def test_sleeping_lagavulin_damage_requires_observing_wake_transition():
    raw = battle([card('Carnage', 2, damage=20)])
    enemy = raw['game_state']['combat_state']['monsters'][0]
    enemy.update(id='Lagavulin', intent='SLEEP', block=8, powers=[{'id':'Metallicize','name':'Metallicize','amount':8}])
    state = rules.initial(prepare_native_combat(raw)[0])
    state = rules.play(state, rules.legal_steps(state)[0])
    assert state['checkpoint'] == 'lagavulin_wake'
    assert rules.outcome(state)['forecast_scope'] == 'partial'


def test_fully_dead_cleanup_does_not_invalidate_other_target_actions():
    state = rules.initial(prepare_native_combat(battle([card('Strike_R',1,damage=6)]))[0])
    state['enemies'][0]['hp'] = 0
    after = deepcopy(state); after['enemies'][0]['gone'] = True
    assert projection(state) == projection(after)
    state['enemies'][0]['hp'] = after['enemies'][0]['hp'] = 10
    assert projection(state) != projection(after)


def test_victory_relic_does_not_disable_current_turn_enumeration():
    from slay_jev_spire.turn_planner import generate_plans
    raw = battle([card('Strike_R',1,damage=6)], relics=[{'id':'Meat on the Bone'}])
    plans, stats = generate_plans(*prepare_native_combat(raw))
    assert plans and stats['enumeration_complete'] and not stats['fallback_required']
    position = plans[0]['outcome']['position']
    assert any(e['source']=='Meat on the Bone' and e['trigger']=='combat_victory'
               for e in position['future_resources']['delayed_effects'])
