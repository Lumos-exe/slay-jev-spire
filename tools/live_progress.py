"""Compact observation of the current live run, with an explicit tail window."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
raw=json.loads((root/'logs/live/latest_state.json').read_text(encoding='utf-8'))
game=raw.get('game_state',{});combat=game.get('combat_state',{})
path=root/'logs/live/runs.jsonl'
with path.open('rb') as stream:
    stream.seek(max(0,path.stat().st_size-4_000_000))
    if stream.tell():stream.readline()
    rows=[json.loads(line) for line in stream if line.strip()]
latest=rows[-1]
recent=[r for r in rows if r.get('run_id')==latest.get('run_id')]
events=[]
for row in recent:
    if row['status'] in {'stopped','complete','battle_complete','checkpoint_reached'}:
        events.append({k:row.get(k) for k in ('timestamp','status','step_id','reason','message','result')})
decisions=[r for r in recent if r['status']=='decision']
result=dict(run_id=latest.get('run_id'),latest_status=latest['status'],latest_timestamp=latest['timestamp'],
    floor=game.get('floor'),hp=game.get('current_hp'),max_hp=game.get('max_hp'),
    screen=game.get('screen_type'),turn=combat.get('turn'),calls=latest.get('calls'),actions=latest.get('actions'),
    enemies=[{k:e.get(k) for k in ('id','current_hp','intent','move_id')} for e in combat.get('monsters',[])],
    last_decisions=[dict(step=r['step_id'],source=r.get('source'),action=r['decision']['action'].get('id'),
                        input_tokens=r['decision'].get('usage',{}).get('input_tokens'),
                        grouped=bool(r['decision'].get('context_comparison')))
                    for r in decisions[-5:]],
    recent_events=events[-5:],tail_window_bytes=4_000_000)
print(json.dumps(result,ensure_ascii=True))
