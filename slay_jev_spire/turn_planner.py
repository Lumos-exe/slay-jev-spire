"""Conservative proof of a lethal basic-card sequence, not a general simulator."""
from itertools import combinations
from copy import deepcopy
from math import floor


def battle_projection(summary):
    def powers(values):
        return {p['id']: p['amount'] for p in values}
    return {'turn': summary.get('turn'), 'energy': summary.get('player', {}).get('energy'),
            'hp': summary.get('player', {}).get('current_hp'), 'block': summary.get('player', {}).get('block'),
            'player_powers': powers(summary.get('player', {}).get('powers', [])),
            'hand': sorted(c['uuid'] for c in summary.get('hand', [])),
            'hand_rules': {c['uuid']: {'id': c['id'], 'native': {k: c.get('native_values', {}).get(k) for k in ('cost_for_turn', 'base_damage', 'block', 'magic_number')}} for c in summary.get('hand', [])},
            'relics': [{'id': r['id'], 'counter': r.get('counter')} for r in summary.get('relics', [])],
            'enemies': [{'id': e['id'], 'hp': e['current_hp'], 'block': e['block'], 'powers': powers(e.get('powers', [])) if e['current_hp'] > 0 else {},
                         'intent': e.get('intent'), 'intent_damage': e.get('move_adjusted_damage'), 'intent_hits': e.get('move_hits')}
                        for e in summary.get('enemies', [])]}


