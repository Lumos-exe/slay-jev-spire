"""An external model chooses an ID; the existing native executor owns actions."""
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import UUID,uuid4

from .selectors import SelectionError,choice_payload,comparison_limit,validate_choice


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def publish_status(directory,request_id,status):
    # Windows readers may deny deletion of an open file. Never replace a shared
    # mutable pointer: append a small event after publishing an immutable request.
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'events.jsonl').open('a',encoding='utf-8') as stream:
        # Leading newline also separates a partial tail left by a crashed writer.
        stream.write('\n'+json.dumps(dict(request_id=request_id,status=status))+'\n')


def current_request(directory):
    directory=Path(directory);path=directory/'events.jsonl'
    if not path.exists():return None
    latest=None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n') or not line.strip():continue
            try:event=json.loads(line)
            except ValueError:continue  # An incomplete writer tail is not a publication.
            if not isinstance(event,dict) or event.get('status') not in {'waiting','answered','cancelled'}:continue
            if event['status']=='waiting' or (latest and event.get('request_id')==latest['request_id']):latest=event
    if latest is None:return None
    identifier=latest['request_id']
    if str(UUID(identifier))!=identifier:raise ValueError('Invalid request index')
    request=json.loads((directory/'requests'/f'{identifier}.json').read_text(encoding='utf-8'))
    return dict(request,status=latest['status'])


class ExternalSelector:
    def __init__(self,output_dir,timeout=600):
        self.output_dir=Path(output_dir)
        self.directory=self.output_dir/'decisions'
        self.timeout=timeout

    def __call__(self,summary,actions):
        if not actions or len(actions)>comparison_limit(summary):
            raise SelectionError('Invalid external candidate count.',code='external_candidates')
        payload=choice_payload(summary,actions)
        digest=sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        request_id=str(uuid4())
        request=dict(request_id=request_id,payload_sha256=digest,payload=payload,
                     status='waiting',provider='external',candidate_count=len(actions))
        write_json(self.directory/'requests'/f'{request_id}.json',request)
        publish_status(self.directory,request_id,'waiting')
        started=time.monotonic();status='cancelled'
        try:
            response=self.directory/'responses'/f'{request_id}.json'
            while time.monotonic()-started<self.timeout:
                if (self.output_dir/'pause.flag').exists():
                    raise SelectionError('External decision paused.',code='external_paused')
                if response.exists():
                    try:reply=json.loads(response.read_text(encoding='utf-8'))
                    except (OSError,ValueError):
                        raise SelectionError('Invalid external decision JSON.',code='external_response') from None
                    if not isinstance(reply,dict) or reply.get('request_id')!=request_id or reply.get('payload_sha256')!=digest:
                        raise SelectionError('External response does not match this request.',code='external_identity')
                    selected=reply.get('choice')
                    if not isinstance(selected,str) or selected not in payload['question']['criteria']:
                        raise SelectionError('External response must choose an offered ID.',code='external_choice')
                    action=validate_choice(payload['choice_references'].get(selected,selected),actions)
                    if not isinstance(reply.get('model'),str) or not reply['model'].strip():
                        raise SelectionError('External model attribution is required.',code='external_model')
                    status='answered'
                    return dict(action=action,requested_model='external',returned_model=reply['model'],
                        confidence=None,model_requests=1,request_id=request_id,payload_sha256=digest,
                        latency_ms=round((time.monotonic()-started)*1000,2),
                        choice_references=payload['choice_references'],card_references=payload['card_references'],
                        model_input_format=payload['model_input_format'],external_reason=reply.get('reason'))
                time.sleep(.1)
            raise SelectionError('External decision timed out; no action chosen.',code='external_timeout')
        finally:
            publish_status(self.directory,request_id,status)


def submit(directory,request_id,choice,model,reason=None):
    """Bind a model's answer to the currently waiting, immutable request."""
    if str(UUID(request_id))!=request_id:raise ValueError('Non-canonical request ID')
    directory=Path(directory)
    current=current_request(directory)
    request=json.loads((directory/'requests'/f'{request_id}.json').read_text(encoding='utf-8'))
    if current is None or current.get('request_id')!=request_id or current.get('status')!='waiting' or current!=request:
        raise ValueError('This request is no longer waiting')
    if choice not in request['payload']['question']['criteria']:raise ValueError('Choice is not offered')
    if not isinstance(model,str) or not model.strip():raise ValueError('Model attribution is required')
    path=directory/'responses'/f'{request_id}.json'
    if path.exists():raise ValueError('Request already answered')
    write_json(path,dict(request_id=request_id,payload_sha256=request['payload_sha256'],
                        choice=choice,model=model,reason=reason))
