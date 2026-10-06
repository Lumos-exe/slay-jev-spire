from tools.audit_strategy import fixture, card
from slay_jev_spire import rules
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans


def angry_case(cards, **kwargs):
    case = fixture('angry', cards, enemy_hp=21, damage=4,
                   enemy_powers=[('Angry', 1)], **kwargs)
    case['raw']['game_state']['combat_state']['monsters'][0].update(
        id='GremlinWarrior', move_base_damage=4)
    return case


def test_bash_cleave_lethal_is_recalled_across_angry_strength_change():
    case = angry_case([dict(card('Bash', 2, damage=10, magic=3), upgrades=1),
                       card('Cleave', 1, damage=8), card('Defend_R', 1, 'SKILL', block=5)])
    plans, stats = generate_plans(*prepare_native_combat(case['raw']))
    kill = next(p for p in plans if p['outcome']['combat_won'])
    assert [s['card_id'] for s in kill['sequence']] == ['Bash', 'Cleave']
    assert kill['outcome']['incoming_hp_loss'] == 0
    assert kill['checkpoint'] is None
    assert not stats['observation_boundaries']


def test_angry_updates_current_attack_and_keeps_remaining_cards_legal():
    case = angry_case([card('Strike_R', 1, damage=6), card('Defend_R', 1, 'SKILL', block=5)])
    state = rules.initial(prepare_native_combat(case['raw'])[0])
    state = rules.play(state, next(s for s in rules.legal_steps(state) if s['kind'] == 'play' and s.get('target_index') == 0))
    assert state['enemies'][0]['powers']['Strength'] == 1
    assert state['enemies'][0]['damage'] == 5
    assert state['checkpoint'] is None and rules.legal_steps(state)
    state = rules.play(state, rules.legal_steps(state)[0])
    assert rules.outcome(state)['incoming_hp_loss'] == 0


def test_angry_missing_native_base_damage_still_requires_observation():
    case = angry_case([card('Strike_R', 1, damage=6)])
    enemy = case['raw']['game_state']['combat_state']['monsters'][0]
    enemy.pop('move_base_damage')
    enemy['powers'].append(dict(id='Strength', name='Strength', amount=2))
    state = rules.initial(prepare_native_combat(case['raw'])[0])
    state = rules.play(state, rules.legal_steps(state)[0])
    assert state['checkpoint'] == 'enemy_intent_recalculation'
    assert 'missing_base_intent' in state['uncertainties']


def test_angry_blocked_hit_and_thorns_damage_do_not_grow_strength():
    case = angry_case([card('Strike_R', 1, damage=6)])
    state = rules.initial(prepare_native_combat(case['raw'])[0])
    state['enemies'][0]['block'] = 6
    rules.damage_enemy(state, 0, 6)
    assert not state['enemies'][0]['powers'].get('Strength')
    rules.damage_enemy(state, 0, 3, attack=False)
    assert not state['enemies'][0]['powers'].get('Strength')
