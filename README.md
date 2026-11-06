# Personal coding-model eval suite

A small, self-contained benchmark for comparing local coding models on one machine.
No Docker, no third-party Python packages, Windows-friendly.

- **34 tasks**, roughly **30–60 minutes** for the full suite on a ~13 tok/s dense model.
- Six categories: codegen, debugging, multi-file edits, tool calls, terminal agent work,
  instruction/long-context.
- Tasks are freshly authored in the style of recent benchmarks (SWE-bench-style repo
  edits, DebugBench-style fixes, BFCL-style tool calls, terminal-agent tasks). Nothing
  is downloaded at run time and no out-of-date datasets such as HumanEval are used.
- Every fixture is verified by `selftest`: the shipped oracle must pass, and the
  shipped starting state must fail.

## Requirements

- Python 3.10+ (`python` on `PATH`).
- A llama.cpp `llama-server` or router exposing an OpenAI-compatible API.
- Windows is the primary target; the harness itself is OS-neutral except for the
  terminal tasks, which use PowerShell.

## Quick start

Start a plain server so the model stays loaded and Prometheus metrics are available:

```powershell
llama serve -m "D:\Models\Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf" `
    -c 65536 -ctk q8_0 -ctv q8_0 -fitt 512 --metrics `
    --host 127.0.0.1 --port 9931
```

Then:

```powershell
cd D:\llm-evals
python bench.py list
python bench.py selftest
python bench.py run --label dense-iq2s --preset full
```

Run the other model, then compare:

```powershell
python bench.py run --label moe --preset full
python bench.py compare results\<dense>.json results\<moe>.json
```

Results are written to `results/` as JSON, including per-task token counts, wall
time, failure detail, and the model's raw output trace.

### Using the llama.cpp desktop router

If something is already listening on the port and `/props` reports `"role":"router"`,
the server loads model presets on demand. Pass the exact id from `/v1/models`:

```powershell
python bench.py run --model Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp --label dense
```

Two caveats:

1. The router can reload the model for each request, which inflates wall times. For
   timing comparisons, use a direct `llama serve` (or keep the instance resident).
2. The router's `/metrics` endpoint is not the per-model one, so `decode t/s` will be
   blank. Token counts and `tokens/pass` still work.

## Commands

| command | purpose |
| --- | --- |
| `python bench.py list` | show all tasks and categories |
| `python bench.py selftest` | prove each fixture has a working oracle and a failing start state |
| `python bench.py run ...` | run tasks against the server |
| `python bench.py compare A.json B.json` | side-by-side pass rate and token efficiency |

Useful `run` flags:

```text
--label NAME           name saved in the result file
--model ID             model id sent to the server (default: local)
--base-url URL         default: http://127.0.0.1:9931
--preset quick|full    quick = 8 tool calls + 4 codegen + 4 debug tasks
--category a,b         filter by category
--id tc-01,dbg-03      run exact task ids
--limit N              take the first N selected tasks
--attempts N           edit-mode repair attempts (default: 2)
--min-output-budget N  raise edit/agent max_tokens to at least N (reasoning mode)
--timeout SECONDS      per-request timeout (default: 900)
--temperature F        override the sampler temperature
--top-p F              override top_p
--verbose              print failure detail
--keep                 keep temporary workspaces
```

Recommended first session:

```powershell
python bench.py run --label dense --preset quick --attempts 2 --verbose
```

Then run the same `--preset quick` command with the MoE model and compare.

## What is measured

- **pass / tests** per category and overall.
- **prompt tokens** and **output tokens** from the server's `usage` block.
- **tokens/pass**: `(prompt + output) / passed tests`. This is the token-efficiency
  number; lower is better for a given pass rate.
- **s per test** and total wall time.
- **decode t/s**, scraped from `/metrics` when a plain server exposes
  `llamacpp:tokens_predicted_total` and `llamacpp:tokens_predicted_seconds_total`.
  Keep the server otherwise idle during a run; the metrics are global counters.

The sampler is pinned to temperature 1.0, top_p 0.95, top_k 20, min_p 0.0 so both
models are compared under the same conditions. Tool-call tasks disable thinking
(`chat_template_kwargs: {"enable_thinking": false}`) because the task is the call
itself, not a long chain of thought. Edit and terminal tasks leave thinking enabled.

### Running with reasoning enabled

Thinking tokens count against each task's `max_tokens`. If the server runs with
reasoning on, cap the thinking and raise the output budgets:

```powershell
llama serve ... --no-reasoning-preserve --reasoning-effort medium --reasoning-budget 1024
python bench.py run --label dense --preset quick --min-output-budget 4096 --attempts 2 --verbose
```

Use the same reasoning flags for both models. Without the reasoning budget, a small
model can spend the whole task budget thinking and never emit the fix.

## Task categories

| category | n | modes | what it exercises |
| --- | --- | --- | --- |
| `codegen` | 6 | edit | implement a module from a precise spec |
| `debug` | 8 | edit | fix a failing test suite with a realistic bug |
| `multifile` | 6 | edit | keep model/repo/api, imports, callers and shared helpers consistent |
| `toolcalls` | 8 | tools | single/parallel calls, typed args, irrelevance, clarification, multi-turn |
| `terminal` | 4 | agent | inspect a workspace, run commands, edit files, verify |
| `instruction` | 2 | text | strict formatting and a long-context bug hunt |

### Edit mode

The model is asked for **whole file blocks**:

```text
=== FILE: path/to/file.py ===
<entire file>
=== END FILE ===
```

It gets up to `--attempts` tries. After a failed attempt the test output is fed back
and it is asked for corrected file blocks. `tests.py` and `verify.py` are restored
from the original fixture after every attempt, so a model cannot pass by rewriting
the spec.

### Tool-call mode

The model gets the JSON schemas for the tools named by the task and must produce the
expected call(s). Some tasks require no call, some require a clarifying question,
and one requires a second turn that consumes the tool result.

### Terminal-agent mode

The model gets `list_files`, `read_file`, `write_file`, `run_command` and `finish`.
`run_command` executes PowerShell in a temporary workspace. After the loop the
harness runs `verify.py`. Test files are read-only to the agent.

`run_command` has a deny list for destructive and network commands, and paths are
confined to the workspace. This is a safety net, not a sandbox: run the suite on a
disposable machine/account if you do not trust the model.

## Adding your own tasks

Append a dict to the relevant module in `tasks/`. The common fields are:

```python
{
    "id": "cg-07",
    "category": "codegen",
    "title": "...",
    "difficulty": "medium",
    "mode": "edit",              # edit | tools | agent | text
    "prompt": "...",
    "files": {"solution.py": "...", "tests.py": "..."},
    "oracle": {"solution.py": "... complete working version ..."},
    "fixes": [("old text", "new text")],   # optional, applied before oracle
    "max_tokens": 2000,
}
```

For `tools` tasks add `tools` (schema names) and `expect`; for `agent` tasks add a
`verify.py`; for `text` tasks add `exact_lines` or `line_rules` plus `oracle_text`.
Run `python bench.py selftest` after every addition.

## Files

```text
bench.py              harness: list / selftest / run / compare
tasks/codegen.py      6 codegen tasks
tasks/debug.py        8 debugging tasks
tasks/multifile.py    6 multi-file tasks
tasks/toolcalls.py    tool schemas + 8 tool-call tasks
tasks/terminal.py     4 terminal-agent tasks
tasks/instruction.py  2 instruction/long-context tasks
results/              timestamped run JSON
```
