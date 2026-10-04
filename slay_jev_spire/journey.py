"""Pure native screen adapters; unknown card metadata remains data."""
from copy import deepcopy
import json
from .state import UnsupportedState, _require
from .native_combat import prepare_native_combat, potion_candidates
from .screens import SUPPORTED_SCREENS, prepare_screen

def _action(command: str, description: str, **metadata) -> dict:
    """Create a candidate carrying its original native index and evidence metadata."""
    return {'id': command.lower().replace(' ', '_'), 'command': command, 'description': description, 'hand_index': None, 'card_uuid': None, 'target_index': None, **metadata}

def prepare_journey(raw: dict) -> tuple[dict, list[dict]]:
    """Validate native indices and expose supported screens without guessing effects."""
    try:
        _require(raw['in_game'] is True and raw['ready_for_command'] is True, 'State is not ready.')
        game = raw['game_state']
        screen = game['screen_type']
        context = deepcopy({k: game.get(k) for k in ('seed', 'class', 'act', 'floor', 'current_hp', 'max_hp', 'gold', 'deck', 'relics', 'potions', 'map', 'act_boss', 'ascension_level')})
        context.update(screen_type=screen, screen_state=deepcopy(game.get('screen_state', {})))
        if game.get('room_phase') == 'COMBAT' and screen == 'NONE':
            summary, actions = prepare_native_combat(raw)
            summary.update(context)
            return (summary, actions)
        commands = raw['available_commands']
        choices = game.get('choice_list', [])
        state = game.get('screen_state', {})
        _require(isinstance(commands, list) and all((isinstance(c, str) for c in commands)), 'Invalid commands.')
        _require(isinstance(choices, list) and all((isinstance(c, str) for c in choices)), 'Invalid choices.')
        actions = []
        if screen == 'GAME_OVER':
            return (context, actions)
        if screen in SUPPORTED_SCREENS:
            actions = prepare_screen(raw)
        elif screen == 'COMBAT_REWARD':
            rewards = state['rewards']
            _require(len(rewards) == len(choices), 'Reward indices do not align.')
            if 'choose' in commands:
                for i, reward in enumerate(rewards):
                    kind = reward['reward_type']
                    _require(choices[i] == kind.lower(), 'Reward labels do not align.')
                    _require(kind in {'GOLD', 'CARD', 'POTION', 'RELIC', 'STOLEN_GOLD', 'SAPPHIRE_KEY', 'EMERALD_KEY'}, 'Unsupported reward type.')
                    if kind == 'POTION' and (not any((p.get('id') == 'Potion Slot' for p in game.get('potions', [])))):
                        continue
                    actions.append(_action(f'CHOOSE {i}', json.dumps(reward, ensure_ascii=False), kind='reward', choice_index=i, reward=deepcopy(reward)))
        elif screen == 'CARD_REWARD':
            cards = state['cards']
            bowl = state.get('bowl_available') is True
            _require(len(choices) == len(cards) + int(bowl), 'Card indices do not align.')
            if bowl:
                _require(choices[-1] == 'bowl', 'Bowl index does not align.')
            if 'choose' in commands:
                for i, card in enumerate(cards):
                    _require(choices[i] == card['name'].lower(), 'Card labels do not align.')
                    actions.append(_action(f'CHOOSE {i}', json.dumps(card, ensure_ascii=False), kind='card', card=deepcopy(card), choice_index=i))
                if bowl:
                    actions.append(_action(f'CHOOSE {len(cards)}', 'Singing Bowl: increase maximum HP by 2', kind='bowl'))
            if 'skip' in commands and state.get('skip_available') is True:
                actions.append(_action('SKIP', 'Skip card reward', kind='skip'))
        elif screen == 'MAP':
            if choices == ['boss']:
                _require(state.get('boss_available') is True, 'Boss availability does not align.')
                if 'choose' in commands:
                    actions.append(_action('CHOOSE 0', 'Enter boss room', kind='boss'))
            else:
                _require(state.get('boss_available') is not True, 'Boss availability does not align.')
                nodes = state['next_nodes']
                _require(len(nodes) == len(choices), 'Map indices do not align.')
                for i, node in enumerate(nodes):
                    _require(choices[i] == f"x={node['x']}", 'Map labels do not align.')
                    if 'choose' in commands:
                        actions.append(_action(f'CHOOSE {i}', json.dumps(node, ensure_ascii=False), kind='map', node=deepcopy(node)))
        elif screen != 'COMPLETE':
            raise UnsupportedState('Screen is not supported.')
        if screen in {'COMBAT_REWARD', 'COMPLETE'} and 'proceed' in commands:
            actions.append(_action('PROCEED', 'Proceed to map', kind='proceed'))
        if 'potion' in commands and screen not in {'GRID', 'HAND_SELECT'}:
            actions.extend(potion_candidates(raw))
        _require(bool(actions), 'No supported native actions.')
        return (context, actions)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise UnsupportedState('Malformed journey state.') from None
