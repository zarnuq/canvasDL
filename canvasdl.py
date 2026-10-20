"""canvasDL core: Canvas REST API over a browser-login session, plus bulk download.

Auth: CANVAS_TOKEN if set, else session cookies from a headless Microsoft SSO
login saved in STATE. Run `python canvasdl.py login` once (add --show to see
the browser if headless gets stuck).
"""
from __future__ import annotations

import getpass
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = os.environ.get("CANVAS_URL", "").rstrip("/")  # e.g. https://school.instructure.com
STATE = Path(os.environ.get("CANVASDL_STATE", "~/.local/share/canvasDL/state.json")).expanduser()
FILE_ID = re.compile(r"/files/(\d+)")
http = requests.Session()


class NeedLogin(Exception):
    """No valid session and no way to sign in without asking the user."""


def js(r: requests.Response):
    """Canvas prefixes cookie-authenticated JSON with `while(1);`."""
    r.raise_for_status()
    return json.loads(r.text.removeprefix("while(1);"))


def api(path: str, **params):
    return js(http.get(path if path.startswith("http") else f"{BASE}/api/v1{path}", params=params))


def get_all(path: str, **params) -> list[dict]:
    """GET every page of a Canvas list endpoint by following the Link header."""
    url, params, out = f"{BASE}/api/v1{path}", {"per_page": 100, **params}, []
    while url:
        r = http.get(url, params=params)
        out += js(r)
        url, params = r.links.get("next", {}).get("url"), None
    return out


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "untitled"


def _load_cookies() -> None:
    http.cookies.clear()
    for c in json.loads(STATE.read_text())["cookies"]:
        http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])


def ensure_auth(ask=None) -> None:
    """Make `http` authenticated. ask(prompt, secret) supplies login input; None = silent only."""
    if not BASE:
        raise RuntimeError("set CANVAS_URL, e.g. export CANVAS_URL=https://school.instructure.com")
    if token := os.environ.get("CANVAS_TOKEN"):
        http.headers["Authorization"] = f"Bearer {token}"
        return
    if STATE.exists():
        _load_cookies()
        if http.get(f"{BASE}/api/v1/users/self").ok:
            return
    login(ask)  # Microsoft "stay signed in" cookie usually makes this silent
    _load_cookies()


def login(ask=None, show: bool = False) -> None:
    """Sign in through Canvas -> Microsoft Entra SSO in headless Chromium, save cookies to STATE."""
    from patchright.sync_api import sync_playwright

    def need(prompt: str, secret: bool = False) -> str:
        if ask is None:
            raise NeedLogin("Canvas session expired: run `python canvasdl.py login`")
        return ask(prompt, secret)

    def tell(msg: str) -> None:
        if ask is None:
            raise NeedLogin("Canvas session expired: run `python canvasdl.py login`")
        print(msg, file=sys.stderr, flush=True)

    host = urlparse(BASE).hostname
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not show)
        ctx = browser.new_context(storage_state=str(STATE) if STATE.exists() else None)
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        told, deadline, done = None, time.monotonic() + 300, set()
        try:
            while not (urlparse(page.url).hostname == host and not urlparse(page.url).path.startswith("/login")):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"login stuck at {page.url[:80]}; retry with --show")
                vis = lambda sel: page.locator(sel).first.is_visible()  # noqa: E731
                if vis("#usernameError, #passwordError, #idTD_Error"):
                    raise RuntimeError(page.locator("#usernameError, #passwordError, #idTD_Error").first.inner_text())
                # Each step runs once: the email box stays visible while the password
                # view slides in, and re-clicking would submit an empty password.
                if "passwd" not in done and vis("input[name=passwd]:not([aria-hidden=true])"):
                    done.add("passwd")
                    page.fill("input[name=passwd]:not([aria-hidden=true])", need("Password: ", True))
                    page.click("#idSIButton9")
                elif "email" not in done and vis("input[name=loginfmt]"):
                    done.add("email")
                    page.fill("input[name=loginfmt]", need("Email: "))
                    page.click("#idSIButton9")
                elif "otc" not in done and vis("input[name=otc]"):
                    done.add("otc")
                    page.fill("input[name=otc]", need("MFA code: "))
                    page.click("#idSubmit_SAOTCC_Continue")
                elif vis("#idRichContext_DisplaySign"):
                    msg = f"Approve in Authenticator, enter number {page.inner_text('#idRichContext_DisplaySign')}"
                    if msg != told:
                        told = msg
                        tell(msg)
                elif vis("#KmsiCheckboxField, #KmsiDescription"):  # "Stay signed in?" -> Yes
                    page.click("#idSIButton9")
                elif vis("#tilesHolder div[role=button]"):  # account picker
                    page.locator("#tilesHolder div[role=button]").first.click()
                elif vis("#idDiv_SAOTCAS_Description") and told != "push":
                    told = "push"
                    tell("Approve the sign-in request on your phone")
                page.wait_for_timeout(700)
            page.wait_for_load_state("domcontentloaded")
            ctx.storage_state(path=str(STATE))
            STATE.chmod(0o600)
        except NeedLogin:
            raise
        except Exception:
            page.screenshot(path=str(STATE.with_name("login-failure.png")))
            raise
        finally:
            browser.close()


