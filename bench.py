#!/usr/bin/env python3
"""
Personal eval suite for local coding models served by llama-server (OpenAI-compatible).

No Docker. No third-party packages. Windows-friendly.

  python bench.py list
  python bench.py selftest
  python bench.py run --label dense-iq2s --preset full
  python bench.py run --label moe --preset quick --category toolcalls
  python bench.py compare results/a.json results/b.json

The model server is assumed to be running, e.g.:

  llama serve -m D:\\Models\\Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf ^
      -c 65536 -ctk q8_0 -ctv q8_0 -fitt 512 --metrics ^
      --host 127.0.0.1 --port 9931

If you use the llama.cpp router instead (the page at /v1/models lists presets),
pass the exact model id and metrics will be skipped:

  python bench.py run --model Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp --label dense
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT))

FILE_BLOCK = re.compile(r"=== FILE:\s*(.+?)\s*===\r?\n(.*?)\r?\n?=== END FILE ===", re.S)
FENCE = re.compile(r"```[a-zA-Z0-9_+.#-]*\r?\n(.*?)```", re.S)

DEFAULT_SAMPLER = {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 20,
    "min_p": 0.0,
}

# Set with --model. A direct llama-server ignores this; a llama.cpp router
# (which exposes /v1/models and loads instances on demand) needs the exact id.
MODEL_NAME = "local"

EDIT_SYSTEM = """You are a senior software engineer working inside a repository.

Reply with the COMPLETE contents of every file you create or change, using exactly this format:

=== FILE: relative/path.py ===
<entire file content, no markdown fences>
=== END FILE ===

Rules:
- Output only file blocks. No commentary before or after.
- Always output the whole file, never a diff or a fragment.
- Use forward slashes in paths, relative to the repository root.
- Do not modify test files (tests.py, verify.py) - they define the specification.
"""

AGENT_SYSTEM = """You are a terminal agent working on a Windows machine.
You have tools: list_files, read_file, write_file, run_command, finish.

Method:
1. Inspect the workspace before changing anything.
2. Make minimal edits.
3. Run the tests to verify, and read the output carefully.
4. Call finish when the task is genuinely complete.

