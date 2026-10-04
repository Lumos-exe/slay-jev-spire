"""Paired first-floor evaluation. Run on the Windows interactive desktop.

Uses the real game for both versions; no combat is simulated for scoring.
The benchmark-only JVM flag normalizes the starting deck/HP/relic/potions.
"""
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(os.environ.get('STS_GAME_DIRECTORY', r'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire'))
WORKSHOP = GAME.parents[1] / 'workshop/content/646570'


def worker(args):
    source = Path(args.source)
    sys.path.insert(0, str(source)); os.chdir(source)
    from slay_jev_spire.transport import communication_mod as transport
    from slay_jev_spire.selectors import choose_mock
    original = transport.RunSession

    class EvaluationSession(original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            combat_selector = self.selector
            self.selector = lambda summary, actions: combat_selector(summary, actions) if 'player' in summary else choose_mock(summary, actions)
            self.eval_start = None
            self.eval_turn = 0

        def _receive_menu(self, raw):
            commands = super()._receive_menu(raw)
            if self.pending and self.pending[1]['action'].get('kind') == 'start':
                self.pending[1]['action']['command'] = 'START IRONCLAD 0 ' + args.seed
            return [('START IRONCLAD 0 ' + args.seed) if cmd.startswith('START ') else cmd for cmd in commands]

        def receive(self, raw):
            if self.stopped: return []
            game = raw.get('game_state', {}); combat = game.get('combat_state', {})
            if raw.get('ready_for_command') and game.get('room_phase') == 'COMBAT' and game.get('action_phase') == 'WAITING_ON_USER' and game.get('screen_type') == 'NONE':
                self.eval_turn = combat['turn']
                if self.eval_start is None:
                    expected = Counter({'Strike_R': 5, 'Defend_R': 4, 'Bash': 1})
                    valid = (combat.get('benchmark_normalized') is True and game.get('floor') == 1
                             and Counter(c['id'] for c in game['deck']) == expected
                             and combat['player']['current_hp'] == combat['player']['max_hp'] == 80
                             and [r['id'] for r in game['relics']] == ['Burning Blood']
                             and all(p['id'] == 'Potion Slot' for p in game['potions']))
                    if not valid: return self._stop('benchmark_initial_state_mismatch')
                    self.eval_start = dict(calls=self.calls, actions=self.actions,
                        hand=[c['id'] for c in combat['hand']],
                        monsters=[{k:m.get(k) for k in ('id','current_hp','block')} for m in combat['monsters']])
                    self._record('evaluation_started', before=raw, seed=args.seed, variant=args.variant, initial=self.eval_start)
            if self.eval_start and game.get('screen_type') in {'COMBAT_REWARD','GAME_OVER'}:
                won = game['screen_type'] == 'COMBAT_REWARD'
                result = dict(victory=won, start_hp=80, end_hp=game.get('current_hp',0) if won else 0,
                    turns=self.eval_turn, combat_calls=self.calls-self.eval_start['calls'],
                    combat_actions=self.actions-self.eval_start['actions'], seed=args.seed, variant=args.variant,
                    initial_hand=self.eval_start['hand'], initial_monsters=self.eval_start['monsters'])
                self._record('evaluation_complete', after=raw, result=result)
                return self._stop('battle_finished')
            return super().receive(raw)

    transport.RunSession = EvaluationSession
    return transport.main(['--run','jev','--start-new','--max-decisions','200',
                           '--input-encoding','gbk','--output-dir',args.output_dir])


def run(args):
    if os.name != 'nt': raise RuntimeError('Run this command in the Windows desktop session.')
    check = subprocess.check_output(['powershell.exe','-NoProfile','-Command',
        "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('java.exe','javaw.exe','SlayTheSpire.exe') -and $_.CommandLine -match 'SlayTheSpire|ModTheSpire' }).Count"],text=True)
    if int(check.strip()): raise RuntimeError('Close Slay the Spire before starting the benchmark.')
    sys.path.insert(0, str(ROOT))
    from slay_jev_spire.config import load_jev_key
    load_jev_key()
    count = args.count
    if not 1 <= count <= 20: raise ValueError('count must be 1–20')
    directory = ROOT / 'logs/benchmarks' / datetime.now().strftime('%Y%m%d-%H%M%S')
    directory.mkdir(parents=True)
    base = directory / 'baseline'; base.mkdir()
    archive = subprocess.check_output(['git','-C',str(ROOT),'archive','--format=zip',args.baseline_ref])
    with zipfile.ZipFile(io.BytesIO(archive)) as z: z.extractall(base)
    head = subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip()
    diff = subprocess.check_output(['git','-C',str(ROOT),'diff','--binary','HEAD'])
    seeds = [str(10001 + i) for i in range(count)]
    manifest = dict(schema_version=1, seeds=seeds, baseline_ref=args.baseline_ref,
                    new_base=head, new_diff_sha256=sha256(diff).hexdigest(), trials=[], completed=False)
    config = Path(os.environ['LOCALAPPDATA']) / 'ModTheSpire/CommunicationMod/config.properties'
    saved_config = config.read_bytes()
    backup = directory / 'save-backup'
    for name in ('saves','preferences','betaPreferences'):
        shutil.copytree(GAME/name, backup/name)
    pause = ROOT / 'logs/live/pause.flag'
    if pause.exists(): pause.unlink()

    def save():
        (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'directory':str(directory),'finished_trials':len(manifest['trials']),
                          'latest':manifest['trials'][-1] if manifest['trials'] else None}),flush=True)

    def restore():
        for name in ('saves','preferences','betaPreferences'):
            for file in (GAME/name).rglob('*'):
                if file.is_file() and not (backup/name/file.relative_to(GAME/name)).exists(): file.unlink()
            shutil.copytree(backup/name,GAME/name,dirs_exist_ok=True)

    save()
    try:
        for seed in seeds:
            for variant, source in [('baseline',base),('new',ROOT)]:
                if pause.exists(): return 2
                restore()
                trial = directory / f'{seed}-{variant}'; trial.mkdir()
                python = ROOT / '.venv/Scripts/python.exe'
                command = f'{python} -X utf8 -u {Path(__file__).resolve()} --worker --source {source} --seed {seed} --variant {variant} --output-dir {trial}'
                if ' ' in str(ROOT): raise ValueError('CommunicationMod requires a project path without spaces.')
                lines = [line for line in saved_config.decode('utf-8-sig').splitlines() if not line.strip().startswith(('command=', 'runAtGameStart='))]
                escaped = command.replace('\\','\\\\').replace(':','\\:')
                config.write_text('\n'.join(lines+['command='+escaped,'runAtGameStart=true'])+'\n',encoding='utf-8')
                result = dict(seed=seed,variant=variant,status='timeout')
                java = GAME/'jre/bin/java.exe'
                with (trial/'game.stdout.log').open('wb') as stdout, (trial/'game.stderr.log').open('wb') as stderr:
                    process = subprocess.Popen([str(java),'-Djev.benchmark=true','-jar',str(WORKSHOP/'1605060445/ModTheSpire.jar'),
                        '--mods','basemod,CommunicationMod,jevstate','--skip-intro'],cwd=GAME,stdout=stdout,stderr=stderr)
                    try:
                        deadline = time.monotonic() + 300
                        while time.monotonic() < deadline and process.poll() is None:
                            if pause.exists(): (trial/'pause.flag').write_text('pause')
                            log = trial/'runs.jsonl'
                            if log.exists():
                                try: rows = [json.loads(s) for s in log.read_text(encoding='utf-8').splitlines() if s.strip()]
                                except json.JSONDecodeError: rows=[]
                                complete = next((r for r in rows if r.get('status')=='evaluation_complete'),None)
                                stopped = next((r for r in reversed(rows) if r.get('status')=='stopped'),None)
                                if complete:
                                    result.update(status='complete',**complete['result']); break
                                if stopped:
                                    result.update(status='stopped',reason=stopped.get('reason')); break
                            time.sleep(1)
                        else:
                            if process.poll() is not None: result.update(status='game_exited',exit_code=process.returncode)
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try: process.wait(timeout=10)
                            except subprocess.TimeoutExpired: process.kill(); process.wait()
                manifest['trials'].append(result); save()
        manifest['completed'] = True
    finally:
        config.write_bytes(saved_config); restore()
        for variant in ('baseline','new'):
            trials=[r for r in manifest['trials'] if r['variant']==variant]
            complete=[r for r in trials if r['status']=='complete']
            manifest[variant]=dict(attempted=len(trials),completed=len(complete),wins=sum(r['victory'] for r in complete),
                win_rate=sum(r['victory'] for r in complete)/count,
                mean_remaining_hp=sum(r['end_hp'] for r in complete)/len(complete) if complete else None,
                mean_combat_calls=sum(r['combat_calls'] for r in complete)/len(complete) if complete else None)
        for seed in seeds:
            pair=[r for r in manifest['trials'] if r['seed']==seed and r['status']=='complete']
            if len(pair)==2 and any(pair[0][k]!=pair[1][k] for k in ('initial_hand','initial_monsters')):
                manifest.setdefault('initial_state_mismatches',[]).append(seed)
        manifest['acceptance_complete'] = (len(manifest['trials']) == count * 2 and
            all(r['status']=='complete' for r in manifest['trials']) and not manifest.get('initial_state_mismatches'))
        save()
    return 0


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--source'); parser.add_argument('--seed'); parser.add_argument('--variant')
    parser.add_argument('--output-dir'); parser.add_argument('--count',type=int,default=10)
    parser.add_argument('--baseline-ref',default='416c2224842750a8d4ec8c9d2ad2f74d469d74ab')
    options=parser.parse_args()
    raise SystemExit(worker(options) if options.worker else run(options))
