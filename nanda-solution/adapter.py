"""Evaluator adapter. Privileged evaluator state stays outside the candidate guard."""
import asyncio
import copy
import json
import time

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, ChatMessageTool, get_model
from inspect_ai.solver import solver
from inspect_ai.tool import ToolInfo, ToolParams

from agent import ObservedGuard, OPERATING_GUIDE, normalize_final


class ToolBudgetExceeded(Exception):
    pass


@solver
def guarded_loop(max_turns=16, max_calls=32, seconds=180):
    async def solve(state, generate):
        from iam_benchmark.inspect_task import make_world
        from iam_benchmark.v2 import FORMAT, V2_TOOLS
        from iam_benchmark.core import FINAL_SCHEMA
        case = state.metadata["case"]
        if case["format"] != FORMAT:
            raise ValueError("This candidate is for Nanda Eval V2 only")
        world = make_world(case)
        def call_tool(name, arguments):
            if len(world.trace) >= max_calls:
                raise ToolBudgetExceeded()
            return copy.deepcopy(world.call(name, arguments))
        public_messages = [{"role": m.role, "content": m.content} for m in state.messages]
        guard = ObservedGuard(call_tool, V2_TOOLS, public_messages)
        state.messages.insert(1, ChatMessageSystem(content=OPERATING_GUIDE))
        infos = [ToolInfo(name=s["name"], description=s["description"],
                         parameters=ToolParams.model_validate(s["parameters"])) for s in V2_TOOLS]
        limit, error, final, turns, proposals = False, None, None, 0, 0
        started = time.monotonic()
        try:
            async with asyncio.timeout(seconds):
                for turns in range(1, max_turns + 1):
                    output = await get_model().generate(state.messages, tools=infos)
                    state.output = output
                    state.messages.append(output.message)
                    calls = output.message.tool_calls or []
                    if not calls:
                        final = normalize_final(output.completion, FINAL_SCHEMA)
                        if final is not None:
                            break
                        state.messages.append(ChatMessageUser(content="Return your decision as one JSON object with exactly "
                            "outcome, reason_codes, missing_fields, message. Do not change completed actions. No Markdown."))
                        continue
                    for call in calls:
                        proposals += 1
                        if proposals > max_calls:
                            raise ToolBudgetExceeded()
                        result = ({"error": "INVALID_TOOL_ARGUMENT_JSON"} if call.parse_error
                                  else guard.call(call.function, call.arguments))
                        state.messages.append(ChatMessageTool(tool_call_id=call.id, function=call.function,
                                                              content=json.dumps(result)))
                else:
                    limit = True
        except (TimeoutError, ToolBudgetExceeded):
            limit = True
        except Exception as exc:
            error = type(exc).__name__
        state.metadata["guard_interventions"] = guard.audit
        state.metadata["candidate_tool_proposals"] = proposals
        state.metadata["execution"] = {
            "state": copy.deepcopy(world.state), "trace": copy.deepcopy(world.trace),
            "final": final, "limit_exceeded": limit, "error": error,
            "turns": turns, "latency_seconds": time.monotonic() - started,
        }
        state.completed = True
        return state
    return solve
