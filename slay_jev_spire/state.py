"""Native state, legal actions and descriptions. No card whitelist."""

from copy import deepcopy
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile
class UnsupportedState(ValueError):
    """输入无效、状态超出覆盖范围或没有支持的候选动作。"""


def _require(condition: bool, message: str) -> None:
    """校验一个条件，失败时抛出不包含原始输入的状态错误。"""
    if not condition:
        raise UnsupportedState(message)


def _integer(value: object, minimum: int | None = 0) -> int:
    """读取整数并校验下限；拒绝布尔值，minimum=None 时允许负数。"""
    _require(type(value) is int and (minimum is None or value >= minimum),
             '状态中的数值字段缺失或不受支持。')
    return value


def _string(value: object) -> str:
    """读取非空字符串；无效值统一转换成安全的状态错误。"""
    _require(isinstance(value, str) and bool(value), '状态中的文字字段缺失或无效。')
    return value







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
            metadata = dict(kind='potion', potion_index=index, potion_id=potion_id, potion=deepcopy(potion))
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
        if 'jev_identity' in game:
            from .identity import GameIdentity
            GameIdentity.from_game(game)
            summary['identity'] = deepcopy(game['jev_identity'])
        _require(len({c['uuid'] for c in summary['hand']}) == len(summary['hand']), 'Duplicate hand UUID.')
        if 'turn_counters' in combat:
            summary['turn_counters'] = deepcopy(combat['turn_counters'])
        for field in ('energy_per_turn','draw_per_turn'):
            if field in combat: summary[field]=_integer(combat[field])
        for pile in ('draw_pile', 'discard_pile', 'exhaust_pile'):
            summary[pile] = sorted(_cards(combat.get(pile, [])), key=lambda c: c['uuid'])
        summary['relics'] = [_metadata(r) for r in _list(game.get('relics', []))]
        for relic in summary['relics']:
            _string(relic['id'])
            if 'counter' in relic:
                _integer(relic['counter'], None)
        summary['potions'] = deepcopy(_list(game.get('potions', [])))
        if 'gold' in game: summary['gold']=_integer(game['gold'])
        from .monsters import encounter_context
        summary['encounter_mechanics']=encounter_context(summary['enemies'])
        actions = []
        if 'play' in commands:
            for card in summary['hand']:
                if not card['is_playable']:
                    continue
                for enemy in _live(summary['enemies']) if card['has_target'] else [None]:
                    target = enemy['target_index'] if enemy else None
                    if target is not None and 'valid_target_indices' in card and target not in card['valid_target_indices']:
                        continue
                    command = f"PLAY {card['play_index']}" + (f' {target}' if target is not None else '')
                    actions.append(_action(command, card['name'], kind='play', hand_index=card['hand_index'], card_uuid=card['uuid'], target_index=target))
        if 'end' in commands:
            actions.append(_action('END', 'End turn', kind='end'))
        actions.extend(potion_candidates(raw))
        _require(bool(actions), 'No supported native candidates.')
        return summary, actions
    except (KeyError, TypeError, AttributeError, IndexError):
        raise UnsupportedState('Malformed native combat state.') from None



def load_catalog(game_jar: Path | None = None) -> dict:
    result = {'cards': {}, 'powers': {}, 'relics': {}}
    if game_jar is None:
        return result
    try:
        with ZipFile(game_jar) as jar:
            for kind in result:
                try:
                    value = json.loads(jar.read(f'localization/eng/{kind}.json').decode('utf-8-sig'))
                    if isinstance(value, dict):
                        result[kind] = {key: entry for key, entry in value.items() if isinstance(key, str) and isinstance(entry, dict)}
                except (KeyError, UnicodeError, ValueError):
                    pass
    except (OSError, BadZipFile, TypeError):
        pass
    return result


def enrich_summary(summary: dict, catalog: dict) -> dict:
    """Recursively annotate identifiable metadata, keeping templates unresolved."""
    result = deepcopy(summary)

    def visit(value, category=None):
        if isinstance(value, list):
            for item in value:
                visit(item, category)
        elif isinstance(value, dict):
            identifier = value.get('id')
            if isinstance(identifier, str) and category in ('cards', 'powers', 'relics'):
                entry = catalog.get(category, {}).get(identifier, {})
                definition=entry.get('NATIVE_DEFINITION')
                if isinstance(definition,dict):
                    value['catalog_ref']={'kind':category,'id':identifier,'version':entry.get('CATALOG_VERSION')}
                    if 'native_mechanics' not in value and 'native_mechanics' in definition:
                        value['native_mechanics']=deepcopy(definition['native_mechanics'])
                    for field in ('tags','keywords','keyword_descriptions'):
                        if field not in value and field in definition:
                            value[field]=deepcopy(definition[field])
                description = entry.get('UPGRADE_DESCRIPTION') if category == 'cards' and type(value.get('upgrades')) is int and value['upgrades'] > 0 else None
                description = description or entry.get('DESCRIPTION') or entry.get('DESCRIPTIONS')
                if isinstance(value.get('native_description'), str) and value['native_description']:
                    description = value['native_description']
                native = value.get('native_values')
                if category == 'cards' and isinstance(native, dict) and native.get('source') == 'game_card_fields':
                    if isinstance(value.get('raw_description'), str) and value['raw_description']:
                        description = value['raw_description']
                    if isinstance(description, str):
                        for token, field in (('!D!', 'damage'), ('!B!', 'block'), ('!M!', 'magic_number')):
                            number = native.get(field)
                            if type(number) is int and number >= 0:
                                description = description.replace(token, str(number))
                    value['value_scope'] = 'game_card_fields_not_target_prediction'
                if isinstance(description, list) and all(isinstance(s, str) for s in description):
                    description = ' '.join(description)
                value['description'] = description if isinstance(description, str) else 'unknown'
                value['dynamic_values_unknown'] = bool(re.search(r'![^!]+!|%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]|\{\d+(?:[^}]*)\}', value['description']))
            for key, child in list(value.items()):
                if key=='catalog_ref':continue  # A reference is not another card/relic object.
                kind = 'powers' if key == 'powers' else 'relics' if key in ('relics', 'relic') else 'cards' if key in ('hand', 'deck', 'cards', 'card', 'draw_pile', 'discard_pile', 'exhaust_pile', 'selected_cards') else category
                visit(child, kind)
    visit(result)
    return result


def prepare_state(raw):
    return prepare_native_combat(raw)
