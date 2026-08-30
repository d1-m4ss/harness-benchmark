#!/usr/bin/env python3
"""Run a benchmark series or one case in isolated Git worktrees."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from parse import parse_log


def render_command(
    parts: list[str], prompt: str, harness: dict[str, Any]
) -> list[str]:
    """Substitute provider-profile placeholders without invoking a shell."""
    values = {
        "prompt": prompt,
        "provider": str(harness.get("provider", "")),
        "model": str(harness.get("model", "")),
        "cli_model": str(harness.get("cli_model", harness.get("model", ""))),
    }
    rendered = []
    for part in parts:
        for name, value in values.items():
            part = part.replace(f"{{{name}}}", value)
        rendered.append(part)
    return rendered


def git(repo: Path, *args: str, check: bool = True, capture: bool = False) -> str:
    """Run Git with predictable output handling."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return result.stdout if capture else ""


def kill_group(process: subprocess.Popen[Any] | None) -> None:
    """Terminate the whole process group created for a harness or verifier."""
    if process is None or process.poll() is not None:
        return
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    for sig, delay in ((signal.SIGTERM, 0.35), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            break
        if delay:
            time.sleep(delay)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def apply_mutation(worktree: Path, mutation: str | None) -> None:
    """Apply and commit the repository mutation used by the controlled case."""
    if mutation is None:
        return
    if mutation != "invert_config_precedence":
        raise ValueError(f"unsupported mutation: {mutation}")
    path = worktree / "src/cli/paths.ts"
    text = path.read_text(encoding="utf-8")
    needle = (
        "export function getConfigDir(): string {\n"
        "  const customConfigDir = getCustomOpenCodeConfigDir();"
    )
    replacement = (
        "export function getConfigDir(): string {\n"
        "  if (process.env.XDG_CONFIG_HOME?.trim()) "
        "return getDefaultOpenCodeConfigDir();\n"
        "  const customConfigDir = getCustomOpenCodeConfigDir();"
    )
    if needle not in text:
        raise RuntimeError("target revision does not match the Task 4 mutation")
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    git(worktree, "add", "src/cli/paths.ts")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Harness Benchmark",
            "-c",
            "user.email=benchmark.invalid",
            "commit",
            "--no-gpg-sign",
            "-m",
            "benchmark: synthetic baseline",
        ],
        cwd=worktree,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_process(
    argv: list[str], cwd: Path, timeout: int, stdout: Any, stderr: Any, env: dict[str, str]
) -> tuple[int | None, bool, float, int, int]:
    """Run a command with timeout and return exit/timing data."""
    started_at_ms = int(time.time() * 1000)
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    timed_out = False
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=env,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(process)
        return (
            process.returncode,
            timed_out,
            time.monotonic() - started,
            started_at_ms,
            int(time.time() * 1000),
        )
    finally:
        kill_group(process)


def verify(worktree: Path, argv: list[str] | None, timeout: int) -> dict[str, Any]:
    """Run the case verifier and retain a bounded diagnostic tail."""
    if not argv:
        return {"configured": False, "passed": None, "exit_code": None, "output": ""}
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        output, _ = process.communicate(timeout=timeout)
        return {
            "configured": True,
            "passed": process.returncode == 0,
            "exit_code": process.returncode,
            "output": output[-8000:],
        }
    except subprocess.TimeoutExpired as error:
        kill_group(process)
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "configured": True,
            "passed": False,
            "exit_code": None,
            "timed_out": True,
            "output": output[-8000:],
        }


def routing_audit(spec: dict[str, str], start_ms: int, end_ms: int) -> dict[str, Any]:
    """Verify the actual upstream model from request-anchored OpenCodex logs."""
    expected = f"{spec['provider']}/{spec['model']}"
    try:
        raw = subprocess.check_output(
            ["ocx", "observe", "logs", "--limit", "200", "--json"],
            text=True,
            timeout=20,
        )
        payload = json.loads(raw)
        rows = payload.get("logs", payload.get("rows", []))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {
            "model_status": "INVALID_NO_PROXY_LOGS",
            "requested_model": spec["requested_model"],
            "actual_models": [],
            "error": str(error),
        }
    window = [
        row
        for row in rows
        if start_ms - 2500 <= int(row.get("timestamp", 0) or 0) <= end_ms + 2500
    ]
    anchors = [
        row for row in window if row.get("requestedModel") == spec["requested_model"]
    ]
    conversations = {row.get("conversationId") for row in anchors if row.get("conversationId")}
    scoped = [row for row in window if row.get("conversationId") in conversations]
    actual = sorted(
        {
            f"{row.get('provider', '')}/{row.get('model', '')}"
            for row in scoped
            if row.get("provider") or row.get("model")
        }
    )
    if not conversations:
        status = "INVALID_NO_REQUEST_ANCHOR"
    elif scoped and all(
        row.get("provider") == spec["provider"] and row.get("model") == spec["model"]
        for row in scoped
    ):
        status = "VALID"
    else:
        status = "INVALID_MODEL_FALLBACK" if scoped else "INVALID_NO_PROXY_LOGS"
    return {
        "model_status": status,
        "requested_model": spec["requested_model"],
        "expected_model": expected,
        "actual_models": actual,
        "matched_conversations": len(conversations),
    }


