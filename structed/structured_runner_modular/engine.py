import copy
import json

from benchmark_runtime import (
    VirtualEnvRunner,
    build_tool_schemas,
    extract_message_text,
    post_openai_compatible_chat,
)
from config import STRUCTURED_SYSTEM_PROMPT
from observation import build_model_observation_view, build_observation_ir, summarize_facts
from policy import classify_tool_risk, execute_tool_with_policy
from prompting import build_initial_user_message


def collect_demo_observations(runner: VirtualEnvRunner) -> list[dict[str, object]]:
    spec_by_name = {
        spec["tool_name"]: spec for spec in runner.case["virtual_environment"]["tools"]
    }
    observations: list[dict[str, object]] = []

    for tool_name in runner.case["agent_input"]["available_tools"]:
        if classify_tool_risk(tool_name) != "read_only":
            continue

        spec = spec_by_name.get(tool_name)
        if not spec:
            continue
        when_called_with = spec.get("when_called_with")
        if not isinstance(when_called_with, dict):
            continue

        result = runner.execute_tool(tool_name, copy.deepcopy(when_called_with))
        observation_ir = build_observation_ir(tool_name, result)
        observations.append(
            {
                "tool_name": tool_name,
                "called_with": copy.deepcopy(when_called_with),
                "raw_result": copy.deepcopy(result),
                "observation_ir": observation_ir,
                "model_observation_view": build_model_observation_view(observation_ir),
            }
        )

    return observations


def run_structured_agent(
    runner: VirtualEnvRunner,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_steps: int,
    temperature: float,
) -> None:
    user_goal = runner.case["agent_input"]["user_instruction"]
    messages: list[dict[str, object]] = [
        {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
        {"role": "user", "content": build_initial_user_message(runner)},
    ]
    tools = build_tool_schemas(
        runner.case["agent_input"]["available_tools"],
        runner.case["virtual_environment"]["tools"],
    )
    observation_memory: list[dict[str, object]] = []

    for _ in range(max_steps):
        response = post_openai_compatible_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
        runner.record_api_usage(response.get("usage"))
        choices = response.get("choices", [])
        if not choices:
            raise RuntimeError("Model response did not include any choices.")

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                raw_args = function.get("arguments", "{}")
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw_arguments": raw_args}

                result, blocked = execute_tool_with_policy(
                    runner,
                    tool_name=tool_name,
                    args=args,
                    user_goal=user_goal,
                    observation_memory=observation_memory,
                )

                if blocked:
                    tool_content = {
                        "channel": "policy_gateway",
                        "status": "blocked",
                        **result,
                    }
                elif classify_tool_risk(tool_name) == "read_only":
                    observation_ir = build_observation_ir(tool_name, result)
                    observation_memory.append(observation_ir)
                    model_observation_view = build_model_observation_view(observation_ir)
                    tool_content = {
                        "channel": "tool_observation",
                        "observation": model_observation_view,
                    }
                else:
                    tool_content = {
                        "channel": "tool_result",
                        "trust_level": "runtime_ack",
                        "result": result,
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(tool_content, ensure_ascii=False),
                    }
                )
            continue

        runner.set_final_output(extract_message_text(message.get("content")))
        return

    runner.set_final_output(
        f"Agent stopped after reaching the max step limit ({max_steps})."
    )


def run_structured_demo_policy(runner: VirtualEnvRunner) -> None:
    observations = collect_demo_observations(runner)
    runner.set_final_output(
        summarize_facts([item["observation_ir"] for item in observations])
    )
