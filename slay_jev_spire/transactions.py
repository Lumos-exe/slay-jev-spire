"""Durable native action transactions; no inference from gameplay effects."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import time
from uuid import uuid4


class ProtocolError(ValueError):
    pass


def protocol(raw):
    value=raw.get('jev_protocol')
    if not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1: return None
    if (not isinstance(value.get('epoch'),str) or not re.fullmatch('[A-Za-z0-9-]{1,128}',value['epoch'])
            or type(value.get('revision')) is not int or value['revision']<0):
        raise ProtocolError('Malformed native protocol identity.')
    return value


def canonical(command):
    if not isinstance(command,str) or '\n' in command or '\r' in command:
        raise ProtocolError('Malformed action command.')
    return ' '.join(command.upper().split())


@dataclass(frozen=True)
class TransactionLimits:
    poll_seconds: float = 1.0
    resend_seconds: float = 5.0
    acceptance_seconds: float = 15.0
    settlement_seconds: float = 60.0
    max_sends: int = 2


class PendingAction:
    def __init__(self,path,data,*,clock=time.monotonic,limits=None):
        self.path=Path(path);self.data=data;self.clock=clock
        self.limits=limits or TransactionLimits()
        self.started=clock();self.last_poll=self.started
        self.accepted=data.get('stage')=='accepted'
        self.attempts=data.get('send_attempts',0)
        self.send_limit=self.attempts+self.limits.max_sends

    @classmethod
    def create(cls,path,raw,decision,context,**kwargs):
        p=protocol(raw)
        if p is None: raise ProtocolError('Native action transactions are unavailable.')
        data=dict(version=1,id=uuid4().hex,epoch=p['epoch'],revision=p['revision'],
                  command=canonical(decision['action']['command']),stage='prepared',send_attempts=0,
                  before=deepcopy(raw),decision=deepcopy(decision),context=deepcopy(context))
        result=cls(path,data,**kwargs);result.save()
        return result

    @classmethod
    def load(cls,path,**kwargs):
        path=Path(path)
        if not path.exists(): return None
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('version')!=1 or not all(k in data for k in ('id','epoch','revision','command','before','decision','context')):
            raise ProtocolError('Invalid pending action journal.')
        if (not isinstance(data['id'],str) or not data['id'].isalnum()
                or type(data['revision']) is not int or data['revision']<0):
            raise ProtocolError('Invalid pending action identity.')
        return cls(path,data,**kwargs)

    @property
    def wire(self):
        d=self.data
        return f"JEV_ACTION {d['epoch']} {d['id']} {d['revision']} {d['command']}"

    @property
    def query(self):
        return f"JEV_STATUS {self.data['epoch']} {self.data['id']}"

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(self.data,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                temporary.replace(self.path);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.02)

    def sent(self):
        self.attempts+=1;self.data['send_attempts']=self.attempts
        if not self.accepted:self.data['stage']='sent'
        self.save()

    def observe(self,raw):
        p=protocol(raw)
        if p is None: return 'missing_protocol',None
        if p['epoch']!=self.data['epoch']: return 'epoch_changed',None
        receipt=p.get('receipt')
        if not isinstance(receipt,dict) or receipt.get('id')!=self.data['id']: return 'waiting',None
        if (receipt.get('command')!=self.data['command']
                or receipt.get('expected_revision')!=self.data['revision']):
            return 'receipt_conflict',receipt
        status=receipt.get('status')
        if status=='settled':
            revision=receipt.get('settled_revision')
            if type(revision) is not int or not self.data['revision']<revision<=p['revision']:
                return 'receipt_conflict',receipt
            if raw.get('ready_for_command') is not True and not self.accepted:
                self.accepted=True;self.data['stage']='accepted';self.save()
            return ('settled' if raw.get('ready_for_command') is True else 'waiting'),receipt
        if status=='rejected': return 'rejected',receipt
        if status=='accepted':
            if not self.accepted:
                self.accepted=True;self.data['stage']='accepted';self.save()
            return 'waiting',receipt
        if status=='received': return 'waiting',receipt
        return 'receipt_conflict',receipt

    def timeout_reason(self):
        elapsed=self.clock()-self.started
        limit=self.limits.settlement_seconds if self.accepted else self.limits.acceptance_seconds
        if elapsed>=limit: return 'native_settlement_timeout' if self.accepted else 'native_acceptance_timeout'
        return None

    def restart_wait(self):
        """Explicit recovery grants a bounded new delivery cycle, same ID."""
        self.started=self.clock();self.last_poll=self.started-self.limits.poll_seconds
        self.send_limit=self.attempts+self.limits.max_sends

    def poll(self):
        now=self.clock()
        if now-self.last_poll<self.limits.poll_seconds:return None
        self.last_poll=now
        if not self.accepted and self.attempts<self.send_limit and now-self.started>=self.limits.resend_seconds:
            return self.wire
        return self.query

    def finish(self):
        # A matching native receipt is the source of truth. Deleting a completed
        # journal after logging is safe: replaying its ID only retrieves it.
        for attempt in range(8):
            try:
                self.path.unlink(missing_ok=True);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.02)
