"""Pure adapter using native legality; this does not simulate card effects."""
from copy import deepcopy

from .state import UnsupportedState, CARDS, UPGRADED_EFFECTS, _require, _integer, _string


def _boolean(value):
    _require(type(value) is bool, 'Native flag must be boolean.')
    return value


def _list(value):
    _require(isinstance(value, list), 'Native collection must be a list.')
    return value


def _metadata(value):
    _require(isinstance(value, dict), 'Native metadata must be an object.')
    return deepcopy(value)


def _powers(values):
    result = []
    for value in _list(values):
        item = _metadata(value)
        _string(item['id'])
        _string(item['name'])
        _integer(item['amount'], None)
        item['effect'] = 'unknown'
        result.append(item)
    return result


def _orbs(values):
    result = []
    for value in _list(values):
        orb = _metadata(value)
        _string(orb['id'])
        if 'name' in orb:
            _string(orb['name'])
        for field in ('evoke_amount', 'passive_amount'):
            if field in orb:
                _integer(orb[field], None)
        orb['effect'] = 'unknown'
        result.append(orb)
    return result


def _cards(values, hand=False):
    result = []
    for index, value in enumerate(_list(values)):
        card = _metadata(value)
        for field in ('id', 'name', 'uuid'):
            _string(card[field])
        for field in ('type', 'rarity'):
            if field in card:
                _string(card[field])
        _integer(card['cost'], -2)
        _integer(card['upgrades'])
        for field in ('is_playable', 'has_target', 'exhausts', 'ethereal'):
            _boolean(card[field])
        card['effect'] = 'unknown'
        if card['id'] in CARDS and card['upgrades'] in (0, 1):
            card['effect'] = (UPGRADED_EFFECTS[card['id']] if card['upgrades'] else '基础' + CARDS[card['id']][1]) + '（实际效果受双方能力影响）'
        if hand:
            card.update(hand_index=index, play_index=index + 1, card_uuid=card['uuid'])
        result.append(card)
    return result


def _enemies(values):
    result = []
    for index, value in enumerate(_list(values)):
        enemy = _metadata(value)
        for key in ('current_hp', 'max_hp', 'block'):
            _integer(enemy[key])
        for key in ('is_gone', 'half_dead'):
            _boolean(enemy[key])
        if 'is_dead' in enemy:
            _boolean(enemy['is_dead'])
        for key in ('name', 'intent'):
            _string(enemy[key])
        for key in ('move_adjusted_damage', 'move_hits'):
            amount = _integer(enemy[key], None)
            enemy[key] = amount if amount >= 0 else None
        enemy['powers'] = _powers(enemy['powers'])
        enemy['target_index'] = index
        result.append(enemy)
    return result


def _live(enemies):
    return [e for e in enemies if e['current_hp'] > 0 and not e['is_gone'] and not e['half_dead'] and not e.get('is_dead', False)]


def _action(command, description, **metadata):
    return {'id': command.lower().replace(' ', '_'), 'command': command, 'description': description,
            'hand_index': None, 'card_uuid': None, 'target_index': None, **metadata}


def potion_candidates(raw):
    """Use original zero-based potion slots, gated by native flags and commands."""
    try:
        _require(raw['in_game'] is True and raw['ready_for_command'] is True, 'State is not ready.')
        commands = _list(raw['available_commands'])
        _require(all(isinstance(c, str) for c in commands), 'Invalid native commands.')
        game = raw['game_state']
        targets = None
        actions = []
        for index, value in enumerate(_list(game.get('potions', []))):
            potion = _metadata(value)
            potion_id = _string(potion['id'])
            if potion_id == 'Potion Slot':
                continue
            use = _boolean(potion['can_use'])
            discard = _boolean(potion['can_discard'])
            targeted = _boolean(potion['requires_target'])
            name = _string(potion['name'])
            if 'potion' not in commands:
                continue
            metadata = dict(kind='potion', potion_index=index, potion_id=potion_id)
            if use:
                if targeted and targets is None:
                    targets = _live(_enemies(game['combat_state']['monsters']))
                for enemy in targets if targeted else [None]:
                    target = enemy['target_index'] if enemy is not None else None
                    command = f'POTION USE {index}' + (f' {target}' if target is not None else '')
                    actions.append(_action(command, f'Use {name}', subaction='use', target_index=target, **metadata))
            if discard:
                actions.append(_action(f'POTION DISCARD {index}', f'Discard {name}', subaction='discard', **metadata))
        return actions
    except (KeyError, TypeError, AttributeError, IndexError):
        raise UnsupportedState('Malformed native potion state.') from None


def prepare_native_combat(raw):
    """Return validated native metadata and only pre-generated legal commands."""
    try:
        _require(raw['in_game'] is True and raw['ready_for_command'] is True, 'State is not ready.')
        game = raw['game_state']
        _require(game['class'] == 'IRONCLAD', 'Only Ironclad is supported initially.')
        _require(game['room_phase'] == 'COMBAT' and game['action_phase'] == 'WAITING_ON_USER', 'Combat is not stable.')
        _require(game['screen_type'] == 'NONE' and game['is_screen_up'] is False, 'A selection screen is open.')
        commands = _list(raw['available_commands'])
        _require(all(isinstance(c, str) for c in commands), 'Invalid native commands.')
        combat = game['combat_state']
        _require(combat['limbo'] == [], 'Cards are resolving.')
        player = _metadata(combat['player'])
        for key in ('current_hp', 'max_hp', 'block', 'energy'):
            _integer(player[key])
        _require(player['current_hp'] > 0, 'Player is dead.')
        player['powers'] = _powers(player['powers'])
        player['orbs'] = _orbs(player['orbs'])
        summary = dict(turn=_integer(combat['turn'], 1), player=player,
                       hand=_cards(combat['hand'], True), enemies=_enemies(combat['monsters']),
                       draw_order_known=False)
        for pile in ('draw_pile', 'discard_pile', 'exhaust_pile'):
            summary[pile] = _cards(combat.get(pile, []))
        summary['relics'] = [_metadata(r) for r in _list(game.get('relics', []))]
        for relic in summary['relics']:
            _string(relic['id'])
            if 'counter' in relic:
                _integer(relic['counter'], None)
            relic['effect'] = 'unknown'
        summary['potions'] = deepcopy(_list(game.get('potions', [])))
        actions = []
        if 'play' in commands:
            for card in summary['hand']:
                if not card['is_playable']:
                    continue
                for enemy in _live(summary['enemies']) if card['has_target'] else [None]:
                    target = enemy['target_index'] if enemy else None
                    command = f"PLAY {card['play_index']}" + (f' {target}' if target is not None else '')
                    actions.append(_action(command, f"{card['name']}: {card['effect']}", kind='play', hand_index=card['hand_index'], card_uuid=card['uuid'], target_index=target))
        if 'end' in commands:
            actions.append(_action('END', 'End turn', kind='end'))
        actions.extend(potion_candidates(raw))
        _require(bool(actions), 'No supported native candidates.')
        return summary, actions
    except (KeyError, TypeError, AttributeError, IndexError):
        raise UnsupportedState('Malformed native combat state.') from None
