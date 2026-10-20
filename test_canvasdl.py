"""Run: .venv/bin/python test_canvasdl.py"""
import asyncio

import canvasdl
import tui


class Resp:
    def __init__(self, data, nxt=None):
        import json
        self.text, self.links = "while(1);" + json.dumps(data), ({"next": {"url": nxt}} if nxt else {})

    def raise_for_status(self):
        pass


pages = {"https://c/api/v1/x": Resp([1, 2], "https://c/p2"), "https://c/p2": Resp([3])}
canvasdl.BASE = "https://c"
canvasdl.http.get = lambda url, params=None: pages[url]
assert canvasdl.get_all("/x") == [1, 2, 3]
assert canvasdl.safe("a/b:c?.") == "a_b_c_"
assert canvasdl.safe("...") == "untitled"
assert canvasdl.FILE_ID.findall('<a href="/courses/9/files/123/download">x</a> /files/45') == ["123", "45"]

# TUI: course -> module -> page renders as markdown
item = {"id": 11, "type": "Page", "title": "Intro", "url": "U", "html_url": "H"}
fake = {"/users/self/favorites/courses": [{"id": 7, "name": "Course 101"}],
        "/courses/7/modules": [{"id": 3, "name": "Week 1", "items": [item]}]}
canvasdl.get_all = lambda path, **kw: fake[path]
canvasdl.api = lambda path, **kw: {"title": "Intro", "body": "<p>IDS <b>approaches</b></p>"}


async def drive():
    app = tui.CanvasTUI()
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        tree = app.query_one(tui.Tree)
        course = tree.root.children[0]
        course.expand()
        await pilot.pause(0.3)
        module = course.children[0]
        assert str(module.label) == "Week 1" and str(course.children[1].label) == "All pages"
        assert (module.data["only"], module.children[0].data["only"], course.children[1].data["only"]) == ("module:3", "item:11", "pages")
        app.show_item(module.children[0].data["item"])
        await pilot.pause(0.3)
        assert "**approaches**" in app.query_one("#doc", tui.Markdown).source


asyncio.run(drive())
# download_course mirrors the TUI tree
import tempfile
from pathlib import Path


class Blob:
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def raise_for_status(self): pass
    def iter_content(self, n): yield b"PDF"


lab = {"id": 101, "type": "Page", "title": "Lab 1", "url": "P1"}
slides = {"id": 102, "type": "File", "title": "slides.pdf", "content_id": 5}
dl_fake = {
    "/courses/7/modules": [{"id": 50, "name": "Week 1", "items": [{"id": 100, "type": "SubHeader", "title": "Read"}, lab, slides]},
                           {"id": 51, "name": "Week 2", "items": []}],
    "/courses/7/pages": [{"title": "Lab 1", "url": "lab-1"}],
    "/courses/7/assignments": [{"id": 9, "name": "Essay", "description": "<p>e</p>"}],
    "/courses/7/files": [{"id": 6, "display_name": "syllabus.pdf", "url": "F6", "size": 3}],
}
docs = {"/courses/7": {"name": "Course 101"}, "P1": {"body": '<a href="/courses/7/files/8">x</a>'},
        "/courses/7/pages/lab-1": {"body": "b"},
        "/courses/7/files/5": {"display_name": "slides.pdf", "url": "F5", "size": 3},
        "/courses/7/files/8": {"display_name": "data.csv", "url": "F8", "size": 3}}
canvasdl.get_all = lambda path, **kw: dl_fake[path]
canvasdl.api = lambda path, **kw: docs[path]
canvasdl.http.get = lambda url, **kw: Blob()
with tempfile.TemporaryDirectory() as d:
    r = canvasdl.download_course(7, d)
    got = sorted(str(f.relative_to(r["dir"])) for f in Path(r["dir"]).rglob("*") if f.is_file())
    assert got == ["01 Week 1/01 Lab 1.html", "01 Week 1/02 slides.pdf", "01 Week 1/data.csv",
                   "All pages/Lab 1.html", "Other assignments/Essay.html", "Other files/syllabus.pdf"], got
    assert r["files_downloaded"] == 3 and not r["errors"], r
    assert canvasdl.download_course(7, d)["files_skipped"] == 3  # re-run skips same-size files

def scoped(only):
    with tempfile.TemporaryDirectory() as d:
        r = canvasdl.download_course(7, d, only)
        return sorted(str(f.relative_to(r["dir"])) for f in Path(r["dir"]).rglob("*") if f.is_file())

# one item keeps its module folder and number, plus files it links
assert scoped("item:102") == ["01 Week 1/02 slides.pdf"]
assert scoped("item:101") == ["01 Week 1/01 Lab 1.html", "01 Week 1/data.csv"]
assert scoped("module:51") == []
assert len(scoped("module:50")) == 3
assert scoped("page:lab-1") == ["All pages/Lab 1.html"]
assert scoped("pages") == ["All pages/Lab 1.html"]

print("ok")
