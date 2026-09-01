# Same Model, Different Harness

This repository asks one narrow question: **what changes when the model stays fixed and only the coding-agent harness changes?**

A harness is much more than a system prompt. It is the agent loop, tool API, context assembly, caching and compaction, permissions, subagents, provider protocol, retries, and session state wrapped around a model. Those layers determine what the model sees, which tools it calls, how much context moves through the system, and whether it stays inside the requested scope.

We ran this benchmark because Codex, Pi, Claude Code, and OpenCode felt noticeably different even when routed to the same model. The measurements confirmed that the harness can change the execution graph substantially.

The practical goal was personal: **find the most effective harness for the author's own environment and daily workflow**. This is therefore not a comparison of pristine default installations. Before the measured runs, the author experimented with each harness, returned it close to its defaults, removed unnecessary configuration, and kept only optimizations that were useful in normal work. Every tested harness then used a minimal system prompt and the same two MCP integrations. The benchmark compares lean, ready-to-use daily configurations under a controlled model, which is also the most useful way to reproduce it: test the harnesses you would actually keep using, while holding the model and task constant.

> 📑 **Quick Links:** [Full Results](RESULTS.md) · [Cases](benchmark/cases.json) · [Provider Profiles](benchmark/providers.json) · [Curated Dataset](benchmark/results.json) · [Agent Prompt](AGENT_PROMPT.md)

## Headline results

The cleanest controlled coding comparison was Task 4: the same synthetic regression, the same pinned repository revision, and the same hard-verified Muse model.

| Harness | Mean wall time | Mean total input | Correctness |
|---|---:|---:|---:|
| Pi | 104.0 s | 267k | 2/2 |
| Codex + OpenCodex | 110.4 s | 446k | 2/2 |
| Claude Code + OpenCodex | 112.5 s | 444k | 2/2 |
| OpenCode beta | — | — | 0/2; tested setup failed |

In the separate GPT coding series, all harnesses found the fix, but their execution cost differed sharply.

| Harness | Median wall time | Median total input | Correctness |
|---|---:|---:|---:|
| Codex | 107.7 s | 505k | 3/3 |
| Pi | 141.0 s | 525k | 3/3 |
| OpenCode stable | 274.4 s | 1.80M | 3/3 |
| OpenCode beta | 402.8 s | at least 1.02M | 3/3 |

OpenCode beta used built-in `explore` and `general` subagents in this task. Its parent stream does not include complete child-session token usage, so that token figure is a lower bound. The original parser also missed OpenCode test commands; the corrected evidence confirms that the tests did run.

### The initial Claude route was Sonnet 5

The first Claude Code pass across **all four Muse-series tasks** silently routed to fallback **Sonnet 5 with `xhigh` thinking**, not Muse Spark 1.2. Those results are preserved in [RESULTS.md](RESULTS.md) as an explicitly cross-model historical series; they are not used as harness-only evidence.

Tasks 3 and 4 were later rerun with requested, actual, and proxy model verification. Both reruns used Muse Spark 1.2 and are the Claude rows in the controlled comparison above. This distinction matters: deleting the Sonnet series would hide what happened, while mixing it into the Muse comparison would invalidate the experiment.

## What we concluded

- The same model in different harnesses produced materially different execution graphs and context throughput.
- Pi processed about 40% less cumulative input than Codex and Claude in the controlled Task 4 runs while producing the same fix (cumulative context throughput, not explained by turn count alone where both Pi and Claude had 12 model calls in run 2).
- Codex and Claude showed strong scope restraint. Task 3 was specifically a restraint test because the requested logger defect was already fixed.
- Pi, Codex, and Claude had similar Task 4 latency at this sample size.
- OpenCode stable was substantially less efficient in the GPT coding task.
- OpenCode beta failed the orchestration/worktree boundary in the tested setup. That is an observation about this configuration, not proof of a universal upstream bug.

For our own workflow, these results were enough to remove OpenCode from the stack. That is a local engineering decision, not a claim that everyone should do the same.

## What was tested

The benchmark contains two model-controlled series:

