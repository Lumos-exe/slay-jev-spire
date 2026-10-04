"""Observed local history and bounded repeat detection; no inferred game effects."""
from collections import Counter
from copy import deepcopy
import json


def gameplay_state(value):
    """Ignore card highlighting and fully gone monsters' delayed power cleanup."""
    if isinstance(value, list):
        return [gameplay_state(item) for item in value]
    if isinstance(value, dict):
        result = {k: gameplay_state(v) for k, v in value.items()}
        native = result.get('native_values')
        if isinstance(native, dict):
            for flag in ('damage_modified', 'block_modified', 'magic_number_modified'):
                native.pop(flag, None)
        combat = result.get('combat_state')
        if isinstance(combat, dict):
            for monster in combat.get('monsters', []):
                if (monster.get('current_hp') == 0 and monster.get('is_gone') is True
                        and monster.get('half_dead') is False):
                    monster.pop('powers', None)
        return result
    return value


class DecisionMemory:
    def __init__(self):
        self.declined = set()
        self.recent = []
        self.visits = Counter()
        self.repeated_requests = 0
        self.opened_reward = None

    @staticmethod
    def location(game):
        return (game.get('act'), game.get('floor'))

    def observe(self, before, after, decision):
        action = decision['action']
        game = before.get('game_state', {})
        kind = action.get('kind')
        if kind == 'reward' and action.get('reward', {}).get('reward_type') == 'CARD':
            # Multiple anonymous CARD entries cannot safely be distinguished after removal.
            count = sum(r.get('reward_type') == 'CARD' for r in game.get('screen_state', {}).get('rewards', []))
            self.opened_reward = (self.location(game), count == 1)
        if kind in {'skip', 'card', 'bowl'}:
            if kind == 'skip' and self.opened_reward == (self.location(game), True):
                self.declined.add(self.location(game))
            self.opened_reward = None
        self.recent.append({'floor': game.get('floor'), 'screen_type': game.get('screen_type'),
                            'command': action['command'], 'kind': kind})
        self.recent = self.recent[-8:]

    def filter(self, raw, actions):
        game = raw['game_state']
        if game.get('screen_type') != 'COMBAT_REWARD' or self.location(game) not in self.declined:
            return actions
        rewards = game.get('screen_state', {}).get('rewards', [])
        if sum(r.get('reward_type') == 'CARD' for r in rewards) != 1:
            return actions
        return [a for a in actions if not (a.get('kind') == 'reward' and a.get('reward', {}).get('reward_type') == 'CARD')]

    def visit(self, summary, actions):
        visible = {k: v for k, v in summary.items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps(gameplay_state([visible, actions]), sort_keys=True, ensure_ascii=False)
        self.visits[key] += 1
        if self.visits[key] > 1:
            self.repeated_requests += 1
        return self.visits[key] <= 2

    def context(self, summary, actions):
        return {'recent_actions': deepcopy(self.recent),
                'objective': 'Win the entire encounter while conserving health and consumables for the run. Compare offense, defense and setup over future turns, not only the next immediate hit.',
                'future_draw_order': 'unknown; draw-pile contents are available, but do not assume a favorable order',
                'declined_card_rewards': [list(x) for x in sorted(self.declined, key=str)],
                'remaining_energy': summary.get('player', {}).get('energy'),
                'playable_card_count': len({a.get('card_uuid') for a in actions if a.get('kind') == 'play'}),
                'enemy_intents': [{k: e.get(k) for k in ('name', 'intent', 'move_adjusted_damage', 'move_hits')}
                                  for e in summary.get('enemies', [])]}


def describe_candidates(summary, actions):
    """Expose available descriptions without resolving unknown dynamic templates."""
    actions = deepcopy(actions)
    cards = {c.get('card_uuid', c.get('uuid')): c for c in summary.get('hand', [])}
    for action in actions:
        card = cards.get(action.get('card_uuid')) if action.get('kind') == 'play' else action.get('card')
        if action.get('kind') == 'card':
            card = next((c for c in summary.get('screen_state', {}).get('cards', [])
                         if c.get('uuid', c.get('id')) == action['card'].get('uuid', action['card'].get('id'))), card)
        if card and card.get('description') and card['description'] != 'unknown':
            action['description'] += ' | Effect: ' + card['description']
            if card.get('dynamic_values_unknown'):
                action['description'] += ' (template values unknown; do not infer current numbers)'
        if card:
            preview = next((p for p in card.get('target_damage_previews', [])
                            if p.get('target_index') == action.get('target_index')
                            and p.get('source') == 'game_calculateCardDamage'
                            and type(p.get('damage_before_block')) is int and p['damage_before_block'] >= 0), None)
            if preview:
                action['damage_preview'] = deepcopy(preview)
                action['description'] += f" | Game target damage calculation before block: {preview['damage_before_block']}; not final HP loss or a full multi-hit simulation."
        if action['command'] == 'END':
            energy = summary.get('player', {}).get('energy')
            playable = len({a.get('card_uuid') for a in actions if a.get('kind') == 'play'})
            action['description'] += f'; remaining energy={energy}, playable cards={playable}. Consider unused attacks, setup and incoming damage; waiting may be appropriate for sleeping enemies.'
    return actions
