"""Candidate-side agentic execution layer for the 8-tool Acme IAM world (system C component).

Sits between the model and the tool API. It sees ONLY what the model sees: the public messages,
the tool schemas and tool results. It never imports the simulator, the generator or any expected
answer. Policy enforcement is NOT done here: it happens at the API boundary (the deterministic policy
harness, `check_policies` with enforce=True), where every blocked attempt is traced and counted.

What the layer does, each logged in `interventions`:
- evidence completion: before a write, lookup_user for every user/sponsor/manager id it names and
  lookup_approval for every approval id it cites, unless already observed in this episode;
- argument hygiene: approval ids upper-cased and trimmed, user ids trimmed;
- strict final JSON: the model's last reply is reduced to exactly one schema-valid decision object
  (prose and code fences removed). If no single valid object exists the reply is left unchanged.

Ported from the generic structure of Nanda's V2 guard (evidence -> validation -> policy -> recovery ->
JSON), minus the version/timeout/delegation mechanics that the 8-tool world does not have.
"""
from __future__ import annotations

import copy
import json
import re

from jsonschema import Draft202012Validator

READS = {"lookup_user", "lookup_approval"}
ID_KEYS = ("user_id", "sponsor_id", "manager_id")
APPROVAL_KEYS = ("approval_id", "hr_ticket_id")
FINAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["outcome", "reason_codes", "missing_fields", "message"],
    "properties": {
        "outcome": {"enum": ["act", "partial", "ask", "refuse", "out_of_scope"]},
        "reason_codes": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "missing_fields": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "message": {"type": "string", "minLength": 1},
    },
}


def normalize_final(text: str | None) -> str | None:
    """Return the single schema-valid decision object as compact JSON, or None if there isn't exactly one."""
    if not text:
        return None
    decoder = json.JSONDecoder()
    found, i = [], 0
    while True:
        i = text.find("{", i)
        if i == -1:
            break
        try:
            obj, length = decoder.raw_decode(text[i:])
        except ValueError:
            # tolerate an invalid backslash escape (e.g. a UNC path) inside the candidate object
            end = text.rfind("}")
            if end > i:
                try:
                    # consume escapes pairwise so a valid "\\" is kept and an invalid "\s" becomes "\\s"
                    repaired = re.sub(r"\\(.)", lambda m: m.group(0) if m.group(1) in '"\\/bfnrtu' else "\\\\" + m.group(1),
                                      text[i:end + 1], flags=re.S)
                    obj = json.loads(repaired, strict=False)
                    length = end + 1 - i
                except ValueError:
                    i += 1
                    continue
            else:
                i += 1
                continue
        if isinstance(obj, dict) and not list(Draft202012Validator(FINAL_SCHEMA).iter_errors(obj)):
            found.append(obj)
        i += max(length, 1)
    if len(found) != 1:
        return None
    return json.dumps(found[0], ensure_ascii=False)


class AgenticLayer:
    def __init__(self, call_tool, specs: list[dict]):
        self.call_tool = call_tool
        self.specs = {s["name"]: s for s in specs}
        self.users_seen: set[str] = set()
        self.approvals_seen: set[str] = set()
        self.interventions: list[dict] = []

    # ---- reads -------------------------------------------------------------------------------
    def _read(self, name, args, auto=False):
        result = self.call_tool(name, args)
        if name == "lookup_user":
            self.users_seen.update(m["user_id"] for m in result.get("matches", []))
        elif name == "lookup_approval" and "error" not in result:
            self.approvals_seen.add(str(result.get("approval_id", "")).upper())
        if auto:
            self.interventions.append({"kind": "evidence", "name": name, "arguments": args})
        return result

    # ---- writes ------------------------------------------------------------------------------
    def _hygiene(self, name, args):
        fixed = copy.deepcopy(args)
        if isinstance(fixed.get("approval_ids"), list):
            fixed["approval_ids"] = [str(a).strip().upper() for a in fixed["approval_ids"]]
        for k in APPROVAL_KEYS:
            if isinstance(fixed.get(k), str):
                fixed[k] = fixed[k].strip().upper()
        for k in ID_KEYS:
            if isinstance(fixed.get(k), str):
                fixed[k] = fixed[k].strip()
        if fixed != args:
            self.interventions.append({"kind": "argument_hygiene", "name": name, "proposed": args, "executed": fixed})
        return fixed

    def _complete_evidence(self, args):
        observations = []
        for k in ID_KEYS:
            uid = args.get(k)
            if uid and uid not in self.users_seen:
                observations.append(("lookup_user", {"query": uid}, self._read("lookup_user", {"query": uid}, auto=True)))
        aids = list(args.get("approval_ids") or []) + [args[k] for k in APPROVAL_KEYS if args.get(k)]
        for aid in aids:
            if str(aid).upper() not in self.approvals_seen:
                observations.append(("lookup_approval", {"approval_id": aid},
                                     self._read("lookup_approval", {"approval_id": aid}, auto=True)))
        return observations

    def call(self, name, arguments):
        spec = self.specs.get(name)
        if spec is None or not isinstance(arguments, dict) or list(Draft202012Validator(spec["parameters"]).iter_errors(arguments)):
            self.interventions.append({"kind": "schema_reject", "name": name, "arguments": arguments})
            return {"error": "GUARD_ARGUMENTS", "message": "Use the exact public tool schema."}
        if name in READS:
            return self._read(name, arguments)
        args = self._hygiene(name, arguments)
        observations = self._complete_evidence(args)
        result = self.call_tool(name, args)  # policy enforcement happens at the API boundary
        if observations:
            result = dict(result, guard_observations=[{"name": n, "arguments": a, "result": r} for n, a, r in observations])
        return result

    def finalize(self, text):
        norm = normalize_final(text)
        if norm is not None and norm != (text or "").strip():
            self.interventions.append({"kind": "final_json_normalized"})
        return norm if norm is not None else text
