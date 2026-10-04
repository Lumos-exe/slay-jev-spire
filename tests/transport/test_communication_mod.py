import json
from pathlib import Path
import subprocess
import sys
import pytest
from threading import Timer


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows open-file replacement semantics')
@pytest.mark.parametrize('release_reader',[True,False])
def test_snapshot_reader_lock_retries_or_records_explicit_transport_stop(tmp_path,release_reader):
    latest=tmp_path/'latest_state.json'
    latest.write_text('{}',encoding='utf-8')
    reader=latest.open()
    process=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'capture_game.py'),
        '--output-dir',str(tmp_path),'--run','mock'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True,encoding='utf-8')
    timer=None
    try:
        assert process.stdout.readline()=='ready\n'
        assert process.stdout.readline()=='STATE\n'
        if release_reader:
            timer=Timer(0.06,reader.close);timer.start()
        raw={'in_game':False,'ready_for_command':True,'available_commands':['start','state']}
        _,error=process.communicate(json.dumps(raw)+'\n',timeout=10)
        if release_reader:
            assert process.returncode==0,error
            assert json.loads(latest.read_text(encoding='utf-8'))==raw
        else:
            assert process.returncode==1
            rows=[json.loads(s) for s in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
            assert rows[-1]['status']=='stopped' and rows[-1]['reason']=='transport_error'
            assert latest.read_text(encoding='utf-8')=='{}'
    finally:
        if timer: timer.join()
        reader.close()
        if process.poll() is None: process.kill();process.communicate()


def start_capture(tmp_path):
    return subprocess.Popen(
        [sys.executable, '-X', 'utf8', str(ROOT / 'capture_game.py'),
         '--output-dir', str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', cwd=tmp_path.parent,
    )


def test_handshake_flush_capture_multiple_states_and_clean_stdout(tmp_path):
    process = start_capture(tmp_path)
    try:
        assert process.stdout.readline() == 'ready\n'
        assert process.stdout.readline() == 'STATE\n'
        states = [
            {'in_game': False, 'ready_for_command': True, 'available_commands': ['start', 'state']},
            {'in_game': True, 'game_state': {'screen_type': 'MAP', 'label': '地图'}},
            {'error': 'Invalid command', 'ready_for_command': True},
        ]
        output, error = process.communicate(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in states), timeout=10)
        assert process.returncode == 0, error
        assert output == ''
        records = [json.loads(line) for line in (tmp_path / 'states.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [r['raw_state'] for r in records] == states
        assert all('timestamp' in r for r in records)
        assert json.loads((tmp_path / 'latest_state.json').read_text(encoding='utf-8')) == states[-1]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_invalid_input_stops_without_any_gameplay_command(tmp_path):
    process = start_capture(tmp_path)
    output, error = process.communicate('[]\n', timeout=10)
    assert process.returncode == 1
    assert output == 'ready\nSTATE\n'
    assert error
    assert (tmp_path / 'states.jsonl').read_text(encoding='utf-8') == ''


def test_unwritable_output_does_not_signal_ready(tmp_path):
    blocked = tmp_path / 'blocked'
    blocked.write_text('file', encoding='utf-8')
    process = start_capture(blocked)
    output, error = process.communicate('', timeout=10)
    assert process.returncode == 1
    assert output == ''
    assert error


def test_gbk_java_input_is_saved_as_utf8(tmp_path):
    raw = {'in_game': True, 'game_state': {'name': '铁甲战士', 'enemy': '邪教徒'}}
    process = subprocess.Popen(
        [sys.executable, '-X', 'utf8', str(ROOT / 'capture_game.py'),
         '--output-dir', str(tmp_path), '--input-encoding', 'gbk'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    output, error = process.communicate((json.dumps(raw, ensure_ascii=False) + '\n').encode('gbk'), timeout=10)
    assert process.returncode == 0, error
    assert output.splitlines() == [b'ready', b'STATE']
    assert json.loads((tmp_path / 'latest_state.json').read_text(encoding='utf-8')) == raw


def test_execute_once_sends_one_generated_command_and_records_reply(tmp_path):
    raw = json.loads((ROOT / 'samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    process = subprocess.Popen(
        [sys.executable, '-X', 'utf8', str(ROOT / 'capture_game.py'),
         '--output-dir', str(tmp_path), '--execute-once', 'mock'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8',
    )
    output, error = process.communicate(json.dumps(raw) + '\n' + json.dumps(raw) + '\n', timeout=10)
    assert process.returncode == 0, error
    assert output.splitlines() == ['ready', 'STATE', 'PLAY 1 0']
    decisions = [json.loads(s) for s in (tmp_path / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(decisions) == 1
    assert decisions[0]['decision']['action']['command'] == 'PLAY 1 0'
    execution = [json.loads(s) for s in (tmp_path / 'executions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [s['status'] for s in execution] == ['sent', 'response_received']
    assert execution[-1]['raw_state'] == raw


def test_execute_once_rejects_unsupported_state_without_command(tmp_path):
    raw = json.loads((ROOT / 'samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    raw['game_state']['class'] = 'THE_SILENT'
    process = subprocess.Popen(
        [sys.executable, '-X', 'utf8', str(ROOT / 'capture_game.py'),
         '--output-dir', str(tmp_path), '--execute-once', 'mock'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8',
    )
    output, error = process.communicate(json.dumps(raw) + '\n', timeout=10)
    assert process.returncode == 0, error
    assert output.splitlines() == ['ready', 'STATE']
    assert not (tmp_path / 'decisions.jsonl').exists()
