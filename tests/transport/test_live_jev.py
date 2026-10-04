import copy
import io
import json
from pathlib import Path

import httpx2
import pytest
import typesafe_sdk

from slay_jev_spire.transport.communication_mod import main


@pytest.mark.parametrize('scenario', ['unchanged', 'changed', 'api_error', 'bad_choice'])
def test_live_jev_uses_sdk_revalidates_state_and_never_falls_back(tmp_path, monkeypatch, scenario):
    raw = json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['combat_state']['monsters'][0]['intent'] = 'ATTACK'
    loading = copy.deepcopy(raw)
    loading['game_state']['combat_state']['monsters'][0]['intent'] = 'DEBUG'
    fresh = copy.deepcopy(raw)
    if scenario == 'changed':
        fresh['game_state']['combat_state']['player']['energy'] = 0
    lines = [loading, loading, raw, fresh, fresh]
    input_stream = io.StringIO(''.join(json.dumps(s) + '\n' for s in lines))
    input_stream.reconfigure = lambda **kwargs: None
    output = io.StringIO()
    monkeypatch.setattr('sys.stdin', input_stream)
    monkeypatch.setattr('sys.stdout', output)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-secret')
    original_client = typesafe_sdk.TypeSafeClient
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        assert requests[-1]['state']['enemies'][0]['intent'] == 'ATTACK'
        if scenario == 'api_error':
            return httpx2.Response(401, json={'message': 'test-only-secret'})
        return httpx2.Response(200, json={
            'model': 'jev-test', 'answers': {'action': {
                'type': 'choice', 'choice': 'invalid' if scenario == 'bad_choice' else 'play_2_0',
                'confidence': 0.8, 'probabilities': {'play_2_0': 0.8},
            }}, 'usage': {'input_tokens': 10, 'output_tokens': 2},
        })

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient',
                        lambda **kwargs: original_client(**kwargs, transport=httpx2.MockTransport(respond)))
    result = main(['--output-dir', str(tmp_path), '--execute-once', 'jev'])
    assert len(requests) == 1
    assert 'test-only-secret' not in output.getvalue()
    commands = output.getvalue().splitlines()
    if scenario == 'unchanged':
        assert result == 0
        assert commands == ['ready', 'STATE', 'STATE', 'STATE', 'STATE', 'PLAY 2 0']
        decision = json.loads((tmp_path / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()[0])
        assert decision['mode'] == 'jev'
        assert decision['decision']['returned_model'] == 'jev-test'
    elif scenario == 'changed':
        assert result == 0
        assert commands == ['ready', 'STATE', 'STATE', 'STATE', 'STATE']
        execution = json.loads((tmp_path / 'executions.jsonl').read_text(encoding='utf-8'))
        assert execution['status'] == 'cancelled_state_changed'
    else:
        assert result == 1
        assert commands == ['ready', 'STATE', 'STATE', 'STATE']
        assert not (tmp_path / 'decisions.jsonl').exists()
