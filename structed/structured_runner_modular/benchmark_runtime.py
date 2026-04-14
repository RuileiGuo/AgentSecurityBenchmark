import importlib.util
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
RULE_LLM_ROOT = CURRENT_DIR.parents[1]
ORIGINAL_DIR = RULE_LLM_ROOT / "original"
VIRTUAL_ENV_BENCHMARK_DIR = RULE_LLM_ROOT / "virtual_env_benchmark"
OUTPUTS_DIR = RULE_LLM_ROOT / "outputs"
STRUCTED_OUTPUT_DIR = RULE_LLM_ROOT / "structed_output"


def _find_runner_path() -> Path:
    candidate_relative_paths = [
        Path("runner.py"),
        Path("original") / "runner.py",
        Path("Rule+LLM") / "original" / "runner.py",
        Path("benchmark") / "virtual_env_benchmark_examples" / "runner.py",
        Path("virtual_env_benchmark") / "runner.py",
    ]

    for base in [CURRENT_DIR, *CURRENT_DIR.parents]:
        for relative_path in candidate_relative_paths:
            candidate = (base / relative_path).resolve()
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        "Could not locate runner.py. Expected it in a nearby folder such as "
        "'original/runner.py' or 'benchmark/virtual_env_benchmark_examples/runner.py'."
    )


def _load_runner_module():
    runner_path = _find_runner_path()
    spec = importlib.util.spec_from_file_location("structured_runner_base_runner", runner_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to create import spec for {runner_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_runner = _load_runner_module()

ALIYUN_DASHSCOPE_BASE_URL = _runner.ALIYUN_DASHSCOPE_BASE_URL
VirtualEnvRunner = _runner.VirtualEnvRunner
build_tool_schemas = _runner.build_tool_schemas
extract_message_text = _runner.extract_message_text
post_openai_compatible_chat = _runner.post_openai_compatible_chat
sanitize_name = _runner.sanitize_name
write_outputs = _runner.write_outputs
