from copy import deepcopy
import pytest
from slay_jev_spire import selectors


@pytest.mark.parametrize('count', [255, 256, 287, 511])
def test_provider_limit_never_drops_or_sends_oversized_choice(monkeypatch, count):
    calls = []
    actions = [dict(id=str(i)) for i in range(count)]
    original = deepcopy(actions)
    def provider(summary, candidates):
        assert len(candidates) <= 255
        calls.append([a['id'] for a in candidates])
        return dict(action=candidates[-1], probabilities={a['id']:float(a == candidates[-1]) for a in candidates},
                    latency_ms=1, usage={'input_tokens':1, 'output_tokens':1}, model_requests=1)
    monkeypatch.setattr(selectors, '_request_with_transient_retry', provider)
    result = selectors._choose_with_context_limit({}, actions)
    assert actions == original
    assert set().union(*map(set, calls)) == {a['id'] for a in actions}
    assert result['model_requests'] == len(calls)
    if count > 255:
        assert result['context_comparison']['trigger'] == 'provider_choice_limit'
    else:
        assert len(calls) == 1


def test_provider_adapter_checks_limit_even_if_called_directly(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'unused-test-key')
    with pytest.raises(selectors.SelectionError) as caught:
        selectors._choose_jev_once({}, [{'id':str(i)} for i in range(256)])
    assert caught.value.code == 'provider_choice_limit'


@pytest.mark.parametrize('count', [32,33,171,1100])
def test_combat_comparison_limit_is_32_without_truncating_the_search_pool(monkeypatch,count):
    calls=[]
    actions=[{'id':str(i)} for i in range(count)]
    def provider(summary, candidates):
        assert len(candidates)<=32
        calls.append([a['id'] for a in candidates])
        return dict(action=candidates[-1],probabilities=None,model_requests=1,
                    usage={'input_tokens':1,'output_tokens':1})
    monkeypatch.setattr(selectors,'_request_with_transient_retry',provider)
    result=selectors._choose_with_context_limit({'player':{}},actions)
    assert len(actions)==count
    assert set().union(*map(set,calls))=={a['id'] for a in actions}
    assert result['model_requests']==len(calls)
    if count>32:
        assert result['context_comparison']['comparison_limit']==32


def test_direct_combat_provider_call_cannot_bypass_32_limit():
    with pytest.raises(selectors.SelectionError) as caught:
        selectors._choose_jev_once({'player':{}},[{'id':str(i)} for i in range(33)])
    assert caught.value.code=='combat_choice_limit'


def test_billing_error_is_reported_without_retry_or_single_step_fallback(monkeypatch):
    import httpx2
    import typesafe_sdk
    calls=[]
    original=typesafe_sdk.TypeSafeClient
    def handle(request):
        calls.append(1)
        return httpx2.Response(402,json={'detail':{'error_type':'billing_error','message':'No credits'}})
    monkeypatch.setenv('TYPESAFE_API_KEY','test-only-key')
    monkeypatch.setattr(typesafe_sdk,'TypeSafeClient',lambda **kwargs: original(**kwargs,transport=httpx2.MockTransport(handle)))
    with pytest.raises(selectors.SelectionError) as caught:
        selectors._choose_with_context_limit({},[dict(id='a',description='a'),dict(id='b',description='b')])
    assert caught.value.code=='billing_error' and caught.value.attempts==1
    assert len(calls)==1


def test_failed_final_comparison_counts_successful_group_requests(monkeypatch):
    def provider(summary, actions):
        if len(actions)==2:
            raise selectors.SelectionError('No credits',code='billing_error',attempts=1)
        return dict(action=actions[0],model_requests=1,probabilities=None,usage={'input_tokens':1,'output_tokens':1})
    monkeypatch.setattr(selectors,'_request_with_transient_retry',provider)
    with pytest.raises(selectors.SelectionError) as caught:
        selectors._choose_with_context_limit({},[{'id':str(i)} for i in range(510)])
    assert caught.value.code=='billing_error' and caught.value.attempts==3


def test_transport_records_actual_bodies_and_mapping_without_headers(tmp_path):
    import httpx2
    import json
    from slay_jev_spire.jev_provider import recording_transport
    def handler(request):
        assert request.headers['authorization'] == 'Bearer never-record-this'
        return httpx2.Response(400, json={'error':'invalid option'}, headers={'x-private':'never-record-that'})
    transport = recording_transport(tmp_path, 'run:decision', {'p0':'plan-abc'}, httpx2.MockTransport(handler))
    with httpx2.Client(transport=transport) as client:
        response = client.post('https://example.invalid', json={'state':'真实局面'},
                               headers={'authorization':'Bearer never-record-this'})
        assert response.status_code == 400 and response.json() == {'error':'invalid option'}
    files = list((tmp_path/'requests').rglob('*.jsonl'))
    assert len(files) == 1
    content = files[0].read_text(encoding='utf-8')
    assert 'never-record' not in content
    request, response = map(json.loads, content.splitlines())
    assert json.loads(request['body']) == {'state':'真实局面'}
    assert response['status_code'] == 400
    assert response['aliases'] == {'p0':'plan-abc'}
