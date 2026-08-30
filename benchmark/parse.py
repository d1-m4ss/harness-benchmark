#!/usr/bin/env python3
"""Normalize a Codex, Pi, Claude Code, or OpenCode JSON/JSONL log."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

TEST_RE = re.compile(
    r"(?:\bbun\s+test\b|\bnpm\s+(?:run\s+)?test\b|\bpnpm\s+(?:run\s+)?test\b|"
    r"\byarn\s+(?:run\s+)?test\b|\bvitest\b|\bjest\b|\bpytest\b|\bgo\s+test\b|\bcargo\s+test\b)",
    re.IGNORECASE,
)
CHILD_RE = re.compile(r'<subagent\s+sessionID="([^"]+)"')


@dataclass
class ParsedRun:
    harness: str
    model_calls: int | None = None
    fresh_input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_input: int = 0
    output: int = 0
    reasoning: int = 0
    final_context: int | None = None
    tool_calls: int = 0
    tools: dict[str, int] = field(default_factory=dict)
    test_commands: list[str] = field(default_factory=list)
    all_commands: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    response: str = ""
    actual_models: list[str] = field(default_factory=list)
    requested_model: str | None = None
    model_status: str | None = None
    accounting_scope: str = "complete"
    child_sessions: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["cache_hit_pct"] = (
            self.cache_read / self.total_input * 100 if self.total_input else 0.0
        )
        return result


def _records(path: str | Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return []
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _command(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return next(
        (value[key] for key in ("command", "cmd", "script") if isinstance(value.get(key), str)),
        "",
    )


def _paths(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [
        value[key]
        for key in ("path", "file_path", "filepath", "directory", "cwd")
        if isinstance(value.get(key), str)
    ]


def _tests(commands: Iterable[str]) -> list[str]:
    return [command for command in commands if TEST_RE.search(command)]


def parse_opencode(path: str | Path, harness: str) -> ParsedRun:
    records = _records(path)
    steps = [
        record
        for record in records
        if record.get("type") == "step_finish"
        and isinstance(record.get("part", {}).get("tokens"), dict)
    ]
    tools = [record for record in records if record.get("type") == "tool_use"]
    fresh = cache_read = cache_write = output = reasoning = 0
    for step in steps:
        tokens = step["part"]["tokens"]
        cache = tokens.get("cache", {}) or {}
        fresh += int(tokens.get("input", 0) or 0)
        cache_read += int(cache.get("read", 0) or 0)
        cache_write += int(cache.get("write", 0) or 0)
        output += int(tokens.get("output", 0) or 0)
        reasoning += int(tokens.get("reasoning", 0) or 0)

    counts: Counter[str] = Counter()
    commands: list[str] = []
    paths: list[str] = []
    child_ids: list[str] = []
    for event in tools:
        part = event.get("part", {}) or {}
        name = str(part.get("tool") or "unknown")
        counts[name] += 1
        state = part.get("state", {}) or {}
        tool_input = state.get("input", {}) or {}
        params = part.get("params", {}) or {}
        command = _command(tool_input) or _command(params)
        if command:
            commands.append(command)
        paths.extend(_paths(tool_input) + _paths(params))
        if name == "subagent" and isinstance(state.get("output"), str):
            child_ids.extend(CHILD_RE.findall(state["output"]))

    models: list[str] = []
    text: list[str] = []
    for record in records:
        part = record.get("part", {}) if isinstance(record.get("part"), dict) else {}
        for container in (record, part):
            for key in ("model", "modelID", "model_id"):
                if isinstance(container.get(key), str):
                    models.append(container[key])
        if record.get("type") == "text" and isinstance(part.get("text"), str):
            text.append(part["text"])

    final_context = None
    if steps:
        tokens = steps[-1]["part"]["tokens"]
        cache = tokens.get("cache", {}) or {}
        final_context = (
            int(tokens.get("input", 0) or 0)
            + int(cache.get("read", 0) or 0)
            + int(cache.get("write", 0) or 0)
        )
    parent_only = counts.get("subagent", 0) > 0
    return ParsedRun(
        harness=harness,
        model_calls=len(steps) or None,
        fresh_input=fresh,
        cache_read=cache_read,
        cache_write=cache_write,
        total_input=fresh + cache_read,
        output=output,
        reasoning=reasoning,
        final_context=final_context,
        tool_calls=sum(counts.values()),
        tools=dict(counts),
        test_commands=_tests(commands),
        all_commands=commands,
        file_paths=_unique(paths),
        response="\n".join(text).strip(),
        actual_models=_unique(models),
        accounting_scope="parent_only" if parent_only else "complete",
        child_sessions=len(set(child_ids)),
        warnings=["OpenCode child-session tokens may be missing"] if parent_only else [],
    )


def parse_pi(path: str | Path) -> ParsedRun:
    records = _records(path)
    messages = [
        record.get("message", {})
        for record in records
        if record.get("type") == "message_end"
        and record.get("message", {}).get("role") == "assistant"
    ]
    usages = [
        message.get("usage", {})
        for message in messages
        if isinstance(message.get("usage"), dict)
    ]
    fresh = sum(int(usage.get("input", 0) or 0) for usage in usages)
    cache_read = sum(int(usage.get("cacheRead", 0) or 0) for usage in usages)
    cache_write = sum(int(usage.get("cacheWrite", 0) or 0) for usage in usages)
    output = sum(int(usage.get("output", 0) or 0) for usage in usages)
    reasoning = sum(
        int(
            usage.get("reasoning", 0)
            or usage.get("details", {}).get("reasoning", 0)
            or 0
        )
        for usage in usages
    )
    commands: list[str] = []
    paths: list[str] = []
    counts: Counter[str] = Counter()
    for event in (record for record in records if record.get("type") == "tool_execution_start"):
        counts[str(event.get("toolName") or "unknown")] += 1
        args = event.get("args", {}) or {}
        if _command(args):
            commands.append(_command(args))
        paths.extend(_paths(args))
    texts: list[str] = []
    models: list[str] = []
    for message in messages:
        if isinstance(message.get("model"), str):
            models.append(message["model"])
        for item in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                texts.append(item["text"])
    final_context = None
    if usages:
        last = usages[-1]
        final_context = (
            int(last.get("input", 0) or 0)
            + int(last.get("cacheRead", 0) or 0)
            + int(last.get("cacheWrite", 0) or 0)
        )
    return ParsedRun(
        harness="pi",
        model_calls=len(usages),
        fresh_input=fresh,
        cache_read=cache_read,
        cache_write=cache_write,
        total_input=fresh + cache_read,
        output=output,
        reasoning=reasoning,
        final_context=final_context,
        tool_calls=sum(counts.values()),
        tools=dict(counts),
        test_commands=_tests(commands),
        all_commands=commands,
        file_paths=_unique(paths),
        response="\n".join(texts).strip(),
        actual_models=_unique(models),
    )


def parse_codex(path: str | Path) -> ParsedRun:
    records = _records(path)
    turns = [record for record in records if record.get("type") == "turn.completed"]
    usage = turns[-1].get("usage", {}) if turns else {}
    total = int(usage.get("input_tokens", 0) or 0)
    cached = int(usage.get("cached_input_tokens", 0) or 0)
    commands: list[str] = []
    paths: list[str] = []
    texts: list[str] = []
    counts: Counter[str] = Counter()
    for record in records:
        if record.get("type") != "item.completed":
            continue
        item = record.get("item", {}) or {}
        kind = str(item.get("type") or "unknown")
        if kind in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
            counts[kind] += 1
        if kind == "command_execution" and isinstance(item.get("command"), str):
            commands.append(item["command"])
        if kind == "agent_message" and isinstance(item.get("text"), str):
            texts.append(item["text"])
        paths.extend(_paths(item))
    models = [
        record[key]
        for record in records
        for key in ("model", "model_id", "modelID")
        if isinstance(record.get(key), str)
    ]
    return ParsedRun(
        harness="codex",
        fresh_input=max(total - cached, 0),
        cache_read=cached,
        cache_write=int(usage.get("cache_write_input_tokens", 0) or 0),
        total_input=total,
        output=int(usage.get("output_tokens", 0) or 0),
        reasoning=int(usage.get("reasoning_output_tokens", 0) or 0),
        tool_calls=sum(counts.values()),
        tools=dict(counts),
        test_commands=_tests(commands),
        all_commands=commands,
        file_paths=_unique(paths),
        response="\n".join(texts).strip(),
        actual_models=_unique(models),
        warnings=["Codex exec JSON does not expose final context or inference-call count"],
    )


def parse_claude(path: str | Path) -> ParsedRun:
    records = _records(path)
    result = next((record for record in reversed(records) if record.get("type") == "result"), None)
    assistants = [
        record.get("message", {})
        for record in records
        if record.get("type") == "assistant"
    ]
    usage = result.get("usage", {}) if result else {}
    if result:
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        fresh = int(usage.get("input_tokens", 0) or 0) + cache_write
        cached = int(usage.get("cache_read_input_tokens", 0) or 0)
        output = int(usage.get("output_tokens", 0) or 0)
    else:
        cache_write = sum(
            int(
                (message.get("usage", {}) or {}).get(
                    "cache_creation_input_tokens", 0
                )
                or 0
            )
            for message in assistants
        )
        fresh = (
            sum(
                int(
                    (message.get("usage", {}) or {}).get("input_tokens", 0) or 0
                )
                for message in assistants
            )
            + cache_write
        )
        cached = sum(
            int(
                (message.get("usage", {}) or {}).get(
                    "cache_read_input_tokens", 0
                )
                or 0
            )
            for message in assistants
        )
        output = sum(
            int(
                (message.get("usage", {}) or {}).get("output_tokens", 0) or 0
            )
            for message in assistants
        )
    counts: Counter[str] = Counter()
    commands: list[str] = []
    paths: list[str] = []
    texts: list[str] = []
    models: list[str] = []
    for record in records:
        if record.get("type") == "system" and record.get("subtype") == "init":
            if isinstance(record.get("model"), str):
                models.append(record["model"])
            if isinstance(record.get("cwd"), str):
                paths.append(record["cwd"])
        if record.get("type") != "assistant":
            continue
        message = record.get("message", {}) or {}
        if isinstance(message.get("model"), str):
            models.append(message["model"])
        for item in message.get("content", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                texts.append(item["text"])
            if item.get("type") == "tool_use":
                counts[str(item.get("name") or "unknown")] += 1
                tool_input = item.get("input", {}) or {}
                if _command(tool_input):
                    commands.append(_command(tool_input))
                paths.extend(_paths(tool_input))
    response = (
        result.get("result", "")
        if result and isinstance(result.get("result"), str)
        else "\n".join(texts).strip()
    )
    turns = result.get("num_turns") if result else len(assistants)
    return ParsedRun(
        harness="claude",
        model_calls=turns if isinstance(turns, int) else None,
        fresh_input=fresh,
        cache_read=cached,
        cache_write=cache_write,
        total_input=fresh + cached,
        output=output,
        reasoning=int(usage.get("output_tokens_details", {}).get("thinking_tokens", 0) or 0),
        tool_calls=sum(counts.values()),
        tools=dict(counts),
        test_commands=_tests(commands),
        all_commands=commands,
        file_paths=_unique(paths),
        response=response,
        actual_models=_unique(models),
    )


def parse_log(
    path: str | Path,
    log_format: str,
    routing_sidecar: str | Path | None = None,
) -> ParsedRun:
    normalized = log_format.lower().replace("_", "-")
    if normalized in {"opencode", "opencode-jsonl", "opencode2", "opencode2-jsonl"}:
        parsed = parse_opencode(path, "opencode2" if "2" in normalized else "opencode")
    elif normalized in {"pi", "pi-jsonl"}:
        parsed = parse_pi(path)
    elif normalized in {"codex", "codex-jsonl"}:
        parsed = parse_codex(path)
    elif normalized in {"claude", "claude-json", "claude-stream-json"}:
        parsed = parse_claude(path)
    else:
        raise ValueError(f"unsupported log format: {log_format}")
    if routing_sidecar:
        routing = json.loads(Path(routing_sidecar).read_text(encoding="utf-8"))
        parsed.requested_model = routing.get("requested_model") or routing.get(
            "proxy_requested_model"
        )
        actual = routing.get("actual_models", routing.get("actual_model", []))
        parsed.actual_models = [actual] if isinstance(actual, str) else _unique(actual)
        parsed.model_status = routing.get("model_status") or routing.get("status")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Harness JSON or JSONL log")
    parser.add_argument(
        "--format",
        required=True,
        choices=["codex", "pi", "claude", "opencode", "opencode2"],
    )
    parser.add_argument("--routing-sidecar", type=Path, help="Optional proxy-routing JSON")
    parser.add_argument("--out", type=Path, help="Output JSON; stdout by default")
    args = parser.parse_args()
    result = parse_log(args.log, args.format, args.routing_sidecar).to_dict()
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
