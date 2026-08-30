#!/usr/bin/env python3
"""Dependency-free parser, data, documentation, and publication-safety checks."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from parse import parse_log
from run import changes, render_command, select_cases

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = ROOT / "benchmark"


class ParserTests(unittest.TestCase):
    def log(self, records: list[dict]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "log.jsonl"
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )
        return path

    def test_codex_cached_input_is_a_subset(self) -> None:
        result = parse_log(
            self.log(
                [
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "bun test x.test.ts",
                        },
                    },
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 1000,
                            "cached_input_tokens": 800,
                            "output_tokens": 50,
                        },
                    },
                ]
            ),
            "codex",
        )
        self.assertEqual(
            (result.fresh_input, result.cache_read, result.total_input),
            (200, 800, 1000),
        )
        self.assertEqual(result.test_commands, ["bun test x.test.ts"])

    def test_claude_cache_creation_is_new_input(self) -> None:
        result = parse_log(
            self.log(
                [
                    {"type": "system", "subtype": "init", "model": "model"},
                    {
                        "type": "result",
                        "num_turns": 3,
                        "usage": {
                            "input_tokens": 26,
                            "cache_creation_input_tokens": 100,
                            "cache_read_input_tokens": 900,
                            "output_tokens": 10,
                        },
                    },
                ]
            ),
            "claude",
        )
        self.assertEqual((result.fresh_input, result.cache_write), (126, 100))
        self.assertEqual(result.total_input, 1026)

    def test_pi_usage(self) -> None:
        result = parse_log(
            self.log(
                [
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "model": "model",
                            "usage": {
                                "input": 100,
                                "cacheRead": 300,
                                "cacheWrite": 10,
                                "output": 20,
                            },
                            "content": [],
                        },
                    }
                ]
            ),
            "pi",
        )
        self.assertEqual(
            (result.fresh_input, result.total_input, result.final_context),
            (100, 400, 410),
        )

    def test_opencode_shell_and_child_session(self) -> None:
        result = parse_log(
            self.log(
                [
                    {
                        "type": "tool_use",
                        "part": {
                            "tool": "shell",
                            "state": {"input": {"command": "bun test src/x.test.ts"}},
                        },
                    },
                    {
                        "type": "tool_use",
                        "part": {
                            "tool": "subagent",
                            "state": {
                                "output": '<subagent sessionID="child-1">ok</subagent>'
                            },
                        },
                    },
                    {
                        "type": "step_finish",
                        "part": {
                            "tokens": {
                                "input": 100,
                                "cache": {"read": 400, "write": 0},
                                "output": 20,
                            }
                        },
                    },
                ]
            ),
            "opencode2",
        )
        self.assertEqual(result.test_commands, ["bun test src/x.test.ts"])
        self.assertEqual(result.accounting_scope, "parent_only")
        self.assertEqual(result.child_sessions, 1)

    def test_routing_sidecar(self) -> None:
        log = self.log([{"type": "turn.completed", "usage": {}}])
        sidecar = log.with_name("routing.json")
        sidecar.write_text(
            json.dumps(
                {
                    "requested_model": "requested",
                    "actual_models": ["provider/model"],
                    "model_status": "VALID",
                }
            ),
            encoding="utf-8",
        )
        result = parse_log(log, "codex", sidecar)
        self.assertEqual(result.actual_models, ["provider/model"])
        self.assertEqual(result.model_status, "VALID")


class RepositoryTests(unittest.TestCase):
    def test_runner_patch_includes_new_files(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Path(directory.name)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Benchmark Test",
                "-c",
                "user.email=benchmark.invalid",
                "commit",
                "-qm",
                "baseline",
            ],
            cwd=repo,
            check=True,
        )
        (repo / "new.txt").write_text("new\n", encoding="utf-8")
        result = changes(repo)
        self.assertIn("new.txt", result["files_changed"])
        self.assertIn("diff --git a/new.txt b/new.txt", result["diff"])

    def test_curated_data_contract(self) -> None:
        payload = json.loads((BENCHMARK / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["results"]), 24)
        claude = [
            row
            for row in payload["results"]
            if row["harness"] == "Claude Code + OpenCodex"
            and row["task"] in {"Task 1 web research", "Task 2 repo architecture"}
        ]
        self.assertEqual(len(claude), 2)
        self.assertTrue(all("Sonnet 5 xhigh" in row["control_model"] for row in claude))
        task4 = [
            row
            for row in payload["results"]
            if row["task"] == "Task 4 controlled regression"
            and row["harness"] == "Pi"
        ][0]
        self.assertEqual(task4["total_input"], 267437)
        self.assertEqual(task4["wall_seconds"], 103.955)

    def test_every_case_has_strict_model_evidence(self) -> None:
        payload = json.loads(
            (BENCHMARK / "providers.json").read_text(encoding="utf-8")
        )
        for profile_id, profile in payload["profiles"].items():
            for name, harness in profile["harnesses"].items():
                self.assertTrue(
                    "expected_model_regex" in harness or "routing" in harness,
                    f"{profile_id}/{name} lacks actual-model verification",
                )
                rendered = render_command(harness["command"], "HI", harness)
                self.assertFalse(
                    any(
                        re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", part)
                        for part in rendered
                    ),
                    f"unresolved command placeholder in {profile_id}/{name}",
                )
                if name.startswith("opencode"):
                    self.assertIn("--auto", rendered)
                    self.assertIn("yolo", rendered)

    def test_smoke_case_contract(self) -> None:
        payload = json.loads((BENCHMARK / "cases.json").read_text(encoding="utf-8"))
        smoke = payload["cases"]["smoke"]
        self.assertEqual(smoke["prompt"], "Reply with exactly: HI")
        self.assertEqual(smoke["expected_response"], "HI")
        self.assertTrue(smoke["expected_no_changes"])
        self.assertEqual(smoke["runs"], 1)

    def test_series_contract(self) -> None:
        payload = json.loads((BENCHMARK / "cases.json").read_text(encoding="utf-8"))
        gpt = select_cases(payload, "gpt")
        muse = select_cases(payload, "muse")
        self.assertEqual(
            [case_id for case_id, _ in gpt], ["gpt-readonly", "gpt-coding"]
        )
        self.assertEqual(
            [case_id for case_id, _ in muse],
            ["muse-web", "muse-repo", "muse-restraint", "muse-regression"],
        )
        self.assertEqual(sum(case["runs"] for _, case in gpt), 6)
        self.assertEqual(sum(case["runs"] for _, case in muse), 11)

    def test_smoke_cli_with_fake_provider(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        providers = root / "providers.json"
        output = root / "runs"
        fake_log = (
            "import json; print(json.dumps({'type':'message_end','message':"
            "{'role':'assistant','model':'fake/model','usage':{'input':1,'output':1},"
            "'content':[{'type':'text','text':'HI'}]}}))"
        )
        providers.write_text(
            json.dumps(
                {
                    "profiles": {
                        "fake": {
                            "group": "fake",
                            "harnesses": {
                                "fake": {
                                    "format": "pi",
                                    "provider": "fake",
                                    "model": "model",
                                    "command": [sys.executable, "-c", fake_log],
                                    "requested_model": "fake/model",
                                    "expected_model_regex": "^fake/model$",
                                }
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(BENCHMARK / "run.py"),
                "smoke",
                "--providers",
                str(providers),
                "--profile",
                "fake",
                "--harness",
                "fake",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0]["valid_run"])
        self.assertTrue(summary[0]["response_valid"])
        self.assertTrue(summary[0]["scope_valid"])
        self.assertEqual(summary[0]["model_status"], "VALID")

    def test_series_cli_with_fake_provider(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Benchmark Test",
                "-c",
                "user.email=benchmark.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=repo,
            check=True,
        )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()
        cases = root / "cases.json"
        providers = root / "providers.json"
        output = root / "runs"
        cases.write_text(
            json.dumps(
                {
                    "target": {"repository": "fixture", "commit": commit},
                    "defaults": {
                        "timeout": 30,
                        "verify_timeout": 30,
                        "cooldown_seconds": 0,
                    },
                    "cases": {
                        "muse-first": {
                            "profile_group": "muse",
                            "default_profile": "fake",
                            "runs": 2,
                            "prompt": "Reply with exactly: HI",
                        },
                        "muse-second": {
                            "profile_group": "muse",
                            "default_profile": "fake",
                            "runs": 1,
                            "prompt": "Reply with exactly: HI",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        fake_log = (
            "import json; print(json.dumps({'type':'message_end','message':"
            "{'role':'assistant','model':'fake/model','usage':{'input':1,'output':1},"
            "'content':[{'type':'text','text':'HI'}]}}))"
        )
        providers.write_text(
            json.dumps(
                {
                    "profiles": {
                        "fake": {
                            "group": "muse",
                            "harnesses": {
                                "fake": {
                                    "format": "pi",
                                    "provider": "fake",
                                    "model": "model",
                                    "command": [sys.executable, "-c", fake_log],
                                    "requested_model": "fake/model",
                                    "expected_model_regex": "^fake/model$",
                                }
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(BENCHMARK / "run.py"),
                "muse",
                "--cases",
                str(cases),
                "--providers",
                str(providers),
                "--profile",
                "fake",
                "--repo",
                str(repo),
                "--harness",
                "fake",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(summary), 3)
        self.assertEqual(
            len(
                json.loads(
                    (output / "muse-first/summary.json").read_text(encoding="utf-8")
                )
            ),
            2,
        )
        self.assertEqual(
            len(
                json.loads(
                    (output / "muse-second/summary.json").read_text(encoding="utf-8")
                )
            ),
            1,
        )

    def test_markdown_links_exist(self) -> None:
        link = re.compile(r"\[[^]]+\]\(([^)]+)\)")
        for path in ROOT.glob("*.md"):
            for target in link.findall(path.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(resolved.exists(), f"broken link in {path.name}: {target}")

    def test_no_publication_secrets_or_personal_paths(self) -> None:
        patterns = {
            "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
            "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
            "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),
            "GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b"),
            "Google key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
            "AWS key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
            "personal home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
            "authorization header": re.compile(r"Authorization\s*:\s*Bearer\s+\S+", re.I),
            "cookie": re.compile(r"\b(?:cookie|set-cookie)\s*[:=].{16,}", re.I),
            "credential URL": re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I),
            "secret query": re.compile(
                r"[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
                r"token|password|secret)=[^&\s]{8,}",
                re.I,
            ),
            "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            "private IP": re.compile(
                r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
                r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
            ),
            "cyrillic text": re.compile(r"[\u0400-\u04FF]"),
        }
        files = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.suffix != ".pyc"
            and path.name != ".DS_Store"
        ]
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in patterns.items():
                self.assertIsNone(pattern.search(text), f"{label} in {path.relative_to(ROOT)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
