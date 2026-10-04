import json
from copy import deepcopy
from pathlib import Path

from slay_jev_spire.state import enrich_summary
from slay_jev_spire.screens import prepare_journey
from slay_jev_spire.session import RunSession


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
    card['native_values'] = {'source': 'game_card_fields', 'cost_for_turn': 1, 'damage': 6, 'base_damage': 6, 'base_block': -1, 'block': 0, 'magic_number': -1}
    card['target_damage_previews'] = [{'target_index': 0, 'damage_before_block': 6, 'source': 'game_calculateCardDamage'}]
    c['hand'] = [dict(deepcopy(card), uuid=f'strike-{i}') for i in range(3)]
    c['player']['energy'] = 3
    return raw
