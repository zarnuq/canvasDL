# canvasDL

Canvas LMS browser/downloader: Textual TUI + MCP server over the Canvas REST API.

## Files

- `canvasdl.py`: core. Auth (`ensure_auth`, headless `login`), API helpers (`api`, `get_all`), `download_course`.
- `tui.py`: Textual app. Lazy-loads courses → modules → items; `d` downloads the selected node via `only`.
- `server.py`: MCP server (mcp 2.x `MCPServer`, not v1 `FastMCP`). Thin wrapper over `canvasdl`.
- `test_canvasdl.py`: offline asserts plus a Textual `run_test` pilot. Run `.venv/bin/python test_canvasdl.py`.

## Gotchas

- Cookie-authenticated Canvas JSON is prefixed with `while(1);`. Always parse through `js()`/`api()`, never `r.json()`.
- Microsoft's login page keeps a hidden decoy `input[name=passwd]` (`aria-hidden=true`, class `moveOffScreen`) on the email step. Select `:not([aria-hidden=true])`, and run each login step once: the email box stays visible while the password view animates in.
- MCP calls `ensure_auth()` with no `ask`, so it can only log in silently. It raises `NeedLogin` instead of prompting.
- MCP tools must raise `ToolError` for user-visible messages; other exceptions are hidden as "Error executing tool".
- Download layout must match the TUI tree: `NN module/NN item`, numbering counts non-SubHeader items. Tests assert the exact paths.
- patchright needs a Python whose greenlet can load the system `libstdc++`; some isolated Python builds (e.g. Nix) cannot.

## Privacy

This repo is public. Never commit real course names, school URLs, user emails, `state.json`,
login screenshots or downloaded content. `.gitignore` is an allowlist; add new source files to it explicitly.
