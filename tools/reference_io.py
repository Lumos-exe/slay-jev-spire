"""Read an external-model request or submit a model ID over the authorized SSH connection.

This is an operator transport/view utility. It never chooses an action, ranks
candidates, or changes the complete payload kept by the game controller.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess


REMOTE=r'''
import base64,json,time
from pathlib import Path
from slay_jev_spire.external_decision import submit,current_request
from slay_jev_spire.native_view import expand
args=json.loads(base64.b64decode('ARGS'))
directory=Path('logs/live/decisions')
if args['operation']=='submit':
    submit(directory,args['request_id'],args['choice'],args['model'],args['reason'])
    deadline=time.monotonic()+args['wait']
    while time.monotonic()<deadline:
        r=current_request(directory)
        if r and r['request_id']!=args['request_id']:break
        time.sleep(.1)
r=current_request(directory)
if r is None:
    print(json.dumps({'status':'no_request_yet'}))
else:
    p=r['payload'];s=p['state'];ref=s.get('reference_state',s)
    if args['full']:print(json.dumps(r,ensure_ascii=False))
    else:
        fields=args['fields'].split(',')
        view={k:expand(ref[k],ref) for k in fields if k in ref}
        view['deck_overview']=[{k:c.get(k) for k in ('uuid','id','name','cost','upgrades','description')}
                               for c in expand(ref.get('deck',[]),ref)]
        print(json.dumps(dict(request_id=r['request_id'],status=r['status'],payload_sha256=r['payload_sha256'],
            read_view_scope='Selected fields for inspection; --full reads the complete immutable request.',
            state=view,current_board=s.get('current_board'),question=p['question']),ensure_ascii=False))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('read','submit'))
    parser.add_argument('--host',default='17469@192.168.3.15')
    parser.add_argument('--stage',default=r'C:\Users\17469\MyFiles\workspace\slay_external_reference_09')
    parser.add_argument('--request-id')
    parser.add_argument('--choice')
    parser.add_argument('--model',default='codex-session')
    parser.add_argument('--reason')
    parser.add_argument('--full',action='store_true')
    parser.add_argument('--wait',type=float,default=15,help='Seconds to observe the next request after submission (0–30).')
    parser.add_argument('--fields',default='act,floor,current_hp,max_hp,gold,screen_type,screen_state,relics,potions,current_map_node,act_boss')
    args=parser.parse_args()
    if not 0<=args.wait<=30:parser.error('wait must be between 0 and 30 seconds')
    if args.operation=='submit' and not (args.request_id and args.choice):parser.error('submit requires request-id and choice')
    data=base64.b64encode(json.dumps(vars(args)).encode()).decode()
    code=REMOTE.replace('ARGS',data)
    # Send data and Python source over stdin. Nesting them in an encoded shell
    # command hits Windows cmd.exe's command-length limit for longer reasons.
    stage=args.stage.replace("'","''")
    powershell=("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';Set-Location '"+stage+
                "'; & .\\.venv\\Scripts\\python.exe -X utf8 -c \"import sys;exec(sys.stdin.read())\"; exit $LASTEXITCODE")
    encoded=base64.b64encode(powershell.encode('utf-16le')).decode()
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/id_ed25519'),'-o','HostKeyAlias=192.168.3.13',
        '-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',args.host,
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand '+encoded],
        input=code,text=True,encoding='utf-8')
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