def changes(worktree: Path) -> dict[str, Any]:
    """Describe the patch left by the harness."""
    status = git(worktree, "status", "--porcelain", capture=True)
    files = [line[3:] for line in status.splitlines() if line[3:] != "node_modules"]
    # Intent-to-add makes new files visible in the patch without staging content.
    git(worktree, "add", "-N", "--", ".")
    diff = git(worktree, "diff", "HEAD", capture=True)
    additions = sum(
        line.startswith("+") and not line.startswith("+++") for line in diff.splitlines()
    )
    deletions = sum(
        line.startswith("-") and not line.startswith("---") for line in diff.splitlines()
    )
    return {
        "files_changed": files,
        "additions": additions,
        "deletions": deletions,
        "diff": diff,
    }


def contamination(parsed: dict[str, Any], worktree: Path, source_repo: Path) -> list[str]:
    """Flag references to the source checkout outside the isolated worktree."""
    allowed = str(worktree.resolve())
    forbidden = str(source_repo.resolve())
    reasons = []
    for value in parsed.get("all_commands", []) + parsed.get("file_paths", []):
        if isinstance(value, str) and forbidden in value and allowed not in value:
            reasons.append("accessed the source checkout outside the benchmark worktree")
    return list(dict.fromkeys(reasons))


def run_one(
    source_repo: Path,
    output: Path,
    temp_root: Path,
    commit: str,
    case_id: str,
    case: dict[str, Any],
    profile_id: str,
    harness_id: str,
    harness: dict[str, Any],
    run_number: int,
    timeout: int,
    verify_timeout: int,
) -> dict[str, Any]:
    """Execute and normalize one harness run."""
    worktree = temp_root / f"{case_id}-{harness_id}-{run_number}"
    git(source_repo, "worktree", "add", "--detach", str(worktree), commit)
    try:
        apply_mutation(worktree, case.get("mutation"))
        if case.get("symlink_node_modules"):
            modules = source_repo / "node_modules"
            if modules.exists():
                os.symlink(modules, worktree / "node_modules")

        stem = output / f"{harness_id}-run{run_number}"
        raw_path = stem.with_suffix(".jsonl")
        stderr_path = stem.with_suffix(".stderr")
        env = os.environ.copy()
        for name in harness.get("unset_env", []):
            env.pop(name, None)
        with raw_path.open("w", encoding="utf-8") as raw, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr:
            exit_code, timed_out, wall_time, start_ms, end_ms = run_process(
                render_command(harness["command"], case["prompt"], harness),
                worktree,
                timeout,
                raw,
                stderr,
                env,
            )

        parsed = parse_log(raw_path, harness["format"]).to_dict()
        parsed["requested_model"] = harness["requested_model"]
        if "routing" in harness:
            route = routing_audit(harness["routing"], start_ms, end_ms)
            parsed.update(route)
            stem.with_suffix(".routing.json").write_text(
                json.dumps(route, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        else:
            models = parsed.get("actual_models", [])
            pattern = harness["expected_model_regex"]
            if not models:
                parsed["model_status"] = "INVALID_NO_MODEL_IN_LOG"
            elif all(re.search(pattern, str(model)) for model in models):
                parsed["model_status"] = "VALID"
            else:
                parsed["model_status"] = "INVALID_MODEL_MISMATCH"

        patch = changes(worktree)
        stem.with_suffix(".patch").write_text(patch.pop("diff"), encoding="utf-8")
        verification = verify(worktree, case.get("verify"), verify_timeout)
        contamination_reasons = contamination(parsed, worktree, source_repo)
        expected_response = case.get("expected_response")
        response_valid = (
            None
            if expected_response is None
            else parsed.get("response", "").strip() == expected_response
        )
        scope_valid = (
            None
            if not case.get("expected_no_changes")
            else not patch["files_changed"]
        )
        valid = (
            not timed_out
            and exit_code == 0
            and parsed["model_status"] == "VALID"
            and not contamination_reasons
            and verification.get("passed") is not False
            and response_valid is not False
            and scope_valid is not False
        )
        result = {
            **parsed,
            "case": case_id,
            "profile": profile_id,
            "harness": harness_id,
            "run": run_number,
            "wall_time": round(wall_time, 6),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "patch": patch,
            "verification": verification,
            "response_valid": response_valid,
            "scope_valid": scope_valid,
            "contaminated": bool(contamination_reasons),
            "contamination_reasons": contamination_reasons,
            "valid_run": valid,
        }
        stem.with_suffix(".json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return result
    finally:
        git(source_repo, "worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(worktree, ignore_errors=True)
        git(source_repo, "worktree", "prune", check=False)


def load_cases(path: Path) -> dict[str, Any]:
    """Load and minimally validate the benchmark definition."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("target", "defaults", "cases"):
        if key not in data:
            raise ValueError(f"{path}: missing {key}")
    return data


def load_providers(path: Path) -> dict[str, Any]:
    """Load provider/model profiles without reading credentials."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") not in {None, 1}:
        raise ValueError(f"{path}: unsupported schema_version")
    if not isinstance(data.get("profiles"), dict) or not data["profiles"]:
        raise ValueError(f"{path}: profiles must be a non-empty object")
    for profile_id, profile in data["profiles"].items():
        if not isinstance(profile.get("group"), str) or not profile["group"]:
            raise ValueError(f"{path}: profile {profile_id} has no group")
        if not isinstance(profile.get("harnesses"), dict) or not profile["harnesses"]:
            raise ValueError(f"{path}: profile {profile_id} has no harnesses")
        for harness_id, harness in profile["harnesses"].items():
            for key in ("format", "provider", "model", "command", "requested_model"):
                if key not in harness:
                    raise ValueError(
                        f"{path}: {profile_id}/{harness_id} is missing {key}"
                    )
            command = harness["command"]
            if not isinstance(command, list) or not command or not all(
                isinstance(part, str) for part in command
            ):
                raise ValueError(
                    f"{path}: {profile_id}/{harness_id} command must be "
                    "a non-empty string array"
                )
            rendered = render_command(command, "SMOKE", harness)
            if any(
                re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", part)
                for part in rendered
            ):
                raise ValueError(
                    f"{path}: {profile_id}/{harness_id} has an unknown placeholder"
                )
            if "expected_model_regex" not in harness and "routing" not in harness:
                raise ValueError(
                    f"{path}: {profile_id}/{harness_id} lacks model verification"
                )
            if "expected_model_regex" in harness:
                try:
                    re.compile(harness["expected_model_regex"])
                except (TypeError, re.error) as error:
                    raise ValueError(
                        f"{path}: {profile_id}/{harness_id} has an invalid "
                        "expected_model_regex"
                    ) from error
    return data


def prepare_smoke_repo(path: Path) -> tuple[Path, str]:
    """Create a disposable Git repository for connectivity smoke runs."""
    path.mkdir(parents=True)
    git(path, "init", "-q")
    (path / "README.md").write_text("# Harness smoke test\n", encoding="utf-8")
    git(path, "add", "README.md")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Harness Benchmark",
            "-c",
            "user.email=benchmark.invalid",
            "commit",
            "-qm",
            "smoke baseline",
        ],
        cwd=path,
        check=True,
    )
    return path, git(path, "rev-parse", "HEAD", capture=True).strip()


def select_cases(
    definitions: dict[str, Any], selection: str
) -> list[tuple[str, dict[str, Any]]]:
    """Resolve one case or every case in a model-controlled series."""
    cases = definitions["cases"]
    if selection in cases:
        return [(selection, cases[selection])]
    if selection in {"gpt", "muse"}:
        selected = [
            (case_id, case)
            for case_id, case in cases.items()
            if case.get("profile_group") == selection
        ]
        if selected:
            return selected
    raise ValueError(f"unknown case or series: {selection}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Series: gpt, muse. Cases: smoke, gpt-readonly, gpt-coding, "
            "muse-web, muse-repo, muse-restraint, muse-regression. "
            "Run smoke before a paid series."
        ),
    )
    parser.add_argument("selection", help="Series ID (gpt/muse) or case ID")
    parser.add_argument(
        "--repo", type=Path, help="Local target Git checkout; not needed for smoke"
    )
    parser.add_argument(
        "--harness",
        action="append",
        required=True,
        help="Harness ID to run; repeat to compare multiple harnesses",
    )
    parser.add_argument(
        "--runs",
        type=int,
        help="Override runs per harness for every selected case",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: runs/SELECTION)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("cases.json"),
        help="Benchmark definition JSON",
    )
    parser.add_argument(
        "--providers",
        type=Path,
        default=Path(__file__).with_name("providers.json"),
        help="Provider/model profile JSON",
    )
    parser.add_argument(
        "--profile",
        help="Profile ID from providers.json; required when no selection default exists",
    )
    args = parser.parse_args()

    definitions = load_cases(args.cases)
    providers = load_providers(args.providers)
    try:
        selected_cases = select_cases(definitions, args.selection)
    except ValueError as error:
        parser.error(str(error))
    is_series = args.selection in {"gpt", "muse"}
    default_profiles = {
        case.get("default_profile")
        for _, case in selected_cases
        if case.get("default_profile")
    }
    profile_id = args.profile or (
        next(iter(default_profiles)) if len(default_profiles) == 1 else None
    )
    if not profile_id:
        parser.error("--profile is required for this selection")
    if profile_id not in providers["profiles"]:
        parser.error(f"unknown provider profile: {profile_id}")
    profile = providers["profiles"][profile_id]
    for case_id, case in selected_cases:
        expected_group = case.get("profile_group")
        if expected_group not in {"any", profile.get("group")}:
            parser.error(
                f"case {case_id} requires a {expected_group} profile, "
                f"but {profile_id} is {profile.get('group')}"
            )
    harnesses = profile["harnesses"]
    unknown = [name for name in args.harness if name not in harnesses]
    if unknown:
        parser.error(f"unsupported harness for {profile_id}: {', '.join(unknown)}")
    if args.runs is not None and args.runs < 1:
        parser.error("--runs must be at least 1")

    if any(not case.get("smoke") for _, case in selected_cases) and args.repo is None:
        parser.error("--repo is required for benchmark cases and series")

    output = (args.output or Path("runs") / args.selection).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    timeout = int(definitions["defaults"].get("timeout", 300))
    verify_timeout = int(definitions["defaults"].get("verify_timeout", 60))
    cooldown = float(definitions["defaults"].get("cooldown_seconds", 0))
    all_results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="harness-benchmark-") as temp:
        temp_root = Path(temp)
        if selected_cases[0][1].get("smoke"):
            source_repo, commit = prepare_smoke_repo(temp_root / "smoke-source")
        else:
            source_repo = args.repo.expanduser().resolve()
            if not (source_repo / ".git").exists():
                parser.error(f"not a Git checkout: {source_repo}")
            commit = definitions["target"]["commit"]
            try:
                git(source_repo, "cat-file", "-e", f"{commit}^{{commit}}")
            except subprocess.CalledProcessError:
                parser.error(f"target commit is unavailable: {commit}")
        for case_id, case in selected_cases:
            case_output = output / case_id if is_series else output
            case_output.mkdir(parents=True, exist_ok=True)
            case_results: list[dict[str, Any]] = []
            runs = args.runs or int(case.get("runs", 1))
            for round_number in range(1, runs + 1):
                offset = (round_number - 1) % len(args.harness)
                order = args.harness[offset:] + args.harness[:offset]
                for harness_id in order:
                    print(
                        f"{case_id}: {harness_id} run {round_number}/{runs}",
                        flush=True,
                    )
                    result = run_one(
                        source_repo,
                        case_output,
                        temp_root,
                        commit,
                        case_id,
                        case,
                        profile_id,
                        harness_id,
                        harnesses[harness_id],
                        round_number,
                        timeout,
                        verify_timeout,
                    )
                    case_results.append(result)
                    all_results.append(result)
                    (case_output / "summary.json").write_text(
                        json.dumps(case_results, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    if is_series:
                        (output / "summary.json").write_text(
                            json.dumps(all_results, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                    print(
                        f"  {result['wall_time']:.2f}s; "
                        f"total={result['total_input']}; "
                        f"model={result['model_status']}; "
                        f"valid={result['valid_run']}",
                        flush=True,
                    )
                    if not result["valid_run"]:
                        print(f"hard failure; inspect {case_output}", flush=True)
                        return 1
                    if cooldown:
                        time.sleep(cooldown)
    print(f"wrote {output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
