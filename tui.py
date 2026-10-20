"""canvasDL TUI: browse courses -> modules -> pages and read them in the terminal.

Run: .venv/bin/python tui.py [canvas page url]
Keys: arrows + enter to open, d download course, o open in browser, q quit.
"""
from __future__ import annotations

import re
import sys
import webbrowser

import html2text
import requests
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Markdown, Tree

import canvasdl


def to_md(html: str) -> str:
    h = html2text.HTML2Text(baseurl=canvasdl.BASE)
    h.body_width = 0
    return h.handle(html or "")


def label(item: dict) -> Text:
    if item["type"] == "SubHeader":
        return Text(item["title"], style="bold")
    if item["type"] == "Page":
        return Text(item["title"])
    return Text.assemble(item["title"], (f"  {item['type']}", "dim"))


class CanvasTUI(App):
    TITLE = "canvasDL"
    CSS = "#nav { width: 40%; } #doc-scroll { width: 60%; padding: 0 1; }"
    BINDINGS = [("d", "download", "Download selected"), ("o", "open", "Open in browser"), ("q", "quit", "Quit")]

    def __init__(self, start_url: str | None = None):
        super().__init__()
        self.start_url = start_url

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Tree("Courses", id="nav")
            with VerticalScroll(id="doc-scroll"):
                yield Markdown("Pick a course, expand a module, press enter on a page.", id="doc")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Tree).show_root = False
        self.load_courses()
        if self.start_url and (m := re.search(r"/courses/(\d+)/pages/([^/?#]+)", self.start_url)):
            self.show_item({"type": "Page", "title": m[2], "html_url": self.start_url,
                            "url": f"{canvasdl.BASE}/api/v1/courses/{m[1]}/pages/{m[2]}"})

    @work(thread=True)
    def load_courses(self) -> None:
        courses = canvasdl.get_all("/users/self/favorites/courses")  # starred; Canvas falls back to dashboard courses if none

        def add() -> None:
            root = self.query_one(Tree).root
            for c in courses:
                if c.get("name"):
                    root.add(Text(c["name"]), data={"kind": "course", "course": c["id"], "only": None})
            root.expand()
        self.call_from_thread(add)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        d = event.node.data
        if d and d["kind"] in ("course", "pages") and not d.get("loaded"):
            d["loaded"] = True
            self.load_children(event.node)

    @work(thread=True)
    def load_children(self, node) -> None:
        cid, kind = node.data["course"], node.data["kind"]
        try:
            if kind == "course":
                rows = canvasdl.get_all(f"/courses/{cid}/modules", **{"include[]": "items"})
            else:
                rows = [{"type": "Page", "title": p["title"], "html_url": p["html_url"], "page_url": p["url"],
                         "url": f"{canvasdl.BASE}/api/v1/courses/{cid}/pages/{p['url']}"}
                        for p in canvasdl.get_all(f"/courses/{cid}/pages", sort="title")]
        except requests.HTTPError as e:  # tab hidden by instructor
            rows = []
            self.call_from_thread(self.notify, f"{kind}: Canvas {e.response.status_code}", severity="warning")

        def add() -> None:
            if kind == "course":
                for m in rows:
                    mod = node.add(Text(m["name"]), data={"kind": "module", "course": cid, "only": f"module:{m['id']}"})
                    for it in m.get("items", []):
                        mod.add_leaf(label(it), data={"kind": "item", "course": cid, "item": it, "only": f"item:{it['id']}"})
                node.add("All pages", data={"kind": "pages", "course": cid, "only": "pages"})
            else:
                for it in rows:
                    node.add_leaf(label(it), data={"kind": "item", "course": cid, "item": it,
                                                   "only": f"page:{it['page_url']}"})
        self.call_from_thread(add)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        d = event.node.data
        if d and d["kind"] == "item":
            self.show_item(d["item"])

    @work(thread=True, exclusive=True, group="doc")
    def show_item(self, it: dict) -> None:
        title = it["title"]
        try:
            if it["type"] == "ExternalUrl":
                md = f"# {title}\n\n[{it.get('external_url')}]({it.get('external_url')})"
            elif "url" not in it:
                md = f"# {title}"
            else:
                doc = canvasdl.api(it["url"])
                title = doc.get("title") or doc.get("name") or doc.get("display_name") or title
                if it["type"] == "File":
                    md = (f"# {title}\n\n{doc.get('size', 0) // 1024} KB, {doc.get('content-type')}\n\n"
                          "Press **d** to download the course, **o** to open in browser.")
                else:
                    md = f"# {title}\n\n" + to_md(doc.get("body") or doc.get("description") or doc.get("message") or "")
        except requests.HTTPError as e:
            md = f"# {title}\n\nCanvas {e.response.status_code} (locked or hidden)"

        def show() -> None:
            self.query_one("#doc", Markdown).update(md)
            self.query_one("#doc-scroll").scroll_home(animate=False)
        self.call_from_thread(show)

    def action_open(self) -> None:
        node = self.query_one(Tree).cursor_node
        if node and node.data:
            item = node.data.get("item", {})
            webbrowser.open(item.get("html_url") or f"{canvasdl.BASE}/courses/{node.data['course']}")

    def action_download(self) -> None:
        node = self.query_one(Tree).cursor_node
        if node and node.data:
            self.download(node.data["course"], node.data.get("only"), node.label.plain)

    @work(thread=True, group="download")
    def download(self, cid: int, only: str | None, name: str) -> None:
        self.call_from_thread(self.notify, f"Downloading {name}...")
        try:
            r = canvasdl.download_course(cid, only=only)
        except Exception as e:
            self.call_from_thread(self.notify, f"Download failed: {e}", severity="error")
            return
        errs = f", {len(r['errors'])} skipped/errors" if r["errors"] else ""
        self.call_from_thread(self.notify, f"{r['files_downloaded']} files, {r['html_docs']} docs{errs} -> {r['dir']}",
                              timeout=15)


if __name__ == "__main__":
    canvasdl.ensure_auth(canvasdl.ask_terminal)
    CanvasTUI(sys.argv[1] if len(sys.argv) > 1 else None).run()
