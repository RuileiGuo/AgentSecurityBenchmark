from benchmark_runtime import VirtualEnvRunner
from config import DEFAULT_APPROVED_PLAN, STRUCTURED_SYSTEM_PROMPT


def build_initial_user_message(runner: VirtualEnvRunner) -> str:
    available_tools = "\n".join(f"- {tool}" for tool in runner.case["agent_input"]["available_tools"])
    approved_plan_text = "\n".join(f"- {step}" for step in DEFAULT_APPROVED_PLAN)
    return (
        "### USER_GOAL:\n"
        f"{runner.case['agent_input']['user_instruction']}\n\n"
        "### AVAILABLE_TOOLS:\n"
        f"{available_tools}\n\n"
        "### APPROVED_PLAN:\n"
        f"{approved_plan_text}\n"
    )


def build_agent_view(runner: VirtualEnvRunner) -> dict[str, object]:
    return {
        "system_prompt": STRUCTURED_SYSTEM_PROMPT,
        "user_message": build_initial_user_message(runner),
        "available_tools": runner.case["agent_input"]["available_tools"],
    }
