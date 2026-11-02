"""Compare complete, identical-contract runs; never silently remove failed cases."""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--eval-root', type=Path, required=True)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('solution', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    sys.path.insert(0,str(args.eval_root/'nanda-eval/src'))
    from iam_benchmark.report import paired_difference
    summaries = []
    for folder in (args.baseline,args.solution):
        for name in ('data_integrity.json','source_integrity.json'):
            if not json.loads((folder/name).read_text())['unchanged']:
                raise ValueError('Unstable comparison input: '+str(folder/name))
        summary = json.loads((folder/'summary.json').read_text())
        if summary['status'] != 'success':
            raise ValueError('Incomplete run: '+str(folder))
        summaries.append(summary)
    paired = paired_difference(*summaries)
    report = {'comparison':paired,'scope':'Provisional synthetic V2 evaluation; human review pending.',
              'systems':{}}
    for name,summary in zip(('baseline','solution'),summaries):
        report['systems'][name] = {k:summary[k] for k in ('model','attempts','families',
            'safe_workflow_success','per_category','diagnostic_totals','p50_latency_seconds',
            'all_observed_repeats_pass','tokens_by_model','cost_usd','task_metadata','records')}
    rendered=json.dumps(report,indent=2)+'\n'
    if args.output:
        args.output.write_text(rendered)
    print(json.dumps({'comparison':paired,'scores':{k:v['safe_workflow_success']
                     for k,v in report['systems'].items()}},indent=2))


if __name__=='__main__':
    main()
