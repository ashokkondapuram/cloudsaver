"""Offline CI entrypoint: exit 0 pass, 1 policy failure, 2 invalid input/configuration."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.plan_policy import InvalidPlan, MAX_BYTES, PlanPolicy, evaluate_plan, load_json


def read(path):
    with open(path,'rb') as handle:
        return load_json(handle.read(MAX_BYTES+1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    parser.add_argument('--policy')
    parser.add_argument('--infracost')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        policy = PlanPolicy.from_dict(read(args.policy)) if args.policy else PlanPolicy()
        result = evaluate_plan(read(args.plan),policy=policy,infracost=read(args.infracost) if args.infracost else None)
        status = 0 if result['decision']=='pass' else 1
    except (InvalidPlan,OSError,TypeError,KeyError,AttributeError,RecursionError):
        result, status = {'decision':'invalid','error':'Invalid, unsupported or unreadable plan/policy/cost input. No raw input was retained.'}, 2
    encoded = json.dumps(result,indent=2)+'\n'
    if args.output:
        try:
            Path(args.output).write_text(encoded)
        except OSError:
            print('{"decision":"invalid","error":"Policy report could not be written"}')
            return 2
    print(encoded,end='')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
