"""Submit an external model's exact choice; never accepts game commands."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.external_decision import submit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'logs/live/decisions')
    parser.add_argument('--request-id',required=True)
    parser.add_argument('--choice',required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--reason')
    args=parser.parse_args()
    submit(args.directory,args.request_id,args.choice,args.model,args.reason)
    print('Submitted model choice for '+args.request_id)


if __name__=='__main__':main()
