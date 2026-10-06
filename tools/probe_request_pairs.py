"""Replay predeclared HTTP-body pairs without executing game commands."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import sys
import time
from threading import Event

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from typesafe_sdk import TypeSafeClient, RetryPolicy, TypeSafeError
    from slay_jev_spire.config import load_jev_key
    from slay_jev_spire.jev_provider import recording_transport
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();directory=args.directory
    load_jev_key()
    jobs=json.loads((directory/'requests.json').read_text(encoding='utf-8'))
    random.Random(20261006).shuffle(jobs)
    billing_stop=Event()
    def run(job):
        started=time.monotonic();body=job['body'];row={k:job[k] for k in ('case','repeat','profile')}
        if billing_stop.is_set():return dict(row,status='skipped_after_billing_error')
        try:
            with TypeSafeClient(api_key=os.environ['TYPESAFE_API_KEY'],base_url='https://api.typesafe.ai',
                model=body.get('model','jev-latest'),retry=RetryPolicy(max_retries=0),timeout=30,
                transport=recording_transport(directory,
                    f'{job["case"]}:{job["profile"]}:{job["repeat"]}',job['aliases'])) as client:
                result=client.system_one(state=body['state'],questions=body['questions'])
            selected=result.answers['action'].choice
            row.update(status='ok',selected_id=job['aliases'].get(selected,selected),
                       model=result.model,usage=result.usage.model_dump())
        except TypeSafeError as error:
            status=getattr(error,'status_code',getattr(error,'status',None))
            row.update(status='provider_error',error_type=type(error).__name__,status_code=status)
            if status==402:billing_stop.set()
        row['elapsed_ms']=round((time.monotonic()-started)*1000,2)
        return row
    with (directory/'results.jsonl').open('x',encoding='utf-8') as out, ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(run,job) for job in jobs]):
            row=future.result();out.write(json.dumps(row)+'\n');out.flush();print(json.dumps(row),flush=True)


if __name__=='__main__':main()
