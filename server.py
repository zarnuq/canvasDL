"""canvasDL MCP server: list and bulk-download Canvas courses. Auth lives in canvasdl.py."""
from __future__ import annotations

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import canvasdl

mcp = MCPServer("canvasDL")


def _auth() -> None:
    try:
        canvasdl.ensure_auth()  # silent only: MCP cannot prompt for password/MFA
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def list_courses() -> list[dict]:
    """List the user's active Canvas courses (id, name)."""
    _auth()
    try:
        courses = canvasdl.get_all("/courses", enrollment_state="active")
    except requests.HTTPError as e:
        raise ToolError(f"Canvas {e.response.status_code}: {e.response.text[:200]}") from e
    return [{"id": c["id"], "name": c.get("name")} for c in courses]


@mcp.tool()
def download_course(course_id: int, dest: str = "~/Downloads/canvasDL", only: str | None = None) -> dict:
    """Download one course as <course>/NN <module>/NN <item>, plus "All pages/".

    Files linked from pages land next to them; files and assignments outside modules
    go to "Other files/" and "Other assignments/". Existing same-size files are skipped.
    only: None = whole course, "module:<id>", "item:<module item id>", "pages", "page:<page url>".
    """
    _auth()
    try:
        return canvasdl.download_course(course_id, dest, only)
    except requests.HTTPError as e:
        raise ToolError(f"Canvas {e.response.status_code}: {e.response.text[:200]}") from e


if __name__ == "__main__":
    mcp.run()
