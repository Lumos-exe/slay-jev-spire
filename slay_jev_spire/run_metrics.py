"""Request accounting based on recorded attempts, separate from game progress."""
import json


def run_metrics(rows):
    requests = {r['step_id']: r for r in rows if r.get('status') == 'request_started'}
    decisions = {r['step_id'] for r in rows if r.get('status') == 'decision' and r['step_id'] in requests}
    failed = {r['step_id'] for r in rows if r.get('status') == 'stopped' and r.get('reason') == 'selection_error'} & requests.keys()
    seen = set()
    duplicates = 0
    for r in requests.values():
        summary = {k: v for k, v in r.get('summary', {}).items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps([summary, r.get('candidates', [])], sort_keys=True, ensure_ascii=False)
        duplicates += key in seen
        seen.add(key)
    return {'api_requests': len(requests), 'valid_decisions': len(decisions),
            'confirmed_actions': len({r['step_id'] for r in rows if r.get('status') == 'action_confirmed'}),
            'duplicate_requests': duplicates, 'failed_requests': len(failed),
            'pending_requests': len(requests.keys() - decisions - failed)}
