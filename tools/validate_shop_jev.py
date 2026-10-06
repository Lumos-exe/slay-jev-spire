"""Actual-model regression on saved shop inputs; never sends game commands."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from slay_jev_spire.config import load_jev_key
from slay_jev_spire.selectors import choose_jev
from slay_jev_spire.shopping import generate_shop_plans,purchase_evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-ref',help='Compare a saved Git selector version against the same fixture.')
    args=parser.parse_args()
    load_jev_key()
    cases=json.loads((ROOT/'samples/strategy_shop_cases.json').read_text(encoding='utf-8'))
    results=[]
    with tempfile.TemporaryDirectory() as directory:
        baseline=None
        if args.baseline_ref:
            source=subprocess.check_output(['git','show',args.baseline_ref+':slay_jev_spire/selectors.py'],cwd=ROOT)
            path=Path(directory)/'baseline_selectors.py';path.write_bytes(source)
            spec=importlib.util.spec_from_file_location('slay_jev_spire.baseline_selectors',path)
            baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        for case in cases:
            summary,actions=case['summary'],case['actions']
            row=dict(name=case['name'])
            if baseline:
                decision=baseline.choose_jev(summary,actions)
                row['baseline']=dict(action=purchase_evidence(decision['action']),
                    probabilities=decision['probabilities'],returned_model=decision['returned_model'])
            plans,stats=generate_shop_plans(summary,actions)
            decision=choose_jev(summary,plans)
            row['new']=dict(action=purchase_evidence(decision['action']),
                probabilities=decision['probabilities'],returned_model=decision['returned_model'],
                review=decision.get('shop_review'),usage=decision.get('usage'),search=stats)
            results.append(row)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(dict(scope='Saved-state model replay, no gameplay or win-rate claim.',cases=results),
                                              ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row,ensure_ascii=True),flush=True)


if __name__=='__main__': main()