- GPT-5.6 Luna: read-only repository navigation and a coding fix with tests, comparing Codex, Pi, OpenCode stable, and OpenCode beta.
- Muse Spark 1.2 Contributor: web research, repository navigation, scope restraint, and a controlled regression, comparing Pi, Codex, Claude Code, and OpenCode beta where the routing evidence was valid.

Repository tasks used `oh-my-opencode-slim` at commit `9dbf2de015aec093e44273e6411c1392705b2f4d`. Each run used a detached Git worktree. The runner records wall time, normalized token usage, tool calls, tests, patch scope, contamination, and requested-versus-actual model status.

### Why Muse?

Muse was chosen as a **non-GPT control**, not because this is a Muse review. The GPT series alone leaves an obvious alternative explanation: GPT might perform especially well inside Codex because the model and harness were designed by the same vendor. Repeating the comparison with one non-GPT model helps separate that possibility from harness behavior.

Muse Spark 1.2 Contributor was also practical for repeated agent runs: it exposes a large context window and inexpensive input, output, and cache-read usage. The author accessed it through **CommandCode** using the upstream model ID `commandcode/meta/muse-spark-1.2-contributor`. See the official [CommandCode model catalog](https://commandcode.ai/models) and [pricing page](https://commandcode.ai/docs/resources/pricing-limits).

The model remains a control variable inside each series. GPT rows and Muse rows must not be combined into a model ranking.

### Configuration philosophy

The harnesses were deliberately kept lean, but they were not artificially reset to empty installations:

- each harness had a minimal system prompt and exactly two MCP integrations;
- experimental settings and unused integrations were removed before measurement;
- configurations were returned close to defaults, then only proven daily-use optimizations were retained;
- production-like memory/Deja stayed enabled intentionally because it was part of the author's real workflow;
- provider, model, task, and validation rules were pinned for each controlled series.

This makes the results environment-specific by design. The repository is a method for choosing an efficient harness in your own working setup, not a claim that one universal stock configuration wins everywhere. If you reproduce it, keep the comparison fair but use the lean configurations you would genuinely use every day.

## Run it

### Requirements

For a **complete reproduction of the author's setup**, plan for:

| Requirement | Why it is needed |
|---|---|
| ChatGPT Plus or higher | Practical minimum for the GPT control series and Codex CLI runs. Plus currently costs [$20/month](https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus); Codex availability and limits vary by plan. |
| [CommandCode GOAT](https://commandcode.ai/docs/plans/goat) | **Author's Muse provider and plan. The complete subscription costs $10/month** and supplies the `commandcode/meta/muse-spark-1.2-contributor` route used in the published runs. |
| [OpenCode Go](https://opencode.ai/go) | **$10/month alternative** to CommandCode GOAT. It includes Muse Spark 1.2 Contributor in supported regions, but uses a different provider/model route. |
| Python 3.10+, Git, and Bun | Git provides isolated worktrees; Bun installs and tests the pinned TypeScript target repository. |
| macOS or Linux | The runner uses POSIX process groups to terminate timed-out harnesses and their child processes. |
| Selected harness CLIs | Install only the runtimes you intend to compare: Codex CLI, Pi, Claude Code, OpenCode stable, or OpenCode beta. |
| OpenCodex | Required for the author's proxy-routed Codex and Claude configurations. It must be configured **and running** so the runner can verify the actual upstream model from proxy logs. |

The author's practical subscription baseline was therefore **ChatGPT Plus ($20/month) + CommandCode GOAT ($10/month)**. OpenCode Go can replace GOAT for $10/month, but it does not reproduce the author's exact provider route.

### Observed token-equivalent cost

The local normalized logs used for this publication contain the following billable token volume:

| Controlled series | Included runs | Fresh input | Cache read | Output | Applied tariff per 1M tokens | Estimated usage cost |
|---|---:|---:|---:|---:|---|---:|
| GPT-5.6 Luna | 24 | 1.569M | 12.428M | 68.9k | $1.25 input / $0.15 cache / $5 output | **$4.17** |
| Muse Spark 1.2 Contributor | 37 | 2.098M | 6.319M | 251.2k | $0.10 input / $0.002 cache / $0.20 output | **$0.27** |

These are token-equivalent estimates, not additional subscription invoices. The GPT figure uses the benchmark-period Luna tariff already used by this repository; the Muse rates come from the [CommandCode model catalog](https://commandcode.ai/models). The Muse total excludes the original Claude fallback rows because they ran on Sonnet 5, not Muse. Both estimates are lower bounds: OpenCode child-session accounting and failed runs can omit usage.

### Configure and start OpenCodex

The `muse-commandcode` profile routes Codex and Claude through OpenCodex. Set it up once, start it before smoke tests, and wait for readiness:

```bash
ocx setup
ocx start
ocx ready --wait --timeout 30
ocx status
```

Configure the CommandCode account/model during `ocx setup`. The runner uses `ocx observe logs --json` after each routed run; missing logs, an unanchored request, or a fallback model makes the run invalid.

### Configure the OpenCode `yolo` agent

The OpenCode profiles invoke `--agent yolo --auto`. Create that primary agent in the configuration used by each OpenCode installation so benchmark runs never stop for interactive approvals. Merge this agent into your existing `opencode.json` rather than overwriting unrelated settings:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "agent": {
    "yolo": {
      "description": "Non-interactive benchmark agent",
      "mode": "primary",
      "permission": {
        "*": "allow",
        "external_directory": "deny"
      }
    }
  }
}
```

`external_directory` remains denied because every repository benchmark must stay inside its detached worktree. The `--auto` flag approves otherwise-ask permissions, while explicit deny rules remain enforced. See the official [OpenCode permissions](https://opencode.ai/docs/permissions/) and [agent configuration](https://opencode.ai/docs/agents/) documentation.

#### Muse provider alternatives

You do not have to use CommandCode, but changing the provider requires changing the model route and verification configuration:

- **CommandCode GOAT — author's exact $10/month plan:** select the tracked `muse-commandcode` profile and keep `commandcode/meta/muse-spark-1.2-contributor`.
- **OpenCode Go — $10/month alternative:** copy the provider file and change the provider/model route to `opencode-go/muse-spark-1.2-contributor` for every selected harness.
- **OpenRouter — bring-your-own-provider alternative:** select an available model from the [OpenRouter catalog](https://openrouter.ai/models), then replace the provider and model ID consistently for every harness. If Muse Contributor is unavailable and you choose another model, that is a new controlled series, not a reproduction of the published Muse results.

Provider/model commands and routing checks now live in [`benchmark/providers.json`](benchmark/providers.json); benchmark prompts remain in [`benchmark/cases.json`](benchmark/cases.json). The runner does not silently rewrite routes. To use a different provider, copy the provider file, update each selected harness entry, and pass it with `--providers` and `--profile`:

```bash
cp benchmark/providers.json benchmark/providers.local.json
# Edit benchmark/providers.local.json with one consistent provider/model route.
python3 benchmark/run.py muse \
  --providers benchmark/providers.local.json \
  --profile muse-opencode-go \
  --repo ../oh-my-opencode-slim \
  --harness pi \
  --harness codex \
  --output runs/muse
```

Create the `muse-opencode-go` profile in the local copy by duplicating `muse-commandcode` and changing `provider`, `model`, `cli_model`, commands, and model-verification rules for all selected harnesses. `benchmark/providers.local.json` is ignored by Git. Keep credentials in standard environment variables or CLI login; never put tokens in provider files, logs, or commits.

First run the free local checks:

```bash
python3 benchmark/test.py
python3 benchmark/run.py --help
python3 benchmark/parse.py --help
```

Then run one tiny smoke command per model profile. Each command makes one real model request per selected harness, expects exactly `HI`, verifies the requested-versus-actual model evidence, checks parsing, and confirms that the harness did not edit its disposable repository:

```bash
python3 benchmark/run.py smoke \
  --profile gpt-openai \
  --harness codex \
  --harness pi \
  --harness opencode \
  --harness opencode2 \
  --output runs/smoke-gpt

python3 benchmark/run.py smoke \
  --profile muse-commandcode \
  --harness pi \
  --harness codex \
  --harness claude \
  --harness opencode2 \
  --output runs/smoke-muse
```

Select only harnesses you have installed and configured. Smoke requests are small but real and may consume plan quota or provider credit. Passing smoke proves CLI authentication, routing evidence, log parsing, exact response, and no-file-change behavior; it does not prove coding correctness or tool behavior.

Clone and prepare the pinned target:

```bash
git clone https://github.com/alvinunreal/oh-my-opencode-slim.git ../oh-my-opencode-slim
git -C ../oh-my-opencode-slim checkout 9dbf2de015aec093e44273e6411c1392705b2f4d
bun install --cwd ../oh-my-opencode-slim
```

### Run the complete benchmark

After setup and smoke, the complete benchmark is **two commands: one GPT series and one Muse series**. Each series automatically runs all of its cases with the default run counts from `benchmark/cases.json`:

```bash
python3 benchmark/run.py gpt \
  --profile gpt-openai \
  --repo ../oh-my-opencode-slim \
  --harness codex \
  --harness pi \
  --harness opencode \
  --harness opencode2 \
  --output runs/gpt

python3 benchmark/run.py muse \
  --profile muse-commandcode \
  --repo ../oh-my-opencode-slim \
  --harness pi \
  --harness codex \
  --harness claude \
  --harness opencode2 \
  --output runs/muse
```

`--harness` remains explicit so the runner cannot spend quota on every installed CLI accidentally. When several harnesses are selected, their order rotates between rounds. The runner stops immediately on the first invalid run.

The default call count is explicit:

| Series | Cases | Runs per harness | Harnesses in full command | Total real calls |
|---|---:|---:|---:|---:|
| `gpt` | 2 | 3 + 3 = 6 | 4 | 24 |
| `muse` | 4 | 3 + 3 + 3 + 2 = 11 | 4 | 44 |

Smoke calls are separate: four for the complete GPT profile and four for the complete Muse profile. Passing `--runs 2` overrides every case in the selected series; for example, the full four-harness Muse series would then make `4 cases × 2 runs × 4 harnesses = 32` calls.

### Cases and targeted reruns

| Case | What it measures | Supported harnesses | Default runs |
|---|---|---|---:|
| `smoke` | Provider, authentication, parser, and actual-model connectivity | Harnesses in the selected profile | 1 |
| `gpt-readonly` | Read-only repository navigation | `codex`, `pi`, `opencode`, `opencode2` | 3 |
| `gpt-coding` | Coding fix and relevant tests | `codex`, `pi`, `opencode`, `opencode2` | 3 |
| `muse-web` | Web research and source accuracy | `pi`, `codex`, `claude`, `opencode2` | 3 |
| `muse-repo` | Repository architecture navigation | `pi`, `codex`, `claude`, `opencode2` | 3 |
| `muse-restraint` | Scope discipline when no fix is needed | `pi`, `codex`, `claude`, `opencode2` | 3 |
| `muse-regression` | Controlled coding regression | `pi`, `codex`, `claude`, `opencode2` | 2 |

Exact prompts, target revision, timeouts, mutations, and test commands live in [`benchmark/cases.json`](benchmark/cases.json). Provider routes, CLI commands, control models, and actual-model verification rules live in [`benchmark/providers.json`](benchmark/providers.json). Inspect both files before spending provider credits.

To rerun only one case or one harness, use the case ID directly. `--harness` is deliberately required so the script cannot start every paid harness by accident:

```bash
python3 benchmark/run.py muse-regression \
  --profile muse-commandcode \
  --repo ../oh-my-opencode-slim \
  --harness pi \
  --runs 2 \
  --output runs/muse-regression-pi
```

For a targeted comparison, repeat `--harness` for every runtime you want to compare. The runner rotates their execution order between rounds:

```bash
python3 benchmark/run.py muse-regression \
  --profile muse-commandcode \
  --repo ../oh-my-opencode-slim \
  --harness pi \
  --harness codex \
  --harness claude \
  --runs 2 \
  --output runs/muse-regression
```

These commands make real model calls. Stop before this step if the selected providers, run count, or expected cost have not been approved.

### Inspect the output

Each series writes an aggregate `summary.json` plus one directory per case. Every case also has its own summary and per-run artifacts:

```text
runs/muse/
├── summary.json
├── muse-web/
│   ├── summary.json
│   └── pi-run1.jsonl
├── muse-repo/
├── muse-restraint/
└── muse-regression/
    ├── pi-run1.stderr
    ├── pi-run1.patch
    ├── pi-run1.json
    └── codex-run1.routing.json
```

- `*.jsonl` is the raw harness log;
- `*.stderr` contains CLI diagnostics;
- `*.patch` is the resulting repository diff;
- the per-run `*.json` contains normalized metrics and validation status;
- `*.routing.json` records proxy model verification where required;
- the series-level `summary.json` combines every completed case;
- each case-level `summary.json` contains only that case.

A benchmark run is valid only when `valid_run` is `true`, `model_status` is `VALID`, configured tests pass, no timeout occurs, and `contaminated` is `false`. Smoke also requires `response_valid` and `scope_valid` to be `true`. The runner exits non-zero on a failed run.

### Parse an existing log

Parsing does not call a model:

```bash
python3 benchmark/parse.py runs/muse/muse-regression/pi-run1.jsonl \
  --format pi \
  --out runs/muse/muse-regression/pi-run1-normalized.json
```

Supported formats are `codex`, `pi`, `claude`, `opencode`, and `opencode2`.

A normalized result has this shape (illustrative values):

```json
{
  "harness": "pi",
  "fresh_input": 100,
  "cache_read": 300,
  "total_input": 400,
  "tool_calls": 2,
  "test_commands": ["bun test src/example.test.ts"],
  "actual_models": ["provider/model"],
  "model_status": "VALID",
  "accounting_scope": "complete"
}
```

## Reading normalized usage

Provider APIs report tokens differently, so the parser normalizes only what the logs actually expose.

| Field | Meaning |
|---|---|
| `fresh_input` | Newly processed input. For Claude this includes `cache_creation_input_tokens`; for Codex it is total input minus cached input. |
| `cache_read` | Input served from cache. |
| `total_input` | Fresh input plus cache reads, except Codex where the reported total already includes cached input. |
| `cache_hit_pct` | `cache_read / total_input`. |
| `final_context` | Last reported context size when the harness exposes it. It is not available from normal Codex exec JSON. |
| `wall_time` | End-to-end elapsed time measured by the runner. |
| `accounting_scope` | `complete` or `parent_only`; the latter warns that child-session usage may be absent. |
| `model_status` | `VALID` only when the observed model matches the requested control. Missing evidence and fallback are hard failures. |
| `contaminated` | Whether the run accessed the source checkout outside its isolated worktree. |

Tool-call counts are harness-log events, not guaranteed to represent identical provider operations. Output and reasoning tokens are included where the harness exposes them but should not be assumed directly comparable across protocols.

## Repository map

- [RESULTS.md](RESULTS.md): full verified tables, the Sonnet fallback history, and caveats.
- [benchmark/results.json](benchmark/results.json): authoritative curated numbers and environment metadata.
- [benchmark/cases.json](benchmark/cases.json): prompts, pinned target, mutations, and verifier commands.
- [benchmark/providers.json](benchmark/providers.json): editable provider/model profiles, harness commands, prices, and routing checks.
- [benchmark/run.py](benchmark/run.py): isolated benchmark runner.
- [benchmark/parse.py](benchmark/parse.py): standalone log normalizer.
- [benchmark/test.py](benchmark/test.py): dependency-free parser, data, link, and publication-safety checks.
- [AGENT_PROMPT.md](AGENT_PROMPT.md): an English copy-paste prompt for another coding agent.

Raw benchmark sessions are intentionally not published: the normalized curated data is sufficient for the documented results and avoids leaking persisted conversations or machine-local context.

## Limitations

- The number of runs is small.
- Production-like memory/Deja remained enabled intentionally because it was part of the measured workflow.
- Task 3 is a scope-restraint audit, not a normal latency benchmark.
- Task 4 used a synthetic mutation that may be easier than an unknown real-world bug.
- OpenCode child-session accounting can be incomplete.
- Results describe the tested versions, providers, prompts, and configuration, not permanent universal properties of any harness.

## License

MIT. See [LICENSE](LICENSE).
