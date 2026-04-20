"""CLI entry point for the LLM test harness.

Usage:
    uv run python -m backend.llm_harness --model <model> --message '{"role":"user","content":"Hello"}'
    uv run python -m backend.llm_harness --from tests/llm_scenarios/example.json
    uv run python -m backend.llm_harness --model <model> --system "You are helpful." --message '...' --reasoning
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from backend.llm_harness._output import StreamPrinter
from backend.llm_harness._runner import HarnessRunner, load_api_key


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="llm-harness",
        description="Test LLM calls against Ollama Cloud directly.",
    )

    parser.add_argument(
        "--from",
        dest="scenario_file",
        help="Load a complete scenario from a JSON file.",
    )
    parser.add_argument(
        "--model",
        help="Model slug (e.g. 'mistral-large-2411', 'deepseek-r1').",
    )
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help='Message as JSON: \'{"role":"user","content":"Hello"}\'. Repeatable.',
    )
    parser.add_argument(
        "--system",
        help="System prompt text.",
    )
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="Enable reasoning/thinking mode.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--tools",
        help="Path to a JSON file containing tool definitions.",
    )
    parser.add_argument(
        "--adapter",
        default="ollama_http",
        choices=["ollama_http", "xai_http"],
        help="Adapter to exercise (default: ollama_http).",
    )
    parser.add_argument(
        "--key-file",
        default=".llm-test-key",
        help="Path to API key file (default: .llm-test-key).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Provider base URL (overrides adapter default).",
    )

    args = parser.parse_args()
    # When no explicit key file was provided, use adapter-appropriate default.
    if args.key_file == ".llm-test-key" and args.adapter == "xai_http":
        args.key_file = ".xai-test-key"
    return args


def _load_scenario(path: str) -> dict:
    """Load a scenario JSON file.

    Expected format:
    {
        "model": "mistral-large-2411",
        "system": "You are helpful.",          // optional
        "messages": [
            {"role": "user", "content": "Hello"}
        ],
        "reasoning": false,                    // optional
        "temperature": null,                   // optional
        "tools": [...]                         // optional
    }
    """
    with Path(path).open() as f:
        return json.load(f)


def _parse_messages(raw_messages: list[str]) -> list[dict]:
    """Parse JSON message strings from --message arguments."""
    result = []
    for raw in raw_messages:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON in --message: {exc}", file=sys.stderr)
            sys.exit(1)
        if "role" not in msg or "content" not in msg:
            print(f"Message must have 'role' and 'content': {raw}", file=sys.stderr)
            sys.exit(1)
        result.append(msg)
    return result


async def _run(args: argparse.Namespace) -> None:
    api_key = load_api_key(args.key_file)
    runner = HarnessRunner(
        api_key=api_key,
        adapter_type=args.adapter,
        base_url=args.base_url,
    )

    # Build parameters from scenario file or CLI arguments.
    if args.scenario_file:
        scenario = _load_scenario(args.scenario_file)
        model = scenario["model"]
        system = scenario.get("system")
        messages = scenario.get("messages", [])
        reasoning = scenario.get("reasoning", False)
        temperature = scenario.get("temperature")
        tools = scenario.get("tools")
    else:
        if not args.model:
            print("Either --model or --from is required.", file=sys.stderr)
            sys.exit(1)
        model = args.model
        system = args.system
        messages = _parse_messages(args.message)
        reasoning = args.reasoning
        temperature = args.temperature
        tools = None
        if args.tools:
            with Path(args.tools).open() as f:
                tools = json.load(f)

    if not messages:
        print("At least one message is required.", file=sys.stderr)
        sys.exit(1)

    completion_messages = runner.build_messages(system, messages)
    request = runner.build_request(
        model=model,
        messages=completion_messages,
        temperature=temperature,
        reasoning=reasoning,
        supports_reasoning=reasoning,
        tools=tools,
    )

    print(f"Model: {model}")
    print(f"Messages: {len(completion_messages)}")
    if reasoning:
        print("Reasoning: enabled")
    if temperature is not None:
        print(f"Temperature: {temperature}")
    if tools:
        print(f"Tools: {len(tools)} defined")
    print()

    printer = StreamPrinter()

    if tools:
        events = runner.run_with_tools(request)
    else:
        events = runner.run(request)

    await printer.process(events)


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_run(args))
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
