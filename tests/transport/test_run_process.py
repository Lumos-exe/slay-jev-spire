import copy
import json
from pathlib import Path
import subprocess
import sys


def test_run_cli_reward_confirmation_and_mutual_exclusion(tmp_path):
    root=Path(__file__).resolve().parents[2]
    r=json.loads((root/'samples/communication_mod_rewards.json').read_text(encoding='utf-8'))
    after=copy.deepcopy(r); g=after['game_state']; g['gold']+=13
    g['choice_list'].pop(0); g['screen_state']['rewards'].pop(0)
    process=subprocess.run([sys.executable,'-X','utf8',str(root/'capture_game.py'),'--run','mock','--max-decisions','1','--output-dir',str(tmp_path)],input=''.join(json.dumps(x)+'\n' for x in [r,r,after]),text=True,capture_output=True,timeout=10)
    assert process.returncode==0,process.stderr
    assert process.stdout.splitlines()==['ready','STATE','STATE','CHOOSE 0','STATE']
    assert 'action_confirmed' in (tmp_path/'runs.jsonl').read_text(encoding='utf-8')
    process=subprocess.run([sys.executable,str(root/'capture_game.py'),'--run','mock','--combat','mock'],input='',text=True,capture_output=True,timeout=10)
    assert process.returncode!=0 and process.stdout==''


def test_run_cli_waits_at_menu_then_handles_reward(tmp_path):
    root = Path(__file__).resolve().parents[2]
    reward = json.loads((root / 'samples/communication_mod_rewards.json').read_text(encoding='utf-8'))
    menu = {'in_game': False, 'ready_for_command': True,
            'available_commands': ['start', 'key', 'click', 'state']}
    data = ''.join(json.dumps(row) + '\n' for row in [menu, menu, reward, reward])
    process = subprocess.run(
        [sys.executable, '-X', 'utf8', str(root / 'capture_game.py'),
         '--run', 'mock', '--max-decisions', '1', '--output-dir', str(tmp_path)],
        input=data, text=True, capture_output=True, encoding='utf-8', timeout=10)
    assert process.returncode == 0, process.stderr
    assert process.stdout.splitlines() == ['ready', 'STATE', 'STATE', 'CHOOSE 0']
    rows = [json.loads(line) for line in (tmp_path / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(row['status'] == 'waiting_for_run' for row in rows)
    assert not any(row['status'] == 'stopped' for row in rows)
