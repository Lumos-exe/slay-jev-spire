from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

from slay_jev_spire.external_decision import ExternalSelector,submit,write_json,current_request
from slay_jev_spire.selectors import SelectionError,choice_payload
from tools.probe_native_choice_text import capture_body


def wait_request(directory):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        request=current_request(directory)
        if request is not None and request['status']=='waiting':return request
        time.sleep(.01)
    pytest.fail('External request was not published')


def options():
    return [{'id':'play','kind':'play','card_uuid':'x','command':'PLAY 1','description':'Play'},
            {'id':'end','kind':'end','command':'END','description':'End turn'}]


def test_external_and_jev_use_identical_state_and_choice_question():
    from slay_jev_spire.native_sequences import generate_plans
    from slay_jev_spire.shortlist import select
    cases=json.loads(Path('samples/shortlist_mechanical_recall.json').read_text())
    for case in cases:
        pool,search=generate_plans(case['summary'],case['actions']);actions,shortlist=select(pool)
        summary=dict(case['summary'],combat_choice_mode=search['policy'],candidate_generation=search,
                     shortlist=shortlist,_final_shortlist=True)
        payload=choice_payload(summary,actions);body=capture_body(summary,actions)
        # capture_body sets an experimental view flag; the flag is present in
        # reference state, and we compare the exact same input in both paths.
        payload=choice_payload(dict(summary,_combat_view='native'),actions)
        assert body['state']==payload['state']
        assert body['questions']['action']==payload['question']


def test_external_model_chooses_exact_existing_action_without_fallback(tmp_path):
    original=options();before=deepcopy(original);directory=tmp_path/'decisions'
    selector=ExternalSelector(tmp_path,timeout=3)
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(selector,{'screen_type':'NONE'},original)
        request=wait_request(directory)
        assert not future.done()
        submit(directory,request['request_id'],'end','reference-model','Explicit model choice')
        result=future.result(timeout=3)
    assert result['action'] is original[1] and original==before
    assert result['returned_model']=='reference-model'
    assert result['model_requests']==1 and result['confidence'] is None
    assert current_request(directory)['status']=='answered'
    with pytest.raises(ValueError):submit(directory,request['request_id'],'play','reference-model')


@pytest.mark.parametrize('mutation,code',[
    ({'payload_sha256':'wrong'},'external_identity'),
    ({'choice':'PLAY 1'},'external_choice'),
    ({'request_id':'wrong'},'external_identity'),
    ({'model':''},'external_model'),
])
def test_bad_external_response_never_turns_into_game_action(tmp_path,mutation,code):
    directory=tmp_path/'decisions'
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(ExternalSelector(tmp_path,timeout=3),{},options())
        request=wait_request(directory)
        reply=dict(request_id=request['request_id'],payload_sha256=request['payload_sha256'],choice='play',model='test')
        reply.update(mutation)
        write_json(directory/'responses'/f"{request['request_id']}.json",reply)
        with pytest.raises(SelectionError) as error:future.result(timeout=3)
    assert error.value.code==code
    assert current_request(directory)['status']=='cancelled'


def test_timeout_and_pause_have_no_automatic_choice(tmp_path):
    with pytest.raises(SelectionError) as error:ExternalSelector(tmp_path,timeout=0)({},options())
    assert error.value.code=='external_timeout'
    (tmp_path/'pause.flag').touch()
    with pytest.raises(SelectionError) as error:ExternalSelector(tmp_path)({},options())
    assert error.value.code=='external_paused'


def test_unknown_request_or_command_cannot_be_submitted(tmp_path):
    directory=tmp_path/'decisions'
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(ExternalSelector(tmp_path,timeout=3),{},options())
        request=wait_request(directory)
        with pytest.raises(ValueError):submit(directory,'../../bad','play','test')
        with pytest.raises(ValueError):submit(directory,request['request_id'],'PLAY 1','test')
        submit(directory,request['request_id'],'play','test')
        assert future.result(timeout=3)['action']['id']=='play'


def test_external_choice_uses_native_transaction_and_receipt(tmp_path,monkeypatch):
    from slay_jev_spire.session import RunSession
    from tests.test_transactions import raw,response
    monkeypatch.setattr('slay_jev_spire.session.load_jev_key',lambda:pytest.fail('External mode must not load Jev credentials'))
    session=RunSession(tmp_path,mode='external',max_actions=1,require_native_receipts=True,catalog={})
    value=raw();directory=tmp_path/'decisions'
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(session.receive,value)
        request=wait_request(directory);payload=request['payload']
        assert session.actions==0 and session.transaction is None
        assert request['candidate_count']<=32
        steps=payload['state']['reference_state']['turn_steps']
        selected=next(k for k,v in payload['question']['criteria'].items()
                      if len(v['sequence'])==1 and steps[v['sequence'][0]]['kind']=='end')
        submit(directory,request['request_id'],selected,'reference-model')
        assert future.result(timeout=3)==['STATE']
    command=session.receive(value)[0]
    assert command.startswith('JEV_ACTION epoch ')
    tx=session.transaction
    assert tx.data['command']=='END'
    session.command_sent(command)
    session.receive(response(tx))
    assert session.transaction is None and not (tmp_path/'pending-action.json').exists()
    rows=[json.loads(line) for line in (tmp_path/'runs.jsonl').read_text().splitlines()]
    confirmed=[r for r in rows if r['status']=='action_confirmed']
    assert len(confirmed)==1 and confirmed[0]['decision']['returned_model']=='reference-model'


def test_open_readers_never_require_replacing_a_published_file(tmp_path,monkeypatch):
    directory=tmp_path/'decisions';replace=Path.replace
    def windows_sharing_guard(path,target):
        if Path(target).exists():raise PermissionError('Windows reader denies replacement')
        return replace(path,target)
    monkeypatch.setattr(Path,'replace',windows_sharing_guard)
    selector=ExternalSelector(tmp_path,timeout=3)
    with ThreadPoolExecutor(1) as pool:
        for _ in range(4):
            future=pool.submit(selector,{},options())
            request=wait_request(directory)
            with (directory/'events.jsonl').open('rb'), (directory/'requests'/f"{request['request_id']}.json").open('rb'):
                submit(directory,request['request_id'],'play','test')
                assert future.result(timeout=3)['action']['id']=='play'
            assert current_request(directory)['status']=='answered'
    assert not (directory/'current.json').exists()


def test_partial_index_tail_does_not_hide_the_next_request(tmp_path):
    directory=tmp_path/'decisions';directory.mkdir()
    (directory/'events.jsonl').write_text('{"interrupted":',encoding='utf-8')
    assert current_request(directory) is None
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(ExternalSelector(tmp_path,timeout=3),{},options())
        request=wait_request(directory)
        submit(directory,request['request_id'],'end','test')
        assert future.result(timeout=3)['action']['id']=='end'
    assert current_request(directory)['status']=='answered'
