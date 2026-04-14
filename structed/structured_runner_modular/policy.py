import copy
from typing import Any, Optional

from benchmark_runtime import VirtualEnvRunner
from config import HIGH_RISK_HINTS, MUTATING_HINTS, READ_ONLY_HINTS, TOOL_AUTH_KEYWORDS
from text_utils import iter_string_values, normalize_external_text


def classify_tool_risk(tool_name: str) -> str:
    lowered = tool_name.lower()
    if any(hint in lowered for hint in HIGH_RISK_HINTS):
        return "high"
    if any(hint in lowered for hint in MUTATING_HINTS):
        return "medium"
    if any(hint in lowered for hint in READ_ONLY_HINTS):
        return "read_only"
    return "medium"


def tool_category(tool_name: str) -> Optional[str]:
    lowered = tool_name.lower()
    for category in TOOL_AUTH_KEYWORDS:
        if category in lowered:
            return category
    if "email" in lowered or "send" in lowered or "forward" in lowered:
        return "send"
    if "transfer" in lowered or "withdraw" in lowered or "pay" in lowered:
        return "transfer"
    if "dispatch" in lowered:
        return "dispatch"
    if "update" in lowered or "modify" in lowered or "edit" in lowered:
        return "update"
    if "delete" in lowered or "remove" in lowered or "drop" in lowered:
        return "delete"
    if "disable" in lowered:
        return "disable"
    if "unlock" in lowered:
        return "unlock"
    if "move" in lowered:
        return "move"
    if "leave" in lowered:
        return "leave"
    if "post" in lowered or "tweet" in lowered or "publish" in lowered:
        return "post"
    return None


def goal_authorizes_tool(user_goal: str, tool_name: str) -> bool:
    risk_level = classify_tool_risk(tool_name)
    if risk_level == "read_only":
        return True

    lowered_goal = normalize_external_text(user_goal).lower()
    category = tool_category(tool_name)
    if not category:
        return False
    return any(keyword in lowered_goal for keyword in TOOL_AUTH_KEYWORDS[category])


def args_reference_untrusted_entities(args: dict[str, Any], observation_memory: list[dict[str, Any]]) -> bool:
    suspicious_entities = set()
    for observation in observation_memory:
        for item in observation.get("candidate_intents", []):
            for entity in item.get("entities", []):
                suspicious_entities.add(entity.lower())
    if not suspicious_entities:
        return False

    for value in iter_string_values(args):
        lowered = value.lower()
        if any(entity in lowered for entity in suspicious_entities):
            return True
    return False


def block_tool_call(
    runner: VirtualEnvRunner,
    *,
    tool_name: str,
    args: dict[str, Any],
    reason: str,
    risk_level: str,
) -> dict[str, Any]:
    result = {
        "error": "blocked_by_structured_policy",
        "tool_name": tool_name,
        "risk_level": risk_level,
        "reason": reason,
    }
    runner.tool_call_log.append(
        {
            "tool_name": tool_name,
            "arguments": copy.deepcopy(args),
            "result": copy.deepcopy(result),
            "matched": False,
            "blocked": True,
        }
    )
    return result


def execute_tool_with_policy(
    runner: VirtualEnvRunner,
    *,
    tool_name: str,
    args: dict[str, Any],
    user_goal: str,
    observation_memory: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    risk_level = classify_tool_risk(tool_name)
    if risk_level == "read_only":
        return runner.execute_tool(tool_name, args), False

    if not goal_authorizes_tool(user_goal, tool_name):
        return (
            block_tool_call(
                runner,
                tool_name=tool_name,
                args=args,
                reason="The user goal does not explicitly authorize this mutating action.",
                risk_level=risk_level,
            ),
            True,
        )

    if args_reference_untrusted_entities(args, observation_memory):
        return (
            block_tool_call(
                runner,
                tool_name=tool_name,
                args=args,
                reason="The requested tool arguments appear to be derived from untrusted observations.",
                risk_level=risk_level,
            ),
            True,
        )

    return runner.execute_tool(tool_name, args), False
