import json
from copy import deepcopy
from pathlib import Path

from slay_jev_spire.catalog import enrich_summary
from slay_jev_spire.journey import prepare_journey
from slay_jev_spire.run_session import RunSession


def combat():
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    g = raw['game_state']; c = g['combat_state']
    g['relics'] = [{'id': 'Burning Blood', 'name': 'Burning Blood', 'counter': -1}]
    c['player']['powers'] = []
    monster = c['monsters'][0]
    monster.update(id='Cultist', name='Cultist', current_hp=7, block=0, intent='ATTACK', powers=[])
    c['monsters'] = [monster]
    card = deepcopy(c['hand'][0])
    card.update(id='Strike_R', name='Strike', cost=1, is_playable=True, has_target=True, exhausts=False, ethereal=False)
    card['native_values'] = {'source': 'game_card_fields', 'cost_for_turn': 1, 'damage': 6}
    card['target_damage_previews'] = [{'target_index': 0, 'damage_before_block': 6, 'source': 'game_calculateCardDamage'}]
    c['hand'] = [dict(deepcopy(card), uuid=f'strike-{i}') for i in range(3)]
    c['player']['energy'] = 3
    return raw


def test_two_strikes_kill_seven_hp_without_model_request(tmp_path):
    def forbidden(*args):
        raise AssertionError('A proven kill should not need a model choice.')
    raw = combat()
    s = RunSession(tmp_path, mode='mock', selector=forbidden)
    assert s.receive(raw) == ['STATE']
    assert s.calls == 0
    assert s.receive(raw) == ['PLAY 1 0']
    s.command_sent('PLAY 1 0')
    after = deepcopy(raw)
    after['game_state']['combat_state']['hand'].pop(0)
    after['game_state']['combat_state']['player']['energy'] = 2
    after['game_state']['combat_state']['monsters'][0]['current_hp'] = 1
    assert s.receive(after) == ['STATE']
    assert s.receive(after) == ['PLAY 1 0']  # UUID moved to index 1; do not reuse index 2.
    assert s.calls == 0


def test_reactive_power_insufficient_energy_or_missing_preview_prevents_claimed_kill():
    from slay_jev_spire.turn_planner import proven_lethal_plan
    raw = combat()
    for mutation in ('reactive', 'energy', 'missing', 'relic', 'unknown_enemy', 'duplicate_card'):
        changed = deepcopy(raw)
        if mutation == 'reactive': changed['game_state']['combat_state']['monsters'][0]['powers'] = [{'id': 'Curl Up', 'name': 'Curl Up', 'amount': 10}]
        if mutation == 'energy': changed['game_state']['combat_state']['player']['energy'] = 1
        if mutation == 'missing':
            for card in changed['game_state']['combat_state']['hand']: card.pop('target_damage_previews')
        if mutation == 'relic': changed['game_state']['relics'].append({'id': 'Unknown', 'name': 'Unknown', 'counter': 0})
        if mutation == 'unknown_enemy': changed['game_state']['combat_state']['monsters'][0]['id'] = 'ModdedMonster'
        if mutation == 'duplicate_card':
            for card in changed['game_state']['combat_state']['hand']: card['uuid'] = 'same'
        summary, actions = prepare_journey(changed)
        assert proven_lethal_plan(summary, actions) is None


def test_block_is_consumed_sequentially_and_plans_do_not_reuse_cards():
    from slay_jev_spire.turn_planner import proven_lethal_plan
    raw = combat()
    raw['game_state']['combat_state']['monsters'][0]['block'] = 6
    summary, actions = prepare_journey(raw)
    plan = proven_lethal_plan(summary, actions)
    assert len(plan) == 3 and len({a['card_uuid'] for a in plan}) == 3
    raw['game_state']['combat_state']['monsters'][0]['block'] = 12
    assert proven_lethal_plan(*prepare_journey(raw)) is None
