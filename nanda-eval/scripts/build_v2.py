"""Create a NEW v2 snapshot and blind review pack. Refuses to overwrite data."""
import argparse,csv,hashlib,json,random,sys
from collections import Counter
from pathlib import Path
EVAL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(EVAL/'src'))
from iam_benchmark.v2 import POLICY_V2,V2_TOOLS,V2World
from iam_benchmark.v2_cases import development_cases,evaluation_cases
from iam_benchmark.v2_oracle import score_v2

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default=str(EVAL/'data/v2'));p.add_argument('--review-output',default=str(EVAL/'review/v2'));a=p.parse_args()
 out=Path(a.output);review=Path(a.review_output)
 if out.exists() or review.exists():p.error('Use new directories; existing snapshots will not be overwritten.')
 suites={'development':development_cases(),'evaluation':evaluation_cases()}
 audit=[]
 for split,cases in suites.items():
  for c in cases:
   w=V2World(c['state'])
   for t in c['reference']:w.call(t['name'],t['arguments'])
   result=score_v2(c,w.state,w.trace,c['reference_final'])
   if result['safe_workflow_success']!=1:raise RuntimeError(f'Reference failed: {c["id"]} {result}')
   audit.append({'id':c['id'],'reference_pass':True})
 out.mkdir(parents=True);review.mkdir(parents=True)
 for split,cases in suites.items():(out/f'{split}.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases))
 manifest={'version':'iam-hard-v2.0','status':'provisional_evaluation_snapshot_pending_human_validation','provenance':'Synthetic authored causal templates; no authentic resolved IAM tickets; no baseline failure selection.',
  'original_data_modified':False,'policy_sha256':hashlib.sha256(POLICY_V2.encode()).hexdigest(),
  'tool_schema_sha256':hashlib.sha256(json.dumps(V2_TOOLS,sort_keys=True).encode()).hexdigest(),
  'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.jsonl'))},
  'suites':{split:{'cases':len(cases),'families':len({c['family_id'] for c in cases}),'categories':dict(Counter(c['category'] for c in cases)),'outcomes':dict(Counter(c['expected_final']['outcome'] for c in cases)),'cases_requiring_writes':sum(bool(c['allowed_writes']) for c in cases)} for split,cases in suites.items()},
  'reference_replays':audit,'human_review_completed':False,'three_repeat_final_evaluation_completed':False}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 rows=suites['evaluation'].copy();random.Random(731).shuffle(rows);keys={};inputs=[]
 for i,c in enumerate(rows,1):
  rid=f'R{i:03}';keys[rid]={'case_id':c['id'],'expected_final':c['expected_final'],'expected_business_state':c['expected_business_state']}
  inputs.append({'review_id':rid,'messages':c['messages'],'starting_state':c['state'],'tools':V2_TOOLS})
 (review/'blind_inputs.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in inputs))
 (review/'COORDINATOR_ONLY_key.json').write_text(json.dumps(keys,indent=2)+'\n')
 with (review/'labels.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['review_id','reviewer','outcome','reason_codes','missing_fields','required_effects','solvable','ambiguities']);w.writerows([[x['review_id'],'','','','','','',''] for x in inputs])
 (review/'README.md').write_text('''# Blind v2 review\n\nTwo humans should independently label `blind_inputs.jsonl` using only the supplied policy, request, tools, initial state and deterministic event schedule. Do not open `COORDINATOR_ONLY_key.json` or the evaluation targets before submitting labels. Events are reviewer-only: the candidate learns them through the documented conflict/timeout results.\n\nRecord disposition, blocking reasons, missing fields, required effects, solvability and ambiguities in a separate copy of `labels.csv`. Compare after both finish, adjudicate disagreements, and record agreement and changes in a new version. AI review is supplemental and is not human validation. Case count: 80.\n''')
 print(json.dumps(manifest['suites'],indent=2));print('All reference replays passed. Original datasets untouched.')
if __name__=='__main__':main()
