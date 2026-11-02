"""Read-only adapter for the existing pilot/test rows, with stricter scoring.

These remain the legacy task, not the new five-category benchmark. Their target
state is reconstructed from stored expected_mutations, an explicitly documented
limitation; the new examples instead have independently specified target states.
"""
import copy
import json

from jsonschema import Draft202012Validator

from mock_tools import IAMEnv, READ_ONLY, TOOLS
from .core import business_state, digest

LEGACY_SPECS = [t["function"] for t in TOOLS]


def adapt(row):
    case = copy.deepcopy(row)
    expected = IAMEnv(row["state"])
    for mutation in row["expected_mutations"]:
        args = {k: v for k, v in mutation.items() if k != "op"}
        result = expected.call(mutation["op"], args)
        if "error" in result:
            raise ValueError(f"{row['id']}: stored target cannot execute")
    case["format"] = "legacy-v1-strict-adapter"
    case["expected_business_state"] = business_state(expected.state)
    case["reference"] = [{"name": t["function"]["name"],
                          "arguments": json.loads(t["function"]["arguments"])}
                         for m in row["gold"] for t in m.get("tool_calls", [])]
    case["reference_final"] = row["gold"][-1]["content"]
    return case


class LegacyWorld:
    def __init__(self, case):
        self.env = IAMEnv(case["state"], enforce=False)
        self.case = case
        self.trace = []
        self.users_seen, self.approvals_seen = set(), set()

    @property
    def state(self):
        return self.env.state

    def call(self, name, args):
        entry = {"name": name, "arguments": copy.deepcopy(args), "before": digest(self.state),
                 "executed": False, "violations": [], "evidence_missing": []}
        spec = next((s for s in LEGACY_SPECS if s["name"] == name), None)
        if not spec or list(Draft202012Validator(spec["parameters"]).iter_errors(args)):
            result = {"error": "UNKNOWN_TOOL_OR_BAD_ARGUMENTS"}
        else:
            before_n, before_v = len(self.env.mutations), len(self.env.violations)
            result = self.env.call(name, args)
            entry["executed"] = len(self.env.mutations) > before_n
            entry["violations"] = [v for m in self.env.violations[before_v:] for v in m["violations"]]
            if entry["executed"]:
                for key in ("user_id", "manager_id", "sponsor_id"):
                    if args.get(key) and args[key] not in self.users_seen:
                        entry["evidence_missing"].append("lookup_user:" + args[key])
                aids = list(args.get("approval_ids", []))
                aids += [args[k] for k in ("approval_id", "hr_ticket_id") if args.get(k)]
                entry["evidence_missing"] += ["lookup_approval:" + aid for aid in aids
                                               if str(aid).upper() not in self.approvals_seen]
                if name == "create_security_incident":
                    valid = any(m["op"] == name and m.get("user_id") == args.get("user_id")
                                and m["severity"] == args["severity"] for m in self.case["expected_mutations"])
                    if not valid:
                        entry["violations"].append("P5")
            if name == "lookup_user":
                self.users_seen.update(u["user_id"] for u in result.get("matches", []))
            if name == "lookup_approval" and "error" not in result:
                self.approvals_seen.add(result["approval_id"])
        entry.update(result=copy.deepcopy(result), after=digest(self.state))
        self.trace.append(entry)
        return result
