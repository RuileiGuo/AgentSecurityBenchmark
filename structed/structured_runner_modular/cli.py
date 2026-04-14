import argparse
import json
import os
from pathlib import Path

from benchmark_runtime import (
    ALIYUN_DASHSCOPE_BASE_URL,
    STRUCTED_OUTPUT_DIR,
    VirtualEnvRunner,
    sanitize_name,
    write_outputs,
)
from engine import collect_demo_observations, run_structured_agent, run_structured_demo_policy
from prompting import build_agent_view


def structed_output_dir() -> Path:
    return STRUCTED_OUTPUT_DIR


def write_structed_output(case_id: str, kind: str, payload: dict[str, object]) -> Path:
    output_dir = structed_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{case_id}__{kind}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Structured-query virtual-environment benchmark runner."
    )
    parser.add_argument(
        "--backend",
        choices=["demo", "openai_compatible", "aliyun_dashscope"],
        default="demo",
        help=(
            "Execution backend. 'demo' uses the modular structured safe path. "
            "Real API backends use the structured-query defense path."
        ),
    )
    parser.add_argument("--case", required=True, help="Path to a case JSON file.")
    parser.add_argument("--output-dir", help="Directory for env_final_state.json and score.json.")
    parser.add_argument(
        "--policy",
        choices=["safe", "attack"],
        default="safe",
        help="Kept for interface compatibility. The modular demo path always runs the safe policy.",
    )
    parser.add_argument("--model", help="Model name for real API backends.")
    parser.add_argument("--base-url", help="Base URL for OpenAI-compatible backends.")
    parser.add_argument(
        "--api-key-env",
        help=(
            "Environment variable containing the API key. Defaults to DASHSCOPE_API_KEY "
            "for aliyun_dashscope and OPENAI_API_KEY for openai_compatible."
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum LLM turns before forcing termination for real API backends.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for real API backends.",
    )
    parser.add_argument(
        "--print-agent-view",
        action="store_true",
        help="Print the structured prompt view shown to the agent.",
    )
    parser.add_argument(
        "--print-demo-observations",
        action="store_true",
        help=(
            "Print how read-only tool outputs are split into sanitized payload, facts, "
            "and candidate_intents for this case."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case_path = Path(args.case).resolve()
    runner = VirtualEnvRunner(case_path)

    if args.print_agent_view:
        payload = build_agent_view(runner)
        output_path = write_structed_output(runner.case["case_id"], "agent_view", payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nsaved_to: {output_path}")
        return

    if args.print_demo_observations:
        payload = {
            "case_id": runner.case["case_id"],
            "observations": collect_demo_observations(runner),
        }
        output_path = write_structed_output(
            runner.case["case_id"],
            "demo_observations",
            payload,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nsaved_to: {output_path}")
        return

    if args.backend == "demo":
        runner.configure_run(backend="demo", run_label="structured_modular__safe")
        run_structured_demo_policy(runner)
    else:
        if not args.model:
            raise ValueError("--model is required for real API backends.")

        if args.backend == "aliyun_dashscope":
            base_url = args.base_url or ALIYUN_DASHSCOPE_BASE_URL
            api_key_env = args.api_key_env or "DASHSCOPE_API_KEY"
        else:
            if not args.base_url:
                raise ValueError("--base-url is required for --backend openai_compatible.")
            base_url = args.base_url
            api_key_env = args.api_key_env or "OPENAI_API_KEY"

        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ValueError(f"Environment variable {api_key_env} is not set or is empty.")

        runner.configure_run(
            backend=args.backend,
            run_label=f"structured_modular__{args.backend}__{sanitize_name(args.model)}",
        )
        run_structured_agent(
            runner,
            base_url=base_url,
            api_key=api_key,
            model=args.model,
            max_steps=args.max_steps,
            temperature=args.temperature,
        )

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        output_dir = (
            STRUCTED_OUTPUT_DIR
            / runner.case["case_id"]
            / runner.run_label
        )

    final_state_path, score_path = write_outputs(runner, output_dir)
    print(f"case_id: {runner.case['case_id']}")
    print(f"run_label: {runner.run_label}")
    print(f"env_final_state: {final_state_path}")
    print(f"score: {score_path}")


if __name__ == "__main__":
    main()
