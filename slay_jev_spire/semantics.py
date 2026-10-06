"""Shared, observable action preconditions for normalized simulator states.

Display text and target previews are derived metadata. Missing primitive fields
remain None; they are not silently interpreted as zero/false. Simulation-only
history is retained separately by search_key, which is deliberately stricter.
"""
from copy import deepcopy

CARD_FIELDS = ('uuid', 'id', 'type', 'cost', 'upgrades', 'base_damage',
    'base_block', 'magic_number', 'free_to_play_once', 'exhaust_on_use_once',
    'exhausts', 'ethereal', 'retain', 'self_retain', 'purge_on_use', 'target_type',
    'has_target', 'can_upgrade', 'upgrade_preview')
ENEMY_FIELDS = ('id', 'entity_id', 'hp', 'max_hp', 'block', 'intent', 'damage',
    'base_damage', 'hits', 'gone', 'half_dead', 'move_id', 'monster_state')


def card_semantics(card):
    return {key: deepcopy(card.get(key)) for key in CARD_FIELDS}


def observable_state(state, counters=False):
    result = {key: deepcopy(state[key]) for key in ('turn', 'energy', 'hp',
        'max_hp', 'block', 'relics', 'potions', 'combust_hp_loss')}
    result['identity'] = deepcopy(state.get('identity'))
    result['powers'] = {k: v for k, v in state['powers'].items() if v != 0 or k in {'Invincible', 'Time Warp'}}
    for pile in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile'):
        result[pile] = sorted(map(card_semantics, state[pile]), key=lambda c: str(c['uuid']))
    result['hand_order'] = [c['uuid'] for c in state['hand']]
    result['enemies'] = [
        {key: deepcopy(enemy.get(key)) for key in ENEMY_FIELDS} |
        {'powers': {k: v for k, v in enemy['powers'].items() if v != 0 or k in {'Invincible', 'Time Warp'}} if enemy['hp'] > 0 else {}}
        for enemy in state['enemies']]
    for enemy in result['enemies']:
        if enemy['hp'] == 0 and not enemy['half_dead']:
            # Native death animation cleanup toggles is_gone later. Such a
            # corpse cannot be targeted or act; half-dead revivers stay distinct.
            enemy['gone'] = True
    if counters:
        result['turn_counters'] = {k: state[k] for k in ('plays', 'attacks', 'skills', 'attacks_this_combat')}
    return result
