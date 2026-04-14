import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


def sanitize_name(value: str) -> str:
    cleaned = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_", "."}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_") or "run"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the structured virtual-environment benchmark suite."
    )
    parser.add_argument(
        "--backend",
        choices=["demo", "openai_compatible", "aliyun_dashscope"],
        default="demo",
        help="Backend passed through to structured_runner.py.",
    )
    parser.add_argument(
        "--policy",
        choices=["safe", "attack"],
        default="safe",
        help="Demo policy. Only used with --backend demo.",
    )
    parser.add_argument("--model", help="Model name for real API backends.")
    parser.add_argument("--base-url", help="Base URL for generic OpenAI-compatible backends.")
    parser.add_argument("--api-key-env", help="Environment variable name containing the API key.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum tool-augmented turns per case.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for real API backends.",
    )
    parser.add_argument(
        "--case-glob",
        default="case_*.json",
        help="Glob pattern under cases/ used to select benchmark cases.",
    )
    parser.add_argument("--suite-name", help="Optional suite output folder name.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep running the remaining cases even if one case fails.",
    )
    return parser.parse_args()


def build_default_suite_name(args: argparse.Namespace) -> str:
    if args.backend == "demo":
        return f"suite__structured__demo__{args.policy}"
    model_part = sanitize_name(args.model or "model")
    return f"suite__structured__{args.backend}__{model_part}"


def build_runner_command(
    *,
    python_exe: str,
    runner_path: Path,
    case_path: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> list[str]:
    cmd = [
        python_exe,
        str(runner_path),
        "--case",
        str(case_path),
        "--backend",
        args.backend,
        "--output-dir",
        str(output_dir),
        "--max-steps",
        str(args.max_steps),
        "--temperature",
        str(args.temperature),
    ]
    if args.backend == "demo":
        cmd.extend(["--policy", args.policy])
    else:
        if not args.model:
            raise ValueError("--model is required for non-demo suite runs.")
        cmd.extend(["--model", args.model])
        if args.backend == "openai_compatible":
            if not args.base_url:
                raise ValueError("--base-url is required for --backend openai_compatible.")
            cmd.extend(["--base-url", args.base_url])
        if args.api_key_env:
            cmd.extend(["--api-key-env", args.api_key_env])
    return cmd


def read_json_if_exists(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_summary_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "status",
        "returncode",
        "runtime_seconds",
        "api_call_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "user_task_completed",
        "attacker_task_completed",
        "forbidden_task_blocked",
        "output_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    rule_llm_root = base_dir.parent
    runner_path = base_dir / "structured_runner.py"
    cases_dir = rule_llm_root / "virtual_env_benchmark" / "cases"

    suite_name = args.suite_name or build_default_suite_name(args)
    suite_root = rule_llm_root / "structed_output" / "suites" / suite_name
    suite_root.mkdir(parents=True, exist_ok=True)

    case_paths = sorted(cases_dir.glob(args.case_glob))
    if not case_paths:
        raise FileNotFoundError(f"No cases matched {args.case_glob!r} under {cases_dir}")

    summary_rows: list[dict[str, Any]] = []
    started = time.time()

    for index, case_path in enumerate(case_paths, start=1):
        case_output_dir = suite_root / case_path.stem
        case_output_dir.mkdir(parents=True, exist_ok=True)

        cmd = build_runner_command(
            python_exe=sys.executable,
            runner_path=runner_path,
            case_path=case_path,
            output_dir=case_output_dir,
            args=args,
        )

        print(f"[{index}/{len(case_paths)}] Running {case_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=rule_llm_root)

        stdout_path = case_output_dir / "runner_stdout.txt"
        stderr_path = case_output_dir / "runner_stderr.txt"
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")

        score = read_json_if_exists(case_output_dir / "score.json")
        final_state = read_json_if_exists(case_output_dir / "env_final_state.json")
        run_info = (score or {}).get("run_info") or (final_state or {}).get("run_info") or {}
        task_resolution = (score or {}).get("task_resolution") or {}

        row = {
            "case_id": (score or {}).get("case_id", case_path.stem),
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "runtime_seconds": run_info.get("runtime_seconds", ""),
            "api_call_count": run_info.get("api_call_count", ""),
            "prompt_tokens": run_info.get("token_usage", {}).get("prompt_tokens", ""),
            "completion_tokens": run_info.get("token_usage", {}).get("completion_tokens", ""),
            "total_tokens": run_info.get("token_usage", {}).get("total_tokens", ""),
            "user_task_completed": task_resolution.get("user_task_completed", ""),
            "attacker_task_completed": task_resolution.get("attacker_task_completed", ""),
            "forbidden_task_blocked": task_resolution.get("forbidden_task_blocked", ""),
            "output_dir": str(case_output_dir),
        }
        summary_rows.append(row)

        if result.returncode != 0:
            print(f"  failed: {case_path.name}")
            if not args.continue_on_error:
                break
        else:
            print(f"  done: {case_path.name}")

    finished = time.time()
    success_count = sum(1 for row in summary_rows if row["status"] == "ok")
    total_prompt_tokens = sum(int(row["prompt_tokens"] or 0) for row in summary_rows)
    total_completion_tokens = sum(int(row["completion_tokens"] or 0) for row in summary_rows)
    total_tokens = sum(int(row["total_tokens"] or 0) for row in summary_rows)

    summary_json = {
        "suite_name": suite_name,
        "backend": args.backend,
        "policy": args.policy if args.backend == "demo" else None,
        "model": args.model,
        "case_count_requested": len(case_paths),
        "case_count_finished": len(summary_rows),
        "success_count": success_count,
        "failure_count": len(summary_rows) - success_count,
        "started_at_unix": started,
        "finished_at_unix": finished,
        "runtime_seconds": round(finished - started, 6),
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
        },
        "cases": summary_rows,
    }

    summary_json_path = suite_root / "suite_summary.json"
    summary_csv_path = suite_root / "suite_summary.csv"
    write_summary_json(summary_json_path, summary_json)
    write_summary_csv(summary_csv_path, summary_rows)

    print(f"suite_root: {suite_root}")
    print(f"summary_json: {summary_json_path}")
    print(f"summary_csv: {summary_csv_path}")


if __name__ == "__main__":
    main()
