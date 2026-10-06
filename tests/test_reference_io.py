import base64
import json
import re
from types import SimpleNamespace

import pytest

from tools import reference_io


def test_long_unicode_reason_uses_stdin_not_windows_command_line(monkeypatch):
    reason='连续拳：力量叠加。 $(never_execute) `literal` "quote"\n'*3000
    monkeypatch.setattr('sys.argv',['reference_io.py','submit','--request-id','request',
        '--choice','p1','--reason',reason])
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(reference_io.subprocess,'run',run)
    with pytest.raises(SystemExit) as result:reference_io.main()
    assert result.value.code==0
    command,kwargs=calls[0]
    assert len(command[-1])<2000
    loader=base64.b64decode(command[-1].split()[-1]).decode('utf-16le')
    assert 'sys.stdin.read()' in loader
    assert 'never_execute' not in loader
    encoded=re.search(r"args=json.loads\(base64.b64decode\('([^']+)'\)\)",kwargs['input']).group(1)
    assert json.loads(base64.b64decode(encoded))['reason']==reason
    assert kwargs['encoding']=='utf-8'
