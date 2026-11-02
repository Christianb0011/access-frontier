"""Run the unchanged Nanda evaluator with a separate candidate solver.

Example: python nanda-solution/run.py --eval-root /path/to/v2/checkout \
  --candidate guarded --data /path/to/v2-development.jsonl \
  --model fireworks/accounts/fireworks/models/kimi-k3
All remaining options are passed to Nanda's run_eval.py unchanged.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--eval-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate", choices=["baseline", "guarded"], default="guarded")
    args, remaining = parser.parse_known_args()
    root = args.eval_root.resolve()
    if not (root / "nanda-eval/src/iam_benchmark/v2.py").exists():
        parser.error("V2 is unavailable here; pass --eval-root pointing to the V2 checkout")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    sys.path[:0] = [str(root / "nanda-eval/scripts"), str(root / "nanda-eval/src"), str(root / "src")]
    import run_eval
    from adapter import guarded_loop
    original = run_eval.iam_benchmark
    def configured(*pos, **kw):
        task = original(*pos, **kw)
        limits = task.metadata["limits"]
        if args.candidate == "guarded":
            task.solver = guarded_loop(limits["turns"], limits["tool_calls"], limits["seconds"])
        task.metadata["candidate"] = args.candidate
        task.metadata["solution_sources"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                              for p in sorted(Path(__file__).parent.glob("*.py"))}
        return task
    run_eval.iam_benchmark = configured
    original_eval = run_eval.inspect_eval
    def recorded_eval(*pos, **kw):
        out = Path(kw['log_dir'])
        selected = next((remaining[i+1] for i, arg in enumerate(remaining[:-1]) if arg == '--data'), None)
        tracked = list((root / 'nanda-eval/src/iam_benchmark').glob('*.py'))
        tracked += list(Path(__file__).parent.glob('*.py'))
        if selected:
            tracked.append(Path(selected).resolve())
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
        archive = out / 'source'
        archive.mkdir()
        for p in tracked:
            if p.suffix == '.py':
                folder = archive / ('solution' if p.parent == Path(__file__).parent else 'evaluator')
                folder.mkdir(exist_ok=True)
                (folder / p.name).write_bytes(p.read_bytes())
        try:
            return original_eval(*pos, **kw)
        finally:
            after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
            (out / 'source_integrity.json').write_text(json.dumps({
                'unchanged': before == after, 'before': before, 'after': after}, indent=2)+'\n')
    run_eval.inspect_eval = recorded_eval
    sys.argv = [str(root / "nanda-eval/scripts/run_eval.py"), *remaining]
    run_eval.main()


if __name__ == "__main__":
    main()
