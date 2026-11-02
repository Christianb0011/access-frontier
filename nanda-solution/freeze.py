"""Copy an existing V2 contract without generating or modifying benchmark cases."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--eval-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root, output = args.eval_root.resolve(), args.output.resolve()
    paths = list((root/'nanda-eval/src/iam_benchmark').glob('*.py'))
    paths += list((root/'nanda-eval/data/v2').glob('*'))
    paths += [root/p for p in ['nanda-eval/scripts/run_eval.py',
              'src/mock_tools.py','config/tools.json','config/policies.yaml','nanda-eval/requirements.txt']]
    paths = [p for p in paths if p.is_file()]
    for required in ['nanda-eval/src/iam_benchmark/v2.py','nanda-eval/data/v2/evaluation.jsonl',
                     'nanda-eval/data/v2/development.jsonl']:
        if root/required not in paths:
            ap.error('Missing V2 snapshot input: '+required)
    before = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.mkdir(parents=True, exist_ok=False)
    for p in paths:
        destination = output/p.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, destination)
    after = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    copied = {key:hashlib.sha256((output/key).read_bytes()).hexdigest() for key in before}
    if before != after or copied != before:
        raise RuntimeError('V2 changed while snapshotting. Do not evaluate this incomplete snapshot.')
    (output/'snapshot.json').write_text(json.dumps({'origin':str(root),'files':copied},indent=2)+'\n')
    print('Frozen unchanged V2 inputs:',output)


if __name__=='__main__':
    main()
