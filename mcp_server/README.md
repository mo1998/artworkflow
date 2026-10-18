# MCP server

Exposes the pipeline as 13 tools over MCP stdio, so any MCP-capable agent can generate, inspect,
validate and export assets without knowing the CLI.

No dependencies: a small JSON-RPC 2.0 server, standard library only. It runs anywhere the pipeline
runs.

```bash
python3 mcp_server/server.py        # speaks MCP on stdin/stdout
```

## Client setup

**Claude Code**

```bash
claude mcp add artworkflow -- python3 /abs/path/to/artworkflow/mcp_server/server.py
# generation is slow; raise the tool timeout
export MCP_TIMEOUT=900000
```

**OpenCode** (`opencode.json`)

```json
{
  "mcp": {
    "artworkflow": {
      "type": "local",
      "command": ["python3", "/abs/path/to/artworkflow/mcp_server/server.py"],
      "enabled": true
    }
  }
}
```

**Cursor / other MCP clients** (`mcp.json` style)

```json
{
  "mcpServers": {
    "artworkflow": {
      "command": "python3",
      "args": ["/abs/path/to/artworkflow/mcp_server/server.py"]
    }
  }
}
```

The server `chdir`s to the repository root on start, so relative paths in the manifest resolve
without configuration.

## Tools

Read-only, instant:

| tool | returns |
| --- | --- |
| `artworkflow_env_check` | resolved tool paths, versions, whether ComfyUI is reachable, whether each workflow's checkpoint and custom nodes exist, and a Blender test render |
| `artworkflow_manifest` | manifest validation result and every job (asset + variants) with source, style, size, seed, animation and export target |
| `artworkflow_styles` | the art directions: prompt fragments, generation and processing defaults |
| `artworkflow_asset_status` | per-asset status, seed, class of clip, failed and review checks, retries, errors |
| `artworkflow_inspect` | measured pixels: dimensions, alpha coverage, subject bbox, border contact, file size and path |

Pipeline stages, slow:

| tool | does |
| --- | --- |
| `artworkflow_generate` | renders raw artwork (only the sources the selected assets actually need) |
| `artworkflow_process` | cutout, trim, scale, anchor |
| `artworkflow_spritesheet` | packs frame sequences + frame metadata |
| `artworkflow_validate` | runs the checks, sets statuses, scans for near-duplicates |
| `artworkflow_export` | copies passing assets out, mirrors into the Godot project, writes sidecars |
| `artworkflow_godot_check` | headless import plus engine-side load verification |
| `artworkflow_report` | builds the run report, returns totals and the report inventory |
| `artworkflow_run` | all seven stages in order for the selected assets |

Every stage tool takes `assets` (ids or run keys; omit for the whole manifest) and `force`.
`artworkflow_run` also takes `stages`, `strict` and `skip_godot`.

## Timeouts

Generation blocks until it finishes: seconds per procedural render, tens of seconds per diffusion
image, and a full 16-asset run takes minutes. MCP clients apply their own tool timeout and will
report a failure even though the work completed. Raise it (`MCP_TIMEOUT` for Claude Code, or the
client's equivalent) before running a real batch, and prefer `assets` scoping plus the individual
stage tools when iterating.

## Notes for anyone editing the server

- **stdout is the transport.** Any stray print corrupts the stream, so every tool call runs inside
  `contextlib.redirect_stdout(sys.stderr)`. Human-readable stage logging is therefore safe and
  appears on stderr.
- A failing tool returns `isError: true` with the error and a traceback in the content — it does
  not raise a protocol error. A model can read it and correct itself.
- Long operations are synchronous. If you add real progress reporting, use MCP
  `notifications/progress`; do not stream text to stdout.
