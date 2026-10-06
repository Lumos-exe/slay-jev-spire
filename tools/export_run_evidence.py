"""Export one run's existing records without loading the full live log."""
import argparse
import gzip
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run_id')
parser.add_argument('output', type=Path)
parser.add_argument('--step', action='append', type=int)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
identifier = args.run_id.encode()
count = 0
args.output.parent.mkdir(parents=True, exist_ok=True)
with (root / 'logs/live/runs.jsonl').open('rb') as source, gzip.open(args.output, 'wb') as target:
    for line in source:
        if identifier not in line or not line.endswith(b'\n'):
            continue
        row = json.loads(line)
        if row.get('run_id') == args.run_id and (not args.step or row.get('step_id') in args.step):
            target.write(line)
            count += 1
print(json.dumps({'run_id': args.run_id, 'records': count, 'compressed_bytes': args.output.stat().st_size}))