run_command executes Windows PowerShell in the workspace directory.
Use relative paths. Prefer `python verify.py` style commands.
"""

DENY_COMMAND = re.compile(
    r"(rm\s+-rf\s+/|Remove-Item\s+.*-Recurse\s+.*[A-Za-z]:\\|format\s+[a-zA-Z]:|"
    r"shutdown|Stop-Computer|Restart-Computer|reg\s+delete|net\s+user|"
    r"Invoke-WebRequest|curl\s|wget\s|pip\s+install|npm\s+install|git\s+push|"
    r"Start-Process|Set-ExecutionPolicy|schtasks)",
    re.I,
)


# ----------------------------------------------------------------------------- http

def api_base(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/v1"):
        b = b[:-3]
    return b


def post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ask(base: str, messages: list, max_tokens: int, sampler: dict, timeout: float,
        tools: list | None = None, extra: dict | None = None):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    payload.update(sampler)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if extra:
        payload.update(extra)
    t0 = time.time()
    resp = post_json(api_base(base) + "/v1/chat/completions", payload, timeout)
    dt = time.time() - t0
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    usage = resp.get("usage") or {}
    return msg, usage, dt


METRIC_KEYS = {
    "llamacpp:tokens_predicted_total",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:prompt_tokens_total",
    "llamacpp:prompt_tokens_cached_total",
}


def scrape_metrics(base: str):
    try:
        with urllib.request.urlopen(api_base(base) + "/metrics", timeout=5) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) == 2 and parts[0] in METRIC_KEYS:
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return out


# ----------------------------------------------------------------------------- workspaces

def write_files(ws: Path, files: dict) -> None:
    for rel, content in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")


def read_ws(ws: Path) -> dict:
    out = {}
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            try:
                out[str(p.relative_to(ws)).replace("\\", "/")] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass
    return out


def safe_rel(path: str):
    path = path.strip().replace("\\", "/")
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return None
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def run_cmd(cmd, cwd: Path, timeout: float = 120):
    if isinstance(cmd, str):
        args = [sys.executable, cmd] if cmd.endswith(".py") else cmd
    else:
        args = cmd
    try:
        p = subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)


# ----------------------------------------------------------------------------- model output parsing

def extract_files(text: str, default_path: str | None):
    found = {}
    for m in FILE_BLOCK.finditer(text or ""):
        rel = safe_rel(m.group(1))
        if rel:
            found[rel] = m.group(2)
    if found:
        return found
    fences = FENCE.findall(text or "")
    if len(fences) == 1 and default_path:
        return {default_path: fences[0]}
    return {}


# ----------------------------------------------------------------------------- modes

def mode_edit(task, base, sampler, timeout, attempts, workdir: Path, log):
    ws = Path(tempfile.mkdtemp(prefix=f"ev-{task['id']}-", dir=str(workdir)))
    files = dict(task.get("files") or {})
    write_files(ws, files)
    protected = set(task.get("protected") or ["tests.py", "verify.py"]) & set(files)

    messages = [{"role": "system", "content": EDIT_SYSTEM}]
    user = task["prompt"]
    if files:
        user += "\n\nCurrent repository:\n\n" + snapshot(files)
    messages.append({"role": "user", "content": user})

    test_cmd = task.get("test_cmd") or [sys.executable, "tests.py"]
    ptok = ctok = 0
    trace = []
    last_out = ""
    passed = False
    used = 0

    for attempt in range(1, attempts + 1):
        used = attempt
        msg, usage, dt = ask(base, messages, task.get("max_tokens", 1400), sampler, timeout)
        ptok += int(usage.get("prompt_tokens") or 0)
        ctok += int(usage.get("completion_tokens") or 0)
        content = msg.get("content") or ""
        trace.append({"attempt": attempt, "content": content, "dt": dt})

        written = extract_files(content, task.get("write_to"))
        if not written:
            last_out = "MODEL DID NOT EMIT ANY FILE BLOCKS"
        else:
            for rel, body in written.items():
                if rel in protected:
                    continue
                (ws / rel).parent.mkdir(parents=True, exist_ok=True)
                (ws / rel).write_text(body, encoding="utf-8", newline="\n")
            for rel in protected:            # never let a model rewrite the spec
                (ws / rel).write_text(files[rel], encoding="utf-8", newline="\n")
            rc, last_out = run_cmd(test_cmd, ws, timeout=120)
            if rc == 0:
                passed = True
                break

        log(f"      attempt {attempt}: fail")
        if attempt < attempts:
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "The tests still fail. Output was:\n\n" + last_out[-2500:] +
                    "\n\nFix the code. Reply with the complete corrected file blocks."
                ),
            })

    return {
        "passed": passed,
        "attempts": used,
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "detail": "" if passed else last_out[-1200:],
        "trace": trace,
        "workspace_files": read_ws(ws),
    }


def snapshot(files: dict) -> str:
    parts = []
    for rel, body in files.items():
        parts.append(f"=== FILE: {rel} ===")
        parts.append(body.rstrip("\n"))
        parts.append("=== END FILE ===")
    return "\n".join(parts)


def tool_specs(names: list) -> list:
    from tasks.toolcalls import TOOLS
    return [TOOLS[n] for n in names]


def mode_tools(task, base, sampler, timeout, attempts, workdir: Path, log):
    tools = tool_specs(task["tools"])
    messages = [{"role": "system", "content": task.get("system", "You are a helpful assistant with tools.")},
                {"role": "user", "content": task["prompt"]}]
    extra = {}
    if task.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}

    msg, usage, _ = ask(base, messages, task.get("max_tokens", 400), sampler, timeout,
                        tools=tools, extra=extra)
    ptok = int(usage.get("prompt_tokens") or 0)
    ctok = int(usage.get("completion_tokens") or 0)
    calls = norm_calls(msg)
    ok, why = check_tool_expect(task.get("expect", {}), calls, msg.get("content") or "")

    trace = [{"calls": calls, "content": msg.get("content"), "why": why}]

    if ok and task.get("followup"):
        fu = task["followup"]
        rid = (msg.get("tool_calls") or [{}])[0].get("id") or "call_1"
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": msg.get("tool_calls") or []})
        messages.append({"role": "tool", "tool_call_id": rid, "content": fu["result"]})
        msg2, usage2, _ = ask(base, messages, task.get("max_tokens", 400), sampler, timeout,
                              tools=tools, extra=extra)
        ptok += int(usage2.get("prompt_tokens") or 0)
        ctok += int(usage2.get("completion_tokens") or 0)
        text = (msg2.get("content") or "").lower()
        calls2 = norm_calls(msg2)
        missing = [s for s in fu.get("contains", []) if s.lower() not in text]
        ok = not missing and (not fu.get("no_more_calls") or not calls2)
        why += f" | followup missing={missing} calls2={[c['name'] for c in calls2]}"
        trace.append({"calls": calls2, "content": msg2.get("content"), "why": why})

    return {
        "passed": ok,
        "attempts": 1,
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "detail": why,
        "trace": trace,
        "workspace_files": {},
    }


def normalize_text(text: str) -> list:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def check_text(task, text: str):
    lines = normalize_text(text)

    if task.get("exact_lines") is not None:
        if lines != task["exact_lines"]:
            return False, f"expected exactly {task['exact_lines']!r}, got {lines!r}"

    rules = task.get("line_rules")
    if rules:
        if len(lines) != len(rules):
            return False, f"expected {len(rules)} lines, got {len(lines)}: {lines!r}"
        for i, (ln, rule) in enumerate(zip(lines, rules), 1):
            rx = rule.get("regex")
            if rx and not re.search(rx, ln):
                return False, f"line {i} does not match {rx!r}: {ln!r}"
            bad_list = rule.get("not_contains") or []
            if isinstance(bad_list, str):
                bad_list = [bad_list]
            for bad in bad_list:
                if bad in ln:
                    return False, f"line {i} must not contain {bad!r}: {ln!r}"

    if task.get("max_lines") and len(lines) > task["max_lines"]:
        return False, f"too many lines: {len(lines)}"
    for pat in task.get("forbid") or []:
        if re.search(pat, text or "", re.I):
            return False, f"forbidden pattern present: {pat!r}"
    for pat in task.get("must_match") or []:
        if not re.search(pat, text or "", re.I | re.S):
            return False, f"missing pattern: {pat!r}"
    return True, "format ok"


def mode_text(task, base, sampler, timeout, attempts, workdir: Path, log):
    messages = []
    if task.get("system"):
        messages.append({"role": "system", "content": task["system"]})
    messages.append({"role": "user", "content": task["prompt"]})

    extra = {}
    if task.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}

    msg, usage, dt = ask(base, messages, task.get("max_tokens", 500), sampler, timeout,
                         extra=extra)
    text = msg.get("content") or ""
    ok, why = check_text(task, text)
    return {
        "passed": ok,
        "attempts": 1,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "detail": "" if ok else why + "\n---\n" + text[:800],
        "trace": [{"content": text, "dt": dt, "why": why}],
        "workspace_files": {},
    }


def norm_calls(msg: dict) -> list:
    out = []
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        out.append({"name": fn.get("name") or tc.get("name"), "args": args or {}})
    return out


def _match(exp, act) -> bool:
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return False
        return all(k in act and _match(v, act[k]) for k, v in exp.items())
    if isinstance(exp, list):
        if not isinstance(act, list) or len(exp) != len(act):
            return False
        return all(_match(e, a) for e, a in zip(exp, act))
    if isinstance(exp, str) and isinstance(act, str):
        return exp.strip().lower() in act.strip().lower()
    return exp == act


def check_tool_expect(exp: dict, calls: list, content: str):
    names = [c["name"] for c in calls]
    if exp.get("no_tool"):
        if calls:
            return False, f"expected no tool call, got {names}"
        if exp.get("contains"):
            low = content.lower()
            missing = [s for s in exp["contains"] if s.lower() not in low]
            if missing:
                return False, f"answer missing {missing}"
        return True, "no tool call, answered directly"

    if exp.get("ask"):
        if calls:
            return False, f"expected clarification, got {names}"
        if not content.strip():
            return False, "empty reply, expected a clarifying question"
        return True, "asked for clarification"

    if not calls:
        return False, f"expected tool call(s) {exp.get('names') or exp.get('name')}, got none"

    if "calls" in exp:
        if len(calls) != len(exp["calls"]):
            return False, f"expected {len(exp['calls'])} calls, got {names}"
        for e, a in zip(exp["calls"], calls):
            if e["name"] != a["name"]:
                return False, f"expected {e['name']}, got {a['name']}"
            if "args" in e and not _match(e["args"], a["args"]):
                return False, f"{a['name']} args {a['args']} !~ {e['args']}"
        return True, "calls ok"

    want = exp.get("name")
    if want and names[0] != want:
        return False, f"expected {want}, got {names}"
    if "args" in exp and not _match(exp["args"], calls[0]["args"]):
        return False, f"args {calls[0]['args']} !~ {exp['args']}"
    return True, "call ok"


def exec_agent_tool(name: str, args: dict, ws: Path):
    if name == "list_files":
        rel = safe_rel(args.get("path") or ".") or "."
        base = ws / rel
        if not base.exists():
            return f"no such directory: {rel}"
        rows = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rows.append(str(p.relative_to(ws)).replace("\\", "/"))
        return "\n".join(rows[:200]) or "(empty)"
    if name == "read_file":
        rel = safe_rel(args.get("path") or "")
        if not rel:
            return "invalid path"
        p = ws / rel
        if not p.exists():
            return f"no such file: {rel}"
        return p.read_text(encoding="utf-8", errors="replace")[:12000]
    if name == "write_file":
        rel = safe_rel(args.get("path") or "")
        if not rel:
            return "invalid path"
        if rel in ("tests.py", "verify.py"):
            return "refused: test files are read-only"
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args.get("content") or "", encoding="utf-8", newline="\n")
        return f"wrote {rel} ({len(args.get('content') or '')} bytes)"
    if name == "run_command":
        cmd = args.get("command") or ""
        if DENY_COMMAND.search(cmd):
            return "refused: command blocked by policy"
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                cwd=str(ws), capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            out = (p.stdout or "") + (p.stderr or "")
            return f"exit={p.returncode}\n" + out[:6000]
        except subprocess.TimeoutExpired:
            return "exit=124 (timeout after 60s)"
    if name == "finish":
        return "DONE"
    return f"unknown tool: {name}"


def mode_agent(task, base, sampler, timeout, attempts, workdir: Path, log):
    ws = Path(tempfile.mkdtemp(prefix=f"ev-{task['id']}-", dir=str(workdir)))
    files = dict(task.get("files") or {})
    write_files(ws, files)
    protected = set(task.get("protected") or ["tests.py", "verify.py"]) & set(files)

    tools = tool_specs(["list_files", "read_file", "write_file", "run_command", "finish"])
    messages = [{"role": "system", "content": AGENT_SYSTEM},
                {"role": "user", "content": task["prompt"]}]
    extra = {}
    if task.get("no_think"):
        extra["chat_template_kwargs"] = {"enable_thinking": False}

    ptok = ctok = 0
    trace = []
    max_steps = task.get("max_steps", 10)
    finished = False

    for step in range(1, max_steps + 1):
        msg, usage, _ = ask(base, messages, task.get("max_tokens", 700), sampler, timeout,
                            tools=tools, extra=extra)
        ptok += int(usage.get("prompt_tokens") or 0)
        ctok += int(usage.get("completion_tokens") or 0)
        calls = norm_calls(msg)
        trace.append({"step": step, "calls": calls, "content": msg.get("content")})

        if not calls:
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            messages.append({"role": "user", "content": "Continue. Use the tools."})
            continue

        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": msg.get("tool_calls") or []})
        stop = False
        for tc, c in zip(msg.get("tool_calls") or [], calls):
            result = exec_agent_tool(c["name"], c["args"], ws)
            if c["name"] == "finish":
                stop = True
            messages.append({"role": "tool", "tool_call_id": tc.get("id") or "call",
                             "content": result[:6000]})
        if stop:
            finished = True
            break

    for rel in protected:
        (ws / rel).write_text(files[rel], encoding="utf-8", newline="\n")

    verify = task.get("verify_cmd") or [sys.executable, "verify.py"]
    rc, out = run_cmd(verify, ws, timeout=120)
    return {
        "passed": rc == 0,
        "attempts": 1,
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "detail": ("" if rc == 0 else f"verify failed rc={rc}\n{out[-1200:]}") + ("" if finished else " | no finish()"),
        "trace": trace,
        "workspace_files": read_ws(ws),
    }


# ----------------------------------------------------------------------------- driving

def load_tasks():
    from tasks import ALL
    return ALL


def select(tasks, args):
    out = tasks
    if args.category:
        cats = {c.strip() for c in args.category.split(",")}
        out = [t for t in out if t["category"] in cats]
    if args.id:
        ids = {i.strip() for i in args.id.split(",")}
        out = [t for t in out if t["id"] in ids]
    if args.preset == "quick":
        quick = [t for t in out if t["category"] == "toolcalls"]
        quick += [t for t in out if t["category"] == "codegen"][:4]
        quick += [t for t in out if t["category"] == "debug"][:4]
        seen, ded = set(), []
        for t in quick:
            if t["id"] not in seen:
                seen.add(t["id"])
                ded.append(t)
        out = ded
    if args.limit:
        out = out[: args.limit]
    return out


def run(args):
    global MODEL_NAME
    MODEL_NAME = args.model
    tasks = select(load_tasks(), args)
    if not tasks:
        print("no tasks selected")
        return 2

    sampler = dict(DEFAULT_SAMPLER)
    if args.temperature is not None:
        sampler["temperature"] = args.temperature
    if args.top_p is not None:
        sampler["top_p"] = args.top_p

    workdir = Path(tempfile.mkdtemp(prefix="llm-evals-"))
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    m0 = scrape_metrics(args.base_url)
    t_start = time.time()

    print(f"model endpoint : {api_base(args.base_url)}")
    print(f"model          : {MODEL_NAME}")
    print(f"label          : {args.label}")
    print(f"tasks          : {len(tasks)}")
    print(f"sampler        : {sampler}")
    print("-" * 78)

    rows = []
    for i, task in enumerate(tasks, 1):
        fn = {"edit": mode_edit, "tools": mode_tools, "agent": mode_agent,
              "text": mode_text}[task["mode"]]
        log = lambda s: print(s, flush=True)
        print(f"[{i:2d}/{len(tasks)}] {task['id']:<10} {task['category']:<11} {task['title']}"[:78], flush=True)
        t0 = time.time()
        try:
            res = fn(task, args.base_url, sampler, args.timeout, args.attempts, workdir, log)
            err = ""
        except Exception as e:                      # noqa: BLE001
            res = {"passed": False, "attempts": 0, "prompt_tokens": 0,
                   "completion_tokens": 0, "detail": f"EXCEPTION: {e}",
                   "trace": [], "workspace_files": {}}
            err = repr(e)
        wall = time.time() - t0
        row = {
            "id": task["id"], "category": task["category"], "title": task["title"],
            "difficulty": task.get("difficulty", "medium"), "mode": task["mode"],
            "passed": bool(res["passed"]), "attempts": res["attempts"],
            "prompt_tokens": res["prompt_tokens"], "completion_tokens": res["completion_tokens"],
            "wall_s": round(wall, 1), "detail": (res.get("detail") or "").strip()[:800],
            "error": err,
        }
        rows.append(row)
        print(f"      -> {'PASS' if row['passed'] else 'FAIL'}  "
              f"{row['prompt_tokens']}+{row['completion_tokens']} tok  {row['wall_s']}s", flush=True)
        if args.verbose and not row["passed"] and row["detail"]:
            print("      " + row["detail"].replace("\n", "\n      ")[:600], flush=True)

    wall_total = time.time() - t_start
    m1 = scrape_metrics(args.base_url)

    decode_tps = None
    if m0 and m1:
        d_tok = m1.get("llamacpp:tokens_predicted_total", 0) - m0.get("llamacpp:tokens_predicted_total", 0)
        d_sec = m1.get("llamacpp:tokens_predicted_seconds_total", 0) - m0.get("llamacpp:tokens_predicted_seconds_total", 0)
        if d_sec > 0:
            decode_tps = round(d_tok / d_sec, 2)

    summary = summarize(rows)
    run_doc = {
        "label": args.label,
        "model": MODEL_NAME,
        "started": started,
        "endpoint": api_base(args.base_url),
        "sampler": sampler,
        "attempts": args.attempts,
        "preset": args.preset,
        "wall_s": round(wall_total, 1),
        "decode_tps": decode_tps,
        "summary": summary,
        "tasks": rows,
    }
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", args.label or "run")
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}--{slug}.json"
    out.write_text(json.dumps(run_doc, indent=2), encoding="utf-8")

    report(run_doc)
    print(f"\nsaved: {out}")
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
    else:
        print(f"workspaces kept in: {workdir}")
    return 0


def summarize(rows):
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"tests": 0, "passed": 0, "ptok": 0, "ctok": 0, "wall": 0.0})
        c["tests"] += 1
        c["passed"] += 1 if r["passed"] else 0
        c["ptok"] += r["prompt_tokens"]
        c["ctok"] += r["completion_tokens"]
        c["wall"] += r["wall_s"]
    total = {
        "tests": len(rows),
        "passed": sum(1 for r in rows if r["passed"]),
        "ptok": sum(r["prompt_tokens"] for r in rows),
        "ctok": sum(r["completion_tokens"] for r in rows),
        "wall": round(sum(r["wall_s"] for r in rows), 1),
    }
    return {"categories": cats, "total": total}


def report(doc):
    s = doc["summary"]
    print("\n" + "=" * 78)
    print(f"{'category':<12}{'pass':>7}{'tests':>7}{'pass%':>8}{'prompt':>9}{'output':>9}{'tok/pass':>10}{'s/test':>8}")
    print("-" * 78)
    for cat, c in s["categories"].items():
        pct = 100.0 * c["passed"] / max(c["tests"], 1)
        tpp = (c["ptok"] + c["ctok"]) / max(c["passed"], 1)
        print(f"{cat:<12}{c['passed']:>7}{c['tests']:>7}{pct:>7.0f}%{c['ptok']:>9}{c['ctok']:>9}{tpp:>10.0f}{c['wall']/max(c['tests'],1):>8.1f}")
    t = s["total"]
    pct = 100.0 * t["passed"] / max(t["tests"], 1)
    tpp = (t["ptok"] + t["ctok"]) / max(t["passed"], 1)
    print("-" * 78)
    print(f"{'TOTAL':<12}{t['passed']:>7}{t['tests']:>7}{pct:>7.0f}%{t['ptok']:>9}{t['ctok']:>9}{tpp:>10.0f}{t['wall']/max(t['tests'],1):>8.1f}")
    print("=" * 78)
    if doc.get("decode_tps"):
        print(f"decode speed: {doc['decode_tps']} tok/s (from llama-server /metrics)")
    print(f"wall clock  : {doc['wall_s']}s")
    failed = [r["id"] for r in doc["tasks"] if not r["passed"]]
    if failed:
        print("failed      : " + ", ".join(failed))


def cmd_list(args):
    tasks = select(load_tasks(), args)
    print(f"{'id':<10}{'category':<12}{'mode':<7}{'diff':<8}title")
    print("-" * 90)
    for t in tasks:
        print(f"{t['id']:<10}{t['category']:<12}{t['mode']:<7}{t.get('difficulty','medium'):<8}{t['title']}")
    print(f"\n{len(tasks)} tasks")


def cmd_selftest(args):
    from tasks.toolcalls import TOOLS

    tasks = load_tasks()
    workdir = Path(tempfile.mkdtemp(prefix="ev-selftest-"))
    bad = 0
    for name in ("list_files", "read_file", "write_file", "run_command", "finish"):
        if name not in TOOLS:
            print(f"BAD agent tool schema missing: {name}")
            bad += 1
    for t in tasks:
        if t["mode"] == "tools":
            exp = t.get("expect") or {}
            ok = bool(exp.get("name") or exp.get("calls") or exp.get("no_tool") or exp.get("ask"))
            missing = [n for n in t.get("tools", []) if n not in TOOLS]
            if missing:
                ok = False
            print(f"{'ok ' if ok else 'BAD'} {t['id']:<10} expectation well-formed"
                  + (f" (missing schemas: {missing})" if missing else ""))
            bad += 0 if ok else 1
            continue
        if t["mode"] == "text":
            ok, why = check_text(t, t.get("oracle_text") or "")
            print(f"{'ok ' if ok else 'BAD'} {t['id']:<10} oracle text -> {why}")
            bad += 0 if ok else 1
            continue
        ws = Path(tempfile.mkdtemp(prefix=f"st-{t['id']}-", dir=str(workdir)))
        cmd = (t.get("test_cmd") or t.get("verify_cmd")
               or ([sys.executable, "verify.py"] if t["mode"] == "agent"
                   else [sys.executable, "tests.py"]))

        # 1) the shipped starting state must fail
        start_files = dict(t.get("files") or {})
        write_files(ws, start_files)
        rc0, out0 = run_cmd(cmd, ws, timeout=120)
        if rc0 == 0:
            print(f"BAD {t['id']:<10} starting state already passes")
            bad += 1

        # 2) applying the reference fix/oracle must pass
        files = dict(start_files)
        for old, new in (t.get("fixes") or []):
            hit = False
            for k, v in list(files.items()):
                if old in v:
                    files[k] = v.replace(old, new)
                    hit = True
                    break
            if not hit:
                print(f"BAD {t['id']}: fix pattern not found: {old[:40]!r}")
                bad += 1
        files.update(t.get("oracle") or {})
        write_files(ws, files)
        rc, out = run_cmd(cmd, ws, timeout=120)
        ok = rc == 0
        bad += 0 if ok else 1
        print(f"{'ok ' if ok else 'BAD'} {t['id']:<10} start fails, oracle -> "
              f"{out.strip().splitlines()[-1] if out.strip() else 'no output'}")
        shutil.rmtree(ws, ignore_errors=True)
    shutil.rmtree(workdir, ignore_errors=True)
    print(f"\n{'ALL FIXTURES OK' if bad == 0 else f'{bad} PROBLEM(S)'}")
    return 0 if bad == 0 else 1


def cmd_compare(args):
    a = json.loads(Path(args.run_a).read_text(encoding="utf-8"))
    b = json.loads(Path(args.run_b).read_text(encoding="utf-8"))
    print(f"A = {a['label']} ({a.get('model', '?')})   B = {b['label']} ({b.get('model', '?')})\n")
    print(f"{'category':<12}{'A pass%':>9}{'B pass%':>9}{'delta':>8}{'A tok/p':>10}{'B tok/p':>10}")
    print("-" * 60)
    cats = sorted(set(a["summary"]["categories"]) | set(b["summary"]["categories"]))
    for c in cats:
        ca = a["summary"]["categories"].get(c, {"passed": 0, "tests": 1, "ptok": 0, "ctok": 0})
        cb = b["summary"]["categories"].get(c, {"passed": 0, "tests": 1, "ptok": 0, "ctok": 0})
        pa = 100.0 * ca["passed"] / max(ca["tests"], 1)
        pb = 100.0 * cb["passed"] / max(cb["tests"], 1)
        ta = (ca["ptok"] + ca["ctok"]) / max(ca["passed"], 1)
        tb = (cb["ptok"] + cb["ctok"]) / max(cb["passed"], 1)
        print(f"{c:<12}{pa:>8.0f}%{pb:>8.0f}%{pb-pa:>+7.0f}{ta:>10.0f}{tb:>10.0f}")
    ta, tb = a["summary"]["total"], b["summary"]["total"]
    pa = 100.0 * ta["passed"] / max(ta["tests"], 1)
    pb = 100.0 * tb["passed"] / max(tb["tests"], 1)
    print("-" * 60)
    print(f"{'TOTAL':<12}{pa:>8.0f}%{pb:>8.0f}%{pb-pa:>+7.0f}")
    print(f"\ndecode t/s  A={a.get('decode_tps')}  B={b.get('decode_tps')}")
    print(f"wall        A={a.get('wall_s')}s  B={b.get('wall_s')}s")


def main(argv=None):
    p = argparse.ArgumentParser(description="Personal eval suite for local coding models")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--base-url", default="http://127.0.0.1:9931")
        sp.add_argument("--model", default="local",
                        help="model id sent to the server; use the exact id behind a router")
        sp.add_argument("--category", default=None)
        sp.add_argument("--id", default=None)
        sp.add_argument("--preset", choices=["quick", "full"], default="full")
        sp.add_argument("--limit", type=int, default=0)

    l = sub.add_parser("list")
    common(l)

    st = sub.add_parser("selftest")

    r = sub.add_parser("run")
    common(r)
    r.add_argument("--label", default="run")
    r.add_argument("--attempts", type=int, default=2)
    r.add_argument("--timeout", type=float, default=900)
    r.add_argument("--temperature", type=float, default=None)
    r.add_argument("--top-p", type=float, default=None)
    r.add_argument("--verbose", action="store_true")
    r.add_argument("--keep", action="store_true")

    c = sub.add_parser("compare")
    c.add_argument("run_a")
    c.add_argument("run_b")

    args = p.parse_args(argv)

    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "selftest":
        return cmd_selftest(args)
    if args.cmd == "compare":
        return cmd_compare(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
