import copy
import json
from pathlib import Path
import subprocess
import sys


def test_combat_entry_loops_to_reward_then_only_captures(tmp_path):
    root=Path(__file__).resolve().parents[2]
    r=json.loads((root/'samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    r['game_state']['combat_state']['monsters'][0]['intent']='ATTACK'
    after=copy.deepcopy(r)
    after['game_state']['combat_state']['hand'].pop(0)
    rewards=copy.deepcopy(after)
    rewards['game_state']['room_phase']='COMPLETE'
    rewards['game_state']['screen_type']='COMBAT_REWARD'
    data=''.join(json.dumps(s)+'\n' for s in [r,r,r,after,after,rewards,r])
    p=subprocess.run([sys.executable,'-X','utf8',str(root/'capture_game.py'),
                      '--output-dir',str(tmp_path),'--combat','mock','--max-decisions','3'],
                     input=data,text=True,encoding="utf-8",capture_output=True,timeout=10)
    assert p.returncode==0,p.stderr
    assert [s for s in p.stdout.splitlines() if s.startswith('PLAY')] == ['PLAY 1 0','PLAY 1 0']
    rows=[json.loads(s) for s in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert rows[-1]['reason']=='battle_finished'
    assert rows[-1]['actions']==2


def test_combat_limit_is_validated_before_handshake(tmp_path):
    root=Path(__file__).resolve().parents[2]
    p=subprocess.run([sys.executable,'-X','utf8',str(root/'capture_game.py'),'--combat','mock','--max-decisions','0'],
                     input='',text=True,encoding="utf-8",capture_output=True,timeout=10)
    assert p.returncode!=0 and p.stdout==''
