"""Optional gameplay-effect evidence, separate from native transactions."""
from copy import deepcopy
from .screens import screen_effect_evidence as confirm_screen

def effect_evidence(before: dict, after: dict, action: dict) -> str | None:
    """Best-effort effect audit, never command acceptance or settlement."""
    if action.get('kind') == 'start':
        game = after.get('game_state', {})
        if after.get('in_game') is True and game.get('class') == 'IRONCLAD' and game.get('ascension_level') == 0:
            return 'requested_run_entered'
        return None
    old = before['game_state']
    new = after.get('game_state', {})
    screen = new.get('screen_type')
    kind = action.get('kind')
    old_screen = old.get('screen_type')
    if kind and kind.startswith('screen_'):
        return confirm_screen(before, after, action)
    if kind == 'potion':
        index = action['potion_index']
        previous = old.get('potions', [])
        current = new.get('potions', [])
        if index < len(previous) and index < len(current) and previous[index].get('id') == action['potion_id']:
            if current[index].get('id') == 'Potion Slot':
                return 'potion_slot_consumed'
            # Entropic Brew等会把刚清空的槽位补上；需要明确的替换证据。
            if action.get('subaction') == 'use' and current[index].get('id') != action['potion_id']:
                return 'potion_slot_replaced'
    if action['command'].startswith('PLAY'):
        if old.get('room_phase') == 'COMBAT' and screen in {'COMBAT_REWARD', 'GAME_OVER', 'COMPLETE'}:
            return 'combat_ended'
        if old_screen == 'NONE' and screen in {'HAND_SELECT', 'GRID', 'CARD_REWARD'}:
            return 'play_opened_selection'
        hand = new.get('combat_state', {}).get('hand')
        if after.get('ready_for_command') is True and isinstance(hand, list) and all((isinstance(c, dict) and ('uuid' in c or 'card_uuid' in c) for c in hand)) and (new.get('room_phase') == 'COMBAT') and (action['card_uuid'] not in {c.get('uuid', c.get('card_uuid')) for c in hand}):
            return 'played_card_left_hand'
    if action['command'] == 'END':
        if screen in {'COMBAT_REWARD', 'GAME_OVER', 'COMPLETE'}:
            return 'combat_ended'
        if old_screen == 'NONE' and screen in {'HAND_SELECT', 'GRID'}:
            return 'turn_end_opened_selection'
        if new.get('combat_state', {}).get('turn', 0) > old['combat_state']['turn']:
            return 'turn_advanced'
    if kind == 'reward':
        reward = action['reward']
        reward_type = reward['reward_type']
        if reward_type in {'SAPPHIRE_KEY', 'EMERALD_KEY'}:
            key = 'sapphire' if reward_type == 'SAPPHIRE_KEY' else 'emerald'
            if old.get('keys', {}).get(key) is False and new.get('keys', {}).get(key) is True:
                return 'key_collected'
        if reward_type == 'CARD' and screen == 'CARD_REWARD':
            return 'card_reward_opened'
        if reward_type == 'RELIC':
            relic_id = reward['relic']['id']
            if sum(r.get('id') == relic_id for r in new.get('relics', [])) > sum(r.get('id') == relic_id for r in old.get('relics', [])):
                return 'relic_reward_collected'
        remaining = new.get('screen_state', {}).get('rewards', [])
        expected = deepcopy(old['screen_state']['rewards'])
        expected.pop(action['choice_index'])
        if screen == old_screen and remaining == expected:
            if reward_type in {'GOLD', 'STOLEN_GOLD'} and new.get('gold', 0) >= old.get('gold', 0) + reward.get('gold', 0):
                return 'gold_reward_collected'
            if reward_type == 'POTION' and new.get('potions') != old.get('potions') and any((p.get('id') == reward['potion'].get('id') for p in new.get('potions', []))):
                return 'potion_reward_collected'
            if reward_type == 'RELIC' and new.get('relics') != old.get('relics') and any((r.get('id') == reward['relic'].get('id') for r in new.get('relics', []))):
                return 'relic_reward_collected'
    if kind == 'card' and old.get('room_phase') == 'COMBAT' and new.get('room_phase') == 'COMBAT':
        old_combat, new_combat = old.get('combat_state',{}), new.get('combat_state',{})
        old_ids = {c.get('uuid') for group in ('hand','draw_pile','discard_pile','exhaust_pile','limbo') for c in old_combat.get(group,[])}
        if any(c.get('id') == action['card']['id'] and c.get('uuid') and c['uuid'] not in old_ids
               for group in ('hand','discard_pile') for c in new_combat.get(group,[])):
            return 'temporary_card_added'
    if kind in {'card', 'bowl', 'skip'} and screen in {'COMBAT_REWARD', 'COMPLETE', 'EVENT'}:
        if kind == 'skip' and new.get('deck') == old.get('deck'):
            return 'card_reward_skipped'
        if kind == 'bowl' and new.get('max_hp', 0) == old.get('max_hp', 0) + 2:
            return 'bowl_hp_increased'
        if kind == 'card':
            card_id = action['card']['id']
            count = lambda g: sum((c.get('id') == card_id for c in g.get('deck', [])))
            if count(new) == count(old) + 1:
                return 'card_added_to_deck'
    if kind == 'proceed' and screen == 'MAP':
        return 'map_opened'
    if (kind == 'proceed' and old_screen == 'COMBAT_REWARD' and screen == 'EVENT'
            and old.get('room_phase') == 'COMPLETE' and new.get('room_phase') in {'EVENT','COMPLETE'}
            and all(old.get(k) == new.get(k) for k in ('act','floor'))
            and new.get('screen_state',{}).get('event_id')):
        return 'reward_overlay_closed_to_event'
    if kind in {'map', 'boss'} and new.get('floor', 0) == old.get('floor', 0) + 1 and (screen != 'MAP'):
        return 'floor_advanced_destination_not_directly_reported'
    return None