def turn_plans(summary, actions):
    """Bounded basic-card turn search. Unknown rules return the atomic path."""
    enemies = summary.get('enemies', [])
    supported = {'Cultist', 'JawWorm', 'Looter', 'Mugger', 'AcidSlime_S', 'AcidSlime_M',
                 'SpikeSlime_S', 'SpikeSlime_M', 'FuzzyLouseNormal', 'FuzzyLouseDefensive'}
    live = [e for e in enemies if e['current_hp'] > 0]
    if not live or len(enemies) > 5 or any(e.get('id') not in supported for e in live):
        return None
    if any(e.get('is_gone') or e.get('half_dead') for e in live):
        return None
    player = summary['player']
    if any(p['id'] not in {'Strength', 'Dexterity', 'Weak', 'Frail', 'Vulnerable', 'Rage', 'Plated Armor'} for p in player.get('powers', [])):
        return None
    if any(p['id'] not in {'Strength', 'Weak', 'Vulnerable', 'Ritual', 'Thievery', 'Curl Up'} for e in live for p in e.get('powers', [])):
        return None
    if any(r.get('id') != 'Burning Blood' for r in summary.get('relics', [])):
        return None
    hand = summary.get('hand', [])
    if not hand or len(hand) > 10 or len({c['uuid'] for c in hand}) != len(hand):
        return None
    if any(c['id'] not in {'Strike_R', 'Defend_R', 'Bash', 'Rage'} or c.get('exhausts') or c.get('ethereal') for c in hand):
        return None
    incoming = {}
    for enemy in live:
        intent = enemy['intent']
        if intent.startswith('ATTACK'):
            damage, hits = enemy.get('move_adjusted_damage'), enemy.get('move_hits')
            if type(damage) is not int or damage < 0 or type(hits) is not int or hits < 1:
                return None
            incoming[enemy['target_index']] = damage * hits
        elif intent in {'BUFF', 'DEFEND', 'DEFEND_BUFF', 'SLEEP', 'DEBUFF', 'STRONG_DEBUFF', 'ESCAPE'}:
            incoming[enemy['target_index']] = 0
        else:
            return None
    current = battle_projection(summary)
    pp = current['player_powers']
    strength = pp.get('Strength', 0)
    weak = 0.75 if pp.get('Weak', 0) > 0 else 1
    usable = {}
    for card in hand:
        native = card.get('native_values', {})
        if native.get('source') != 'game_card_fields' or type(native.get('cost_for_turn')) is not int or native['cost_for_turn'] < 0:
            return None
        if card['id'] == 'Defend_R':
            if type(native.get('block')) is not int or native['block'] < 0:
                return None
        elif card['id'] == 'Rage':
            if type(native.get('magic_number')) is not int or native['magic_number'] < 0:
                return None
        else:
            if type(native.get('base_damage')) is not int or native['base_damage'] < 0:
                return None
            for enemy in live:
                preview = next((p for p in card.get('target_damage_previews', []) if p.get('target_index') == enemy['target_index'] and p.get('source') == 'game_calculateCardDamage'), None)
                expected = floor(max(0, native['base_damage'] + strength) * weak * (1.5 if current['enemies'][enemy['target_index']]['powers'].get('Vulnerable', 0) > 0 else 1))
                if not preview or preview.get('damage_before_block') != expected:
                    return None
            if card['id'] == 'Bash' and (type(native.get('magic_number')) is not int or native['magic_number'] < 0):
                return None
        if card['is_playable']:
            usable[card['uuid']] = card
    if not any(a['command'] == 'END' for a in actions):
        return None
    terminal = []
    visited = set()
    nodes = 0

    def search(state, steps):
        nonlocal nodes
        nodes += 1
        if nodes > 2000:
            return
        key = repr(state)
        if key in visited:
            return
        visited.add(key)
        won = all(e['hp'] <= 0 for e in state['enemies'])
        ending = steps if won else steps + [{'kind': 'end', 'expected_before': deepcopy(state)}]
        hp = [max(0, e['hp']) for e in state['enemies']]
        danger = sum(incoming.get(i, 0) for i, e in enumerate(state['enemies']) if e['hp'] > 0)
        terminal.append({'steps': ending, 'vulnerability': tuple(e['powers'].get('Vulnerable', 0) for e in state['enemies']),
            'outcome': {'enemy_hp': sum(hp), 'enemy_hp_by_target': hp,
            'incoming_hp_loss': 0 if won else max(0, danger - state['block'] - max(0, pp.get('Plated Armor', 0))),
            'remaining_energy': state['energy'], 'block': state['block'], 'combat_won': won}})
        if won:
            return
        for uuid in state['hand']:
            card = usable.get(uuid)
            if not card:
                continue
            native = card['native_values']; cost = native['cost_for_turn']
            if cost > state['energy']:
                continue
            targets = [i for i, e in enumerate(state['enemies']) if e['hp'] > 0] if card['has_target'] else [None]
            for index in targets:
                after = deepcopy(state); after['energy'] -= cost; after['hand'].remove(uuid); after['hand_rules'].pop(uuid)
                if card['id'] == 'Defend_R':
                    after['block'] += native['block']
                elif card['id'] == 'Rage':
                    after['player_powers']['Rage'] = after['player_powers'].get('Rage', 0) + native['magic_number']
                else:
                    target = after['enemies'][index]
                    after['block'] += max(0, after['player_powers'].get('Rage', 0))
                    damage = floor(max(0, native['base_damage'] + strength) * weak * (1.5 if target['powers'].get('Vulnerable', 0) > 0 else 1))
                    absorbed = min(target['block'], damage); target['block'] -= absorbed
                    hp_loss = damage - absorbed; target['hp'] = max(0, target['hp'] - hp_loss)
                    if target['hp'] <= 0:
                        target['powers'] = {}
                    else:
                        if hp_loss > 0:
                            target['block'] += target['powers'].pop('Curl Up', 0)
                        if card['id'] == 'Bash':
                            target['powers']['Vulnerable'] = target['powers'].get('Vulnerable', 0) + native['magic_number']
                step = {'kind': 'play', 'card_uuid': uuid, 'target_index': index,
                        'expected_before': deepcopy(state)}
                search(after, steps + [step])

    search(current, [])
    # Discard plans worse in both damage and immediate health loss. Identical
    # outcomes keep the shorter sequence; retain real offense/defense tradeoffs.
    terminal.sort(key=lambda p: len(p['steps']))
    unique = {}
    for p in terminal:
        o = p['outcome']; key = (tuple(o['enemy_hp_by_target']), o['incoming_hp_loss'], p['vulnerability'])
        unique.setdefault(key, p)
    frontier = []
    for key, plan in unique.items():
        if any(all(a <= b for a, b in zip(other[0], key[0])) and other[1] <= key[1]
               and all(a >= b for a, b in zip(other[2], key[2])) and other != key for other in unique):
            continue
        sequence = ['END' if step['kind'] == 'end' else f"{usable[step['card_uuid']]['id']}({step['card_uuid']})" for step in plan['steps']]
        frontier.append({'id': f'turn_plan_{len(frontier)}', 'kind': 'turn_plan', 'command': 'PLAN',
            'hand_index': None, 'card_uuid': None, 'target_index': None, **plan,
            'description': f"Whole turn: {' -> '.join(sequence)}; verified basic-card outcome {plan['outcome']}. Future draw order unknown."})
    return frontier or None


