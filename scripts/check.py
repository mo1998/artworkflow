#!/usr/bin/env python3
"""Run everything CI runs, in one command, before you push.

    python3 scripts/check.py            # static sweep + the test suite
    python3 scripts/check.py --static   # only the sweep
    python3 scripts/check.py --tests    # only the suite
    python3 scripts/check.py --mcp      # only the MCP handshake

The sweep catches what the suite cannot: a syntax error in a file no test imports, and a Blender
script that will not parse. Those scripts import `bpy`, so they can never be imported here - only
parsed.
"""

from __future__ import annotations

import argparse
import ast
import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")]

# A floor on the number of tests that must actually execute. Without it, a change that makes every
# test skip - a broken import, a rename - turns the suite green by testing nothing.
MIN_TESTS = 60

SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".godot"}


def python_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if "assets" in path.parts or "logs" in path.parts:
            continue
        files.append(path)
    return files


def static_sweep() -> list[str]:
    problems: list[str] = []

    for path in python_files():
        try:
            with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
                py_compile.compile(str(path), cfile=tmp.name, doraise=True)
        except py_compile.PyCompileError as exc:
            problems.append(f"compile: {path.relative_to(ROOT)}: {exc.msg.splitlines()[-1]}")
            continue
        try:
            ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"parse: {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

    for path in sorted((ROOT / "blender").rglob("*.py")):
        try:
            ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"parse (blender): {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

    # Config-shaped files: a YAML indentation slip or a trailing comma in JSON is silent until a
    # stage reads it.
    import yaml

    for path in sorted(list((ROOT / "config").glob("*.yaml")) + [ROOT / "config" / "pipeline.yaml"]):
        try:
            yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            problems.append(f"yaml: {path.relative_to(ROOT)}: {exc}")

    for pattern in ("config/*.json", "workflows/comfyui/*.json", "skills/**/SKILL.md",
                    "metadata/manifests/*.json"):
        for path in sorted(ROOT.glob(pattern)):
            try:
                text = path.read_text()
                if path.suffix == ".md":
                    block = text.split("---", 2)[1]
                    yaml.safe_load(block)
                else:
                    json.loads(text)
            except (json.JSONDecodeError, yaml.YAMLError, IndexError) as exc:
                problems.append(f"parse: {path.relative_to(ROOT)}: {exc}")

    return problems


def check_mcp() -> list[str]:
    """Speak the protocol to the server in a clean subprocess.

    Kept here rather than inline in the CI workflow: shell quoting around a multi-line program is
    exactly the kind of thing that breaks silently, and this way a contributor runs the same check.
    """
    import json as _json

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "artworkflow_manifest", "arguments": {}}},
    ]
    payload = "\n".join(_json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run([sys.executable, str(ROOT / "mcp_server" / "server.py")],
                          input=payload, capture_output=True, text=True, timeout=300)
    problems: list[str] = []
    if proc.returncode != 0:
        return [f"server exited {proc.returncode}: {proc.stderr[-500:]}"]
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        responses = [_json.loads(line) for line in lines]
    except ValueError as exc:
        return [f"stdout carried a non-JSON line ({exc}); the transport is corrupted"]
    if [r.get("id") for r in responses] != [1, 2, 3]:
        problems.append(f"unexpected response ids: {[r.get('id') for r in responses]}")
    tools = (responses[1].get("result") or {}).get("tools") or []
    if len(tools) < 13:
        problems.append(f"only {len(tools)} tools listed")
    if not all(str(t.get("name", "")).startswith("artworkflow_") for t in tools):
        problems.append("a tool is not namespaced artworkflow_*")
    manifest = (responses[2].get("result") or {}).get("content") or [{}]
    try:
        body = _json.loads(manifest[0].get("text") or "{}")
        if not body.get("ok"):
            problems.append(f"manifest tool reported problems: {body.get('problems')}")
    except ValueError:
        problems.append("tools/call returned non-JSON content")
    return problems


def run_tests(verbose: bool) -> tuple[int, str]:
    argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    if verbose:
        argv.append("-v")
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--static", action="store_true", help="only the syntax/config sweep")
    parser.add_argument("--tests", action="store_true", help="only the test suite")
    parser.add_argument("--mcp", action="store_true", help="only the MCP server handshake")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    both = not args.static and not args.tests and not args.mcp

    failed = False

    if args.mcp:
        print("== MCP handshake ==")
        problems = check_mcp()
        for problem in problems:
            print(f"  FAIL {problem}")
        if problems:
            failed = True
        else:
            print("  ok   initialize, tools/list and a tools/call round trip")

    if both or args.static:
        print("== static sweep ==")
        problems = static_sweep()
        if problems:
            failed = True
            for problem in problems:
                print(f"  FAIL {problem}")
        else:
            print(f"  ok   {len(python_files())} python files compile and parse")

    if both or args.tests:
        print("\n== test suite ==")
        code, output = run_tests(args.verbose)
        tail = [line for line in output.splitlines() if line.startswith("Ran ") or line.startswith("OK")
                or line.startswith("FAILED")]
        for line in tail:
            print(f"  {line}")
        if args.verbose or code != 0:
            print(output)
        if code != 0:
            failed = True
        ran = 0
        for line in output.splitlines():
            if line.startswith("Ran ") and " test" in line:
                try:
                    ran = int(line.split()[1])
                except (IndexError, ValueError):
                    ran = 0
        if ran < MIN_TESTS:
            failed = True
            print(f"  FAIL only {ran} test(s) executed; expected at least {MIN_TESTS}. "
                  f"A change that makes tests skip is not a passing build.")

    print("\n" + ("FAILED" if failed else "all checks passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