def download_course(course_id: int, dest: str = "~/Downloads/canvasDL", only: str | None = None) -> dict:
    """Download a course, or part of it, in the same layout the TUI shows.

    only: None = whole course, "module:<id>", "item:<module item id>", "pages", "page:<page url>".

    <course>/NN <module>/NN <item>.html|<file>, then "All pages/". Files linked from a
    page land next to it; anything the TUI doesn't show (Files tab, assignments outside
    modules) goes to "Other files/" and "Other assignments/". Same-size files are skipped.
    """
    course = api(f"/courses/{course_id}")
    root = Path(dest).expanduser() / safe(course.get("name") or str(course_id))
    want: dict[int, tuple[Path, str]] = {}  # file id -> (folder, name prefix); first placement wins
    metas: dict[int, dict] = {}
    errors: list[str] = []
    docs = 0
    kind, _, val = (only or "").partition(":")

    def listing(path: str, **params) -> list[dict]:
        try:
            return get_all(path, **params)
        except requests.HTTPError as e:  # tab hidden by instructor
            errors.append(f"{path}: {e.response.status_code}")
            return []

    def save_html(out: Path, title: str, body: str) -> None:
        nonlocal docs
        for fid in FILE_ID.findall(body):
            want.setdefault(int(fid), (out.parent, ""))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"<h1>{html.escape(title)}</h1>\n{body}", encoding="utf-8")
        docs += 1

    # Number modules and items like the TUI order; module File items claim their folder first.
    modules = []
    mods = listing(f"/courses/{course_id}/modules", **{"include[]": "items"}) if kind in ("", "module", "item") else []
    for mi, m in enumerate(mods, 1):
        if kind == "module" and str(m["id"]) != val:
            continue
        items = [(n, it) for n, it in enumerate((it for it in m.get("items", []) if it["type"] != "SubHeader"), 1)
                 if kind != "item" or str(it["id"]) == val]
        mdir = root / f"{mi:02} {safe(m['name'])}"
        modules.append((mdir, items))
        for n, it in items:
            if it["type"] == "File":
                want.setdefault(it["content_id"], (mdir, f"{n:02} "))

    in_modules: set[int] = set()
    for mdir, items in modules:
        for n, it in items:
            out = mdir / f"{n:02} {safe(it['title'])}.html"
            if it["type"] == "ExternalUrl":
                link = html.escape(it.get("external_url", ""))
                save_html(out, it["title"], f'<a href="{link}">{link}</a>')
            elif it["type"] in ("Page", "Assignment", "Discussion", "Quiz"):
                try:
                    doc = api(it["url"])
                except requests.HTTPError as e:
                    errors.append(f"{it['title']}: {e.response.status_code}")
                    continue
                if it["type"] == "Assignment":
                    in_modules.add(it["content_id"])
                save_html(out, it["title"], doc.get("body") or doc.get("description") or doc.get("message") or "")

    for pg in listing(f"/courses/{course_id}/pages", sort="title") if kind in ("", "pages", "page") else []:
        if kind == "page" and pg["url"] != val:
            continue
        try:
            body = api(f"/courses/{course_id}/pages/{pg['url']}").get("body") or ""
        except requests.HTTPError as e:
            errors.append(f"{pg['title']}: {e.response.status_code}")
            continue
        save_html(root / "All pages" / f"{safe(pg['title'])}.html", pg["title"], body)

    for a in listing(f"/courses/{course_id}/assignments") if not kind else []:
        if a["id"] not in in_modules:
            save_html(root / "Other assignments" / f"{safe(a['name'])}.html", a["name"], a.get("description") or "")

    for f in listing(f"/courses/{course_id}/files") if not kind else []:
        metas[f["id"]] = f
        want.setdefault(f["id"], (root / "Other files", ""))

    taken: set[Path] = set()
    got = skipped = 0
    for fid, (folder, prefix) in want.items():
        meta = metas.get(fid)
        if meta is None:
            try:
                meta = api(f"/courses/{course_id}/files/{fid}")
            except requests.HTTPError as e:
                errors.append(f"file {fid}: {e.response.status_code}")
                continue
        if not meta.get("url"):  # locked or unpublished
            errors.append(f"file {fid} ({meta.get('display_name')}): locked")
            continue
        out = folder / f"{prefix}{safe(meta['display_name'])}"
        if out in taken:
            out = folder / f"{prefix}{fid}_{safe(meta['display_name'])}"
        taken.add(out)
        if out.exists() and out.stat().st_size == meta.get("size"):
            skipped += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with http.get(meta["url"], stream=True) as r:
                r.raise_for_status()
                with open(out, "wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        fh.write(chunk)
            got += 1
        except requests.RequestException as e:
            out.unlink(missing_ok=True)
            errors.append(f"file {fid} ({out.name}): {e}")

    return {"dir": str(root), "files_downloaded": got, "files_skipped": skipped,
            "html_docs": docs, "errors": errors}


def ask_terminal(prompt: str, secret: bool = False) -> str:
    return getpass.getpass(prompt) if secret else input(prompt)


if __name__ == "__main__":
    if sys.argv[1:2] == ["login"]:
        login(ask_terminal, show="--show" in sys.argv)
        print(f"saved session to {STATE}")
    else:
        sys.exit("usage: canvasdl.py login [--show]")
