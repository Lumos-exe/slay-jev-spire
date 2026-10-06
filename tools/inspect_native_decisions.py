"""Read a bounded live log tail and show native decision inputs, without scoring."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--last', type=int, default=8)
    args = parser.parse_args()
    path = ROOT / 'logs/live/runs.jsonl'
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 12_000_000))
        if stream.tell():
            stream.readline()
        rows = []
        for line in stream:
            if not line.endswith(b'\n'):
                break
            row = json.loads(line)
            if row['status'] == 'decision':
                rows.append(row)
    for row in rows[-args.last:]:
        raw = row.get('before', {}).get('game_state', {})
        combat = raw.get('combat_state', {})
        summary = row.get('summary', {})
        hand = summary.get('hand', combat.get('hand', []))
        enemies = summary.get('enemies', combat.get('monsters', []))
        result = dict(step=row['step_id'], floor=raw.get('floor'), turn=combat.get('turn'),
            player=summary.get('player', combat.get('player')),
            hand=[{k:c.get(k) for k in ('id','cost','uuid','native_values')} for c in hand],
            enemies=[{k:e.get(k) for k in ('id','current_hp','block','intent','move_adjusted_damage','move_hits')} for e in enemies],
            selected=row['decision']['action'], source=row.get('source'),
            latency_ms=row['decision'].get('latency_ms'))
        print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