def bind_plan_step(step, summary, actions):
    if battle_projection(summary) != step['expected_before']:
        return None
    return next((a for a in actions if a.get('kind') == step['kind']
                 and (step['kind'] == 'end' or (a.get('card_uuid') == step['card_uuid'] and a.get('target_index') == step['target_index']))), None)


def proven_lethal_plan(summary, actions):
    enemies = summary.get('enemies', [])
    if len(enemies) != 1:
        return None
    enemy = enemies[0]
    # Only the audited Cultist transition is supported until other creatures'
    # damage/death callbacks are verified; a missing power list is not proof.
    if enemy.get('id') != 'Cultist':
        return None
    if enemy.get('is_gone') or enemy.get('half_dead') or enemy.get('current_hp', 0) <= 0:
        return None
    harmless_enemy = {'Strength', 'Weak', 'Frail', 'Vulnerable', 'Ritual'}
    harmless_player = {'Strength', 'Dexterity', 'Weak', 'Frail', 'Vulnerable'}
    if any(p.get('id') not in harmless_enemy for p in enemy.get('powers', [])):
        return None
    if any(p.get('id') not in harmless_player for p in summary.get('player', {}).get('powers', [])):
        return None
    if any(r.get('id') != 'Burning Blood' for r in summary.get('relics', [])):
        return None
    hand = summary.get('hand', [])
    if len({c.get('uuid') for c in hand}) != len(hand):
        return None
    if len(hand) > 10 or any(c.get('id') not in {'Strike_R', 'Defend_R', 'Bash'} for c in hand):
        return None
    energy = summary.get('player', {}).get('energy', 0)
    candidates = []
    for card in hand:
        if card.get('id') not in {'Strike_R', 'Bash'} or not card.get('is_playable'):
            continue
        action = next((a for a in actions if a.get('kind') == 'play'
                       and a.get('card_uuid') == card.get('uuid')
                       and a.get('target_index') == enemy.get('target_index')), None)
        native = card.get('native_values', {})
        cost = native.get('cost_for_turn')
        preview = next((p for p in card.get('target_damage_previews', [])
                        if p.get('target_index') == enemy.get('target_index')
                        and p.get('source') == 'game_calculateCardDamage'), None)
        damage = preview.get('damage_before_block') if preview else None
        if action and native.get('source') == 'game_card_fields' and type(cost) is int and cost >= 0 and type(damage) is int and damage > 0:
            candidates.append((action, cost, damage))
    # Current previews already include current Weak/Strength/Vulnerable. Bash may
    # increase later damage; ignoring that increase is a conservative lower bound.
    required = enemy['current_hp'] + enemy['block']
    for count in range(1, len(candidates) + 1):
        winning = [group for group in combinations(candidates, count)
                   if sum(x[1] for x in group) <= energy and sum(x[2] for x in group) >= required]
        if winning:
            group = min(winning, key=lambda group: sum(x[1] for x in group))
            return [x[0] for x in group]
    return None
