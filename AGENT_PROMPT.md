# Reproduction Prompt for a Coding Agent

Copy the text below into a coding agent with access to this repository.

```text
Reproduce one or both model-controlled harness benchmark series from this repository.

Safety and evidence rules:
- Read README.md, benchmark/cases.json, benchmark/providers.json, and benchmark/run.py before doing anything.
- Do not start a paid model or harness run until the user explicitly approves the selected series or case, harnesses, run count, and likely cost.
- Never print, copy, or commit credentials. Use existing CLI authentication or environment variables.
- Do not edit benchmark/results.json or reinterpret historical benchmark results.
- Treat benchmark/results.json as the authoritative curated dataset, benchmark/cases.json as the authoritative task definition, and benchmark/providers.json as the authoritative provider/model route definition.
- Keep the initial Claude Code Sonnet 5 xhigh series visible as cross-model history. Do not merge it into the Muse-controlled comparison.
- Do not treat raw or generated output as ground truth until model status, contamination, verifier result, and patch scope are checked.
- Preserve the benchmark's practical purpose: compare lean daily-use harness configurations in the user's own environment, not artificial empty installations.
- Keep the control surface comparable. The published setup used a minimal system prompt and exactly two MCP integrations per harness, removed unused configuration, stayed close to defaults, and retained only daily-use optimizations.

Workflow:
1. Run the free local checks:
   python3 benchmark/test.py
   python3 benchmark/run.py --help
   python3 benchmark/parse.py --help

2. Confirm that Git, Python 3.10+, Bun, the selected harness CLIs, and provider authentication are available. If the selected profile uses OpenCodex, configure and start it:
   ocx setup
   ocx start
   ocx ready --wait --timeout 30
   ocx status

3. If OpenCode is selected, confirm that its `yolo` primary agent exists with non-interactive permissions and that the tracked command includes `--agent yolo --auto`. Keep `external_directory` denied so the harness cannot escape its worktree.

4. Ask the user which provider profile and harnesses to test. After approval for the small real requests, smoke every selected harness before a full benchmark:
   python3 benchmark/run.py smoke \
     --profile muse-commandcode \
     --harness pi \
     --harness codex \
     --harness claude \
     --harness opencode2 \
     --output runs/smoke-muse

   Repeat smoke with `gpt-openai` and the selected GPT harnesses before the GPT series.

   Require `valid_run`, `response_valid`, and `scope_valid` to be true and `model_status` to be `VALID`. A smoke pass validates CLI authentication, routing, actual-model evidence, parsing, the exact `HI` response, and no repository changes; it does not validate coding performance.

5. Clone and prepare the pinned target if it is not already available:
   git clone https://github.com/alvinunreal/oh-my-opencode-slim.git ../oh-my-opencode-slim
   git -C ../oh-my-opencode-slim checkout 9dbf2de015aec093e44273e6411c1392705b2f4d
   bun install --cwd ../oh-my-opencode-slim

6. Ask the user which series and harnesses to run. A complete reproduction requires only one command per series. After explicit approval, use this shape for Muse:
   python3 benchmark/run.py muse \
     --profile muse-commandcode \
     --repo ../oh-my-opencode-slim \
     --harness pi \
     --harness codex \
     --harness claude \
     --harness opencode2 \
     --output runs/muse

   Use `gpt` with the `gpt-openai` profile for the GPT series. Do not invoke all six cases manually unless the user requested targeted reruns. Omit `--runs` to preserve the published per-case defaults; an explicit `--runs` value overrides every case in the selected series.

7. If the user provides an existing raw log, parse it without running a model:
   python3 benchmark/parse.py path/to/raw.jsonl --format pi --out normalized.json

8. Read the series-level summary plus each case summary. Report, for every run: profile, case, wall time, fresh/cached/total input, tool calls, tests, patch, verifier result, accounting_scope, model_status, contamination, and valid_run.

9. Stop and mark the run invalid if the actual model is missing or mismatched, proxy routing cannot be request-anchored, the verifier fails, the run times out, or it accesses the source checkout outside its worktree.

If the user selects OpenCode Go, OpenRouter, or another provider, copy benchmark/providers.json to benchmark/providers.local.json and update the provider, model, cli_model, command, and verification fields consistently. Never silently substitute a model or treat a different model as a reproduction of the published controlled series.

Do not make broader benchmark claims from a new run unless the data and sample size support them.
```
