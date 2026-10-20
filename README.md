# canvasDL

Browse and bulk-download Canvas LMS course content from the terminal, or let an
AI assistant do it through an MCP server.

- **TUI**: courses, modules and pages in a tree; pages render as Markdown.
- **Download** a whole course, one module, or a single item, laid out the same way the TUI shows it.
- **MCP server** with `list_courses` and `download_course` tools.
- **No API token needed**: signs in through your school's Microsoft (Entra ID) single sign-on in a headless browser and reuses that session.

> [!IMPORTANT]
> Unofficial and not affiliated with or endorsed by Instructure or any school. Use it only
> with your own account, for content you already have access to, and follow your
> institution's acceptable-use policy. Course materials belong to their authors; do not
> redistribute downloads. Provided as-is with no warranty.

## Install

Python 3.10+.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m patchright install chromium
```

## Configure

```sh
export CANVAS_URL=https://yourschool.instructure.com
```

Authentication, in order:

1. `CANVAS_TOKEN`, if set (Account → Settings → New Access Token, when your school allows it).
2. A saved browser session from `python canvasdl.py login`. It asks for email, password and
   MFA in the terminal and prints the Authenticator number to approve. Choosing "stay signed
   in" lets later logins happen silently. Add `--show` to watch the browser if it gets stuck.

The session is stored at `~/.local/share/canvasDL/state.json` (mode 600; override with
`CANVASDL_STATE`). It holds live session cookies, so keep it private.

The browser login currently understands Microsoft Entra ID sign-in pages only. Schools using
another identity provider need `CANVAS_TOKEN`.

## TUI

```sh
.venv/bin/python tui.py [canvas page url]
```

| Key | Action |
| --- | --- |
| arrows, enter | expand / open |
| `d` | download the selected course, module, item or page |
| `o` | open selection in your browser |
| `q` | quit |

Only starred (favorite) courses are listed.

## Download layout

Default destination `~/Downloads/canvasDL/`:

```
<course>/
  01 <module>/01 <item>.html, 02 <file>.pdf, <file linked from a page>
  All pages/
  Other assignments/   # assignments not in any module
  Other files/         # Files-tab items not in any module
```

Re-running skips files already present with the same size.

## MCP server

```sh
claude mcp add canvasDL -e CANVAS_URL=https://yourschool.instructure.com -- \
  /path/to/canvasDL/.venv/bin/python /path/to/canvasDL/server.py
```

The server can only log in silently. When the session expires, run `canvasdl.py login` or
open the TUI once.

`download_course(course_id, dest, only)` where `only` is `None` (whole course),
`module:<id>`, `item:<module item id>`, `pages`, or `page:<page url>`.

## Tests

```sh
.venv/bin/python test_canvasdl.py
```

Offline; no Canvas account needed.
