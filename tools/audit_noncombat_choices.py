"""Trace noncombat choices and their observed resource changes from live logs."""
import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-id', action='append', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
selected = set(args.run_id)
requests, decisions, counts = {}, [], Counter()

def option(action):
    return {'id': action['id'], 'kind': action.get('kind'),
            'description': action.get('card', {}).get('name') or action.get('option', {}).get('text') or action.get('description'),
            'item': action.get('item')}

with (root / 'logs/live/runs.jsonl').open(encoding='utf-8') as stream:
    for line in stream:
        if not any(identifier in line for identifier in selected):
            continue
        row = json.loads(line)
        if row.get('run_id') not in selected:
            continue
        game = row.get('before', {}).get('game_state', {})
        screen = game.get('screen_type')
        if screen not in {'EVENT', 'CHEST', 'SHOP_ROOM', 'SHOP_SCREEN', 'REST', 'CARD_REWARD', 'COMBAT_REWARD', 'BOSS_REWARD'}:
            continue
        key = (row['run_id'], row['step_id'])
        if row['status'] == 'request_started':
            requests[key] = [option(a) for a in row['candidates']]
        if row['status'] != 'action_confirmed':
            continue
        action = row['decision']['action']
        after = row['after'].get('game_state', {})
        counts[(row['run_id'], screen, action.get('kind'))] += 1
        decisions.append({'run_id': row['run_id'], 'step': row['step_id'], 'timestamp': row['timestamp'],
                          'floor': game.get('floor'), 'screen': screen,
                          'hp': game.get('current_hp'), 'max_hp': game.get('max_hp'), 'gold': game.get('gold'),
                          'chosen': option(action), 'options': requests.pop(key, []),
                          'gold_after': after.get('gold'), 'hp_after': after.get('current_hp'),
                          'deck_before': [(c['id'], c.get('upgrades', 0)) for c in game.get('deck', [])],
                          'deck_after': [(c['id'], c.get('upgrades', 0)) for c in after.get('deck', [])],
                          'relics_before': [r['id'] for r in game.get('relics', [])],
                          'relics_after': [r['id'] for r in after.get('relics', [])]})
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps({'decisions': decisions}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'confirmed_noncombat_choices': len(decisions), 'output': str(args.output)}))
