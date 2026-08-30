# Benchmark Results & Quantitative Metrics

> **Evaluation Principle:** The AI model is held constant as the control variable. The tables evaluate the surrounding **agent harness runtime** (tool execution, context compaction, state tracking, cache efficiency, and workspace boundaries). All benchmark metric tables reflect the canonical dataset in [`benchmark/results.json`](benchmark/results.json); API costs and code diffs are calculated estimates and ground-truth validation checks.

---

## 1. Phase A — GPT-5.6 Luna Control Suite

* **Fixed Model:** `openai/gpt-5.6-luna` (medium reasoning effort).
* **Target Repository:** [`oh-my-opencode-slim`](https://github.com/alvinunreal/oh-my-opencode-slim) (pinned baseline commit `9dbf2de015aec093e44273e6411c1392705b2f4d`).
* **Evaluation Scheme:** 3 rounds per harness in rotated execution order.

### 🔍 Task 1: Read-Only Repository Navigation (Median of 3 Runs)

*Goal: Locate `BackgroundJobBoard` lifecycle implementation and provide structured architectural analysis without modifying files.*

| Harness | Wall Time | Fresh Input | Total Input | Cache Hit % | Correctness | Status |
|---|---:|---:|---:|---:|:---:|:---:|
| **Codex** | **37.33s** | **38.9k** | 179.4k | 78.3% | 3/3 | Verified |
| **Pi** | 40.85s | 59.7k | 170.0k | 64.5% | 3/3 | Verified |
| **OpenCode beta** | 41.07s | 46.4k | **167.2k** | 58.6% | 3/3 | Verified |
| **OpenCode stable** | 80.02s | 98.2k | 562.5k | 81.4% | 3/3 | Verified |

---

### 💻 Task 2: Coding Bugfix + Unit Tests (Median of 3 Runs)

*Goal: Resolve an alias counter memory leak in `BackgroundJobBoard`, preserve public API, add/update covering unit tests, and verify tests pass.*

| Harness | Wall Time | Fresh Input | Total Input | Cache Hit % | Correctness | Status |
|---|---:|---:|---:|---:|:---:|:---:|
| **Codex** | **107.73s** | 50.3k | **505.4k** | 90.1% | 3/3 | Verified |
| **Pi** | 140.96s | **44.2k** | 525.4k | 90.9% | 3/3 | Verified |
| **OpenCode stable** | 274.43s | 109.4k | 1797.1k | 93.9% | 3/3 | Verified |
| **OpenCode beta** | 402.75s | 79.8k* | 1015.4k* | 91.4%* | 3/3 | Wall time valid* |

> [!NOTE]
> `*` **OpenCode Beta Subagent Accounting:** OpenCode beta autonomously spawned built-in `explore` / `general` subagents during the coding task. Child-session tokens are omitted from the parent JSON stream, so token metrics represent a lower bound while wall-clock time is fully valid.

---

### 💰 Estimated API Cost Comparison (Coding Task — Calculated Estimate)

Calculated estimates using standard control tier pricing assumptions ($1.25 / 1M input, $0.15 / 1M cache read, $5.00 / 1M output). Provider pricing varies:

| Harness | Estimated Cost / Task | Relative Cost vs. Leader | Cost Assessment |
|---|---:|:---:|:---:|
| **Codex** | **~$0.0246** | **1.00x** (Baseline) | Optimal |
| **Pi** | **~$0.0247** | **1.004x** (+0.4%) | Optimal |
| **OpenCode stable** | **~$0.0642** | **2.61x** (+161%) | High Cost |

---

## 2. Phase B — Non-GPT Control Suite (`Muse Spark 1.2`)

* **Requested Control Model:** `meta/muse-spark-1.2-contributor` (CommandCode / OpenCodex upstream). The initial Claude Tasks 1–4 were a documented `Sonnet 5 xhigh` fallback; verified Muse reruns replaced Claude Tasks 3–4 for controlled comparison.
* **Target Repository:** [`oh-my-opencode-slim`](https://github.com/alvinunreal/oh-my-opencode-slim) (`9dbf2de015aec093e44273e6411c1392705b2f4d`).

> [!NOTE]
> **Proxy Routing Audit:**<br>
> The initial Claude Code pass across Tasks 1–4 ran on the fallback model `Sonnet 5 xhigh`, not the requested Muse control. That historical series is preserved below as a cross-model observation. Claude Tasks 3 and 4 were subsequently rerun with hard proxy verification of `Muse Spark 1.2`; only those reruns participate in the strict model-controlled comparison.

---

### Initial series: Claude Code on `Sonnet 5 xhigh`

In the initial pass across all four tasks, Claude Code's proxy route fell back
to **`Sonnet 5` with `xhigh` extended thinking**. Pi, Codex, and OpenCode beta
continued to use `Muse Spark 1.2`. This accidental series is useful for describing
what actually happened, but it must not be interpreted as a harness-only result:
both the harness and model differ in the Claude column.

| Task | Pi (`Muse 1.2`) | Codex (`Muse 1.2`) | Claude Code (`Sonnet 5 xhigh`) | OpenCode beta (`Muse 1.2`) | Observation |
|---|---:|---:|---:|---:|---|
| Task 1: web research | **41.66s**; 48.9k input; 3/3 | 51.35s; 19.9k; 1/3 | 59.62s; 83.4k; 3/3 | 110.62s; 245.9k; 1/3 | Pi finished 18.0s before Claude; both were correct in all runs. |
| Task 2: repository navigation | 35.67s; 81.4k input | 42.52s; 174.8k | **29.08s**; 64.0k | 48.12s; 196.7k | Claude finished about 6.6s before Pi. |
| Task 3: scope restraint | **201.02s**; 120.5k input; 0 edits | 233.77s; 214.8k; 0 edits | 308.50s; 1.56M; **over-edited 2 files** | 422.25s; over-edited 2 files | Sonnet and OpenCode beta expanded scope; Pi and Codex stopped without edits. |
| Task 4: regression fix | 103.96s; 267.4k input; 2/2 | 110.42s; 446.4k; 2/2 | **88.62s**; 546.8k; 2/2 | 288.05s; 0/2 | Claude was about 15s faster than Pi, with higher context throughput. |

The initial Task 3 Claude run modified two files and added 182 lines even though
the requested defect was already fixed. In the replacement, Muse-verified Claude
runs, Claude correctly stopped without edits in 2/2 runs. The initial Task 4
Claude run was correct and faster, but its `Sonnet 5 xhigh` model makes it
ineligible for the strict Muse harness comparison.

---

### 🌐 Task 1: Web Research (Median of 3 Runs)

*Goal: Retrieve release facts, context limits, pricing, and terms for Muse Spark 1.2 Contributor via live web search.*

| Harness | Wall Time | Fresh Input | Total Input | Cache Hit % | Correctness | Verification Status |
|---|---:|---:|---:|---:|:---:|---|
| **Pi** | **41.66s** | 27.2k | 48.9k | 31.6% | **3/3** | Verified |
| **Codex + OpenCodex** | 51.35s | **19.8k** | **19.9k** | 0.0% | 1/3 (omissions) | Verified |
| **Claude Code + OpenCodex** | 59.62s | 27.5k | 83.4k | 68.6% | **3/3** | `Sonnet 5 xhigh` fallback; cross-model |
| **OpenCode beta** | 110.62s | 96.5k | 245.9k | 60.7% | 1/3 (omissions) | Verified |

---

### 🏛️ Task 2: Repository Architecture Navigation (Median of 3 Runs)

*Goal: Analyze background subagent lifecycle and job board synchronization without editing files.*

| Harness | Wall Time | Fresh Input | Total Input | Cache Hit % | Correctness | Verification Status |
|---|---:|---:|---:|---:|:---:|---|
| **Claude Code + OpenCodex** | **29.08s** | **33.9k** | **64.0k** | 26.5% | 3/3 | `Sonnet 5 xhigh` fallback; cross-model |
| **Pi** | 35.67s | 40.4k | 81.4k | 45.9% | 3/3 | Verified |
| **Codex + OpenCodex** | 42.52s | 64.2k | 174.8k | 67.7% | 3/3 (minor path issue) | Verified |
| **OpenCode beta** | 48.12s | 70.4k | 196.7k | 58.7% | 3/3 | Verified |

---

### 🛡️ Task 3: Scope Discipline & Restraint (Qualitative Behavioral Audit)

*Goal: Prompt requested fixing a file logger defect that was already resolved in the repository baseline. Correct behavior was to inspect, verify existing tests, and make **0 modifications**.*

| Harness | Evaluated Model | Action Taken | Result | Verification Status |
|---|---|---|:---:|---|
| **Codex + OpenCodex** | `Muse Spark 1.2` | **3/3 correctly verified and stopped with 0 edits** | **PASS (3/3)** | Verified |
| **Claude Code + OpenCodex** | `Muse Spark 1.2` | **2/2 correctly verified and stopped with 0 edits** | **PASS (2/2)** | Hard-verified proxy audit reruns |
| **Pi** | `Muse Spark 1.2` | 2/3 stopped with 0 edits; 1/3 added extra edge handling | **PARTIAL (2/3)** | Verified |
| **OpenCode beta** | `Muse Spark 1.2` | Modified 2 files; targeted shared root instead of worktree | **EXCLUDED** | Setup boundary failure |

> [!NOTE]
> **Task 3 is a Behavioral Audit, Not a Speed Ranking:**<br>
> Because harnesses took fundamentally different workload paths (stopping vs. editing code), Task 3 measures scope restraint and judgment rather than throughput latency.

---

### 🛠️ Task 4: Controlled Synthetic Regression (Mean of 2 Runs, n=2)

*Goal: Locate a synthetic configuration precedence inversion committed into a detached worktree, repair `paths.ts`, and update `paths.test.ts`.*

| Harness | Evaluated Model | Run 1 | Run 2 | Mean Wall Time | Mean Fresh Input | Mean Total Input | Cache Hit % | Correctness | Verification Status |
|---|---|---:|---:|---:|---:|---:|---:|:---:|---|
| **Pi** | `Muse Spark 1.2` | **71.37s** | 136.54s | **103.96s** | **61.8k** | **267.4k** | 77.0% | **2/2** | Verified |
| **Codex + OpenCodex** | `Muse Spark 1.2` | 77.63s | 143.20s | 110.42s | 76.0k | 446.4k | 83.0% | **2/2** | Verified |
| **Claude Code + OpenCodex** | `Muse Spark 1.2` | 96.10s | **128.81s** | 112.46s | 86.7k | 444.2k | 78.8% | **2/2** | Hard-verified proxy audit reruns |
| **OpenCode beta** | `Muse Spark 1.2` | 288.05s | TIMEOUT | — | — | — | — | 0/2 | Excluded (setup boundary failure) |

> [!IMPORTANT]
> **Key Finding on Parity & Efficiency (Task 4, n=2):**<br>
> Across 2 evaluated runs (n=2) under strictly verified model weights and prompts:
> 1. **Latency:** Pi, Codex, and Claude Code form a single tight latency group (**104s / 110s / 112s**), all producing the identical valid +6 line repair.
> 2. **Context Throughput:** **Pi required ~40% less total context throughput (267.4k vs ~445k)** due to leaner context assembly and compaction cycles.
