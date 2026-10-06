"""Run several normal seeded games on the Windows desktop, keeping evidence.

Only closes a game after its recorded GAME_OVER. Technical stops leave the game
open for diagnosis; rerunning this tool continues the same managed trial.
"""
import argparse
import base64
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'logs/live'


def powershell(script):
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    return subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',encoded],
                          capture_output=True,text=True,encoding='utf-8',errors='replace')


def game_pids():
    result=powershell("Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('java.exe','javaw.exe') -and $_.CommandLine -match 'ModTheSpire.jar' } | Select-Object -ExpandProperty ProcessId")
    return [int(v) for v in result.stdout.split() if v.isdigit()]


def close_completed_game():
    pids=game_pids()
    if not pids:return
    raw=json.loads((LIVE/'latest_state.json').read_text(encoding='utf-8'))
    if raw.get('game_state',{}).get('screen_type')!='GAME_OVER':
        raise RuntimeError('Refusing to close an unfinished game.')
    if (LIVE/'pending-action.json').exists():
        raise RuntimeError('Refusing to close a game with an unreconciled native action.')
    for pid in pids:
        result=powershell(f"$p=Get-Process -Id {pid}; $null=$p.CloseMainWindow(); if (!$p.WaitForExit(5000)) {{ $p.Kill(); $p.WaitForExit() }}")
        if result.returncode:raise RuntimeError('Could not close completed game.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds',nargs='+',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--minutes-per-run',type=int,default=30)
    parser.add_argument('--faults',action='store_true',help='Opt in to receipt-loss/duplicate-send protocol tests.')
    args=parser.parse_args()
    if any(not re.fullmatch('[A-Za-z0-9]+',s) for s in args.seeds):raise ValueError('Invalid seed')
    directory=args.directory.resolve();directory.mkdir(parents=True,exist_ok=True)
    manifest_path=directory/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else dict(
        scope='Normal Ironclad A0 games, not normalized benchmarks.',seeds=args.seeds,trials=[])
    if manifest['seeds']!=args.seeds:raise ValueError('Seed list differs from the saved series.')
    def save():
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    log=LIVE/'runs.jsonl'
    for index,seed in enumerate(args.seeds):
        trial=next((t for t in manifest['trials'] if t['index']==index),None)
        if trial and trial['status']=='complete':continue
        if trial is None:
            close_completed_game()
            fault=('none','drop_settled','duplicate_action')[index%3] if args.faults else 'none'
            trial=dict(index=index,seed=seed,fault_injection=fault,status='starting',offset=log.stat().st_size if log.exists() else 0,
                       started_at=datetime.now(timezone.utc).isoformat(),technical_stops=[])
            manifest['trials'].append(trial);save()
            # Child games can inherit pipe handles. Waiting for communicate()
            # would then wait for the whole JVM, hiding real-time progress.
            launch_log=directory/f'launch-{index}.log'
            with launch_log.open('wb') as output:
                launch=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                    str(ROOT/'tools/launch_jev.ps1'),'-StartNew','-Seed',seed,'-MaxDecisions','1000','-FaultInjection',fault],
                    cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
            launch_deadline=time.monotonic()+60
            match=None
            while time.monotonic()<launch_deadline:
                match=re.search(r'Game process launched: (\d+)',launch_log.read_text(encoding='utf-8',errors='replace'))
                if match:break
                if launch.poll() is not None and launch.returncode!=0:break
                time.sleep(.25)
            if match is None:
                trial.update(status='launch_failed',exit_code=launch.poll());save();return 2
            trial['pid']=int(match[1])
            trial['status']='running';save()
        else:
            trial['status']='running';save()
        deadline=time.monotonic()+args.minutes_per_run*60
        last_event=time.monotonic()
        while time.monotonic()<deadline:
            if log.exists():
                with log.open('rb') as stream:
                    stream.seek(trial['offset'])
                    while True:
                        start=stream.tell();line=stream.readline()
                        if not line or not line.endswith(b'\n'):break
                        trial['offset']=stream.tell()
                        row=json.loads(line);last_event=time.monotonic()
                        if row.get('status') in {'created','run_bound'}:trial['run_id']=row['run_id']
                        if row.get('status')=='stopped':
                            trial['technical_stops'].append({k:row.get(k) for k in ('run_id','step_id','reason','message')})
                            trial['status']='needs_attention';save()
                            print(json.dumps(trial),flush=True);return 2
                        if row.get('status')=='complete':
                            game=row.get('after',{}).get('game_state',{})
                            trial.update(status='complete',result=row.get('result'),floor=game.get('floor'),
                                         finished_at=row['timestamp'],calls=row.get('calls'),actions=row.get('actions'))
                            shutil.copy2(LIVE/'latest_state.json',directory/f'final-state-{index}.json')
                            save();print(json.dumps(trial),flush=True);break
            if trial['status']=='complete':break
            if not game_pids():
                trial['status']='process_missing';save();return 2
            if time.monotonic()-last_event>120:
                trial['status']='no_progress';save();print(json.dumps(trial),flush=True);return 2
            time.sleep(1)
        if trial['status']!='complete':
            trial['status']='time_limit';save();return 2
    manifest['completed']=True;save();return 0


if __name__=='__main__':raise SystemExit(main())
