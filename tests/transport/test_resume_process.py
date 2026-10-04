import copy
import io
import json
from collections import deque
from pathlib import Path

from slay_jev_spire.transport import communication_mod as transport
from slay_jev_spire.session import handle_resume_request
from slay_jev_spire.session import RunSession


class Input(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


def test_buffered_snapshots_cannot_repeat_unconfirmed_action(tmp_path, monkeypatch, capsys):
    raw = json.loads(Path('samples/communication_mod_rewards.json').read_text(encoding='utf-8'))
    after = copy.deepcopy(raw)
    after['game_state']['gold'] += 13
    after['game_state']['screen_state']['rewards'].pop(0)
    after['game_state']['choice_list'].pop(0)

    class Messages:
        def __init__(self):
            self.rows = deque([raw, raw, raw, raw, raw, after, None, raw, raw])
            self.count = 0
            self.drained = False

        def __iter__(self):
            while self.rows:
                if self.count == 2:
                    (tmp_path / 'pause.flag').write_text('pause')
                    (tmp_path / 'resume.flag').write_text('resume')
                self.count += 1
                row = self.rows.popleft()
                yield json.dumps(row) + '\n' if row is not None else None

        def discard_pending(self):
            assert list(self.rows) == [raw, raw]
            self.rows.clear()
            self.drained = True

    messages = Messages()
    monkeypatch.setattr(transport.sys, 'stdin', Input())
    monkeypatch.setattr(transport, '_input_messages', lambda: messages)
    monkeypatch.setattr(transport, 'handle_resume_request',
                        lambda old, budget: handle_resume_request(old, budget, session_factory=RunSession))
    assert transport.main(['--run', 'mock', '--max-decisions', '1', '--output-dir', str(tmp_path)]) == 0
    output = capsys.readouterr().out.splitlines()
    assert output.count('CHOOSE 0') == 1
    assert messages.drained
    rows = [json.loads(line) for line in (tmp_path / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len([r for r in rows if r['status'] == 'command_sent']) == 1
    assert len([r for r in rows if r['status'] == 'action_confirmed']) == 1
    assert rows[-1]['status'] == 'resumed' and rows[-1]['calls'] == 0
