#!/usr/bin/env python3
"""reclickup-mcp (stdio): write a formatted user story straight into a ClickUp DOC page.

ClickUp's public Docs API is markdown-only (equal-width columns, no cell colour). The Doc
editor, however, accepts a paste whose text/html carries each table as
<span class="ql-table-embed" data-table-embed-value=BASE64(json)>. This server opens the page
in reclickup's own headless Edge (browser.py, CDP :9335, session copied once), fires that paste, reloads,
verifies widths/colours, and closes the tab. Nothing for the user to copy.
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import websocket                      # websocket-client
from md2delta import md_to_delta
from delta2doc import convert

import browser
CDP = browser.CDP     # private headless Edge (see browser.py), not the user's debug Edge

PASTE_JS = r"""
(async () => {
  const html = __HTML__, append = __APPEND__;
  const ed = document.querySelector('.cu-dashboard-doc-page_editor-wrapper .ql-editor') || document.querySelector('.ql-editor');
  if (!ed) return 'NO_EDITOR';
  ed.focus();
  const r = document.createRange();
  if (append) { const b = ed.querySelectorAll(':scope > *'); r.selectNodeContents(b[b.length - 1] || ed); r.collapse(false); }
  else r.selectNodeContents(ed);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  await new Promise(res => setTimeout(res, 500));
  const dt = new DataTransfer(); dt.setData('text/html', html); dt.setData('text/plain', ' ');
  const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  ed.dispatchEvent(ev);
  await new Promise(res => setTimeout(res, 2000));
  return ev.defaultPrevented ? 'PASTED' : 'NOT_HANDLED';
})()
"""

VERIFY_JS = r"""
(() => {
  const ed = document.querySelector('.ql-editor'); const h = ed && ed.querySelector('h1');
  const hl = h ? Math.round(h.getBoundingClientRect().left) : null;
  return JSON.stringify({
    chars: ed ? ed.innerText.length : 0,
    tables: [...document.querySelectorAll('table')].map(t => ({
      widths: [...t.querySelectorAll('col')].map(c => +c.getAttribute('width')),
      green: t.querySelectorAll('[data-cell-bg-color]').length,
      aligned: hl === null ? null : Math.abs(Math.round(t.getBoundingClientRect().left) - hl) <= 2,
      head: t.innerText.slice(0, 30).replace(/\s+/g, ' ')}))});
})()
"""


class Tab:
    """A CDP session on one page target."""
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=60); self.n = 0
    def call(self, method, params=None):
        self.n += 1; self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    def eval(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        return r.get("result", {}).get("value")
    def close(self):
        try: self.ws.close()
        except Exception: pass


def cdp_json(path, method="GET"):
    req = urllib.request.Request(CDP + path, method=method)
    return json.load(urllib.request.urlopen(req, timeout=5))


def wait_editor(tab, secs=40):
    end = time.time() + secs; reloaded = False
    while time.time() < end:
        st = tab.eval("JSON.stringify({u: location.href, n: document.querySelectorAll('.ql-editor').length})")
        st = json.loads(st or "{}")
        if "/login" in st.get("u", ""):
            raise RuntimeError("NOT_LOGGED_IN: the ClickUp session in reclickup's browser expired - run clickup_relogin.")
        if st.get("n"): time.sleep(1.5); return
        if not reloaded and time.time() > end - secs / 2:
            tab.call("Page.reload"); reloaded = True
        time.sleep(1.5)
    raise RuntimeError("The Doc editor never loaded (wrong link, no access, or signed out).")


def trusted_click(tab, x, y):
    for typ in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent", {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


EDITOR_RECT_JS = """(() => { const e = document.querySelector('.cu-dashboard-doc-page_editor-wrapper .ql-editor') || document.querySelector('.ql-editor');
  if (!e) return 'null'; const b = e.getBoundingClientRect();
  if (b.height > 0) { e.scrollIntoView({block: 'center'}); const c = e.getBoundingClientRect(); return JSON.stringify({x: c.left + 20, y: c.top + Math.min(12, c.height / 2)}); }
  return 'null'; })()"""

START_WRITING_JS = """(() => { const el = [...document.querySelectorAll('div,button,span,a')].find(e => e.children.length <= 2 && e.innerText && e.innerText.trim() === 'Start writing');
  if (!el) return 'null'; const b = el.getBoundingClientRect(); return JSON.stringify({x: b.left + b.width / 2, y: b.top + b.height / 2}); })()"""


def set_title_if_untitled(tab, title):
    """Type the story title into an empty page title box (an untitled page shows 'Untitled' as placeholder)."""
    r = json.loads(tab.eval("""(() => { const t = document.querySelector('textarea.cu-editable__input, .cu-dashboard-doc-page textarea');
      if (!t || t.value.trim()) return 'null'; const b = t.getBoundingClientRect();
      return JSON.stringify({x: b.left + 10, y: b.top + b.height / 2}); })()"""))
    if not r or not title: return False
    trusted_click(tab, r["x"], r["y"]); time.sleep(0.3)
    tab.call("Input.insertText", {"text": title}); time.sleep(1)
    return True


def click_editor(tab):
    """A trusted click into the body. On an untitled page ClickUp keeps focus in the title box,
    and an EMPTY page hides the editor behind a 'Start writing / Blank wiki / Templates' chooser."""
    for _ in range(10):
        r = json.loads(tab.eval(EDITOR_RECT_JS))
        if r:
            trusted_click(tab, r["x"], r["y"]); time.sleep(0.5); return
        sw = json.loads(tab.eval(START_WRITING_JS))
        if sw: trusted_click(tab, sw["x"], sw["y"])
        time.sleep(1)
    raise RuntimeError("Could not reach the Doc body (empty-page chooser did not open the editor).")


def write_doc(page_url, delta, append=False, title=None):
    if "/v/dc/" not in page_url and "/docs/" not in page_url:
        raise RuntimeError("page_url must be a ClickUp Doc page link (contains /v/dc/ or /docs/).")
    html = convert(delta["ops"] if isinstance(delta, dict) else delta)
    try:
        browser.ensure()
        return _write_doc(page_url, html, append, title)
    except RuntimeError as e:
        if "NOT_LOGGED_IN" not in str(e): raise
        browser.import_session(from_real_edge=not browser.IS_WIN)   # stale copy: refresh once, retry
        return _write_doc(page_url, html, append, title)
    finally:
        browser.touch()


def _write_doc(page_url, html, append, title):
    target = None
    for _ in range(3):
        try:
            t = cdp_json("/json/new?" + urllib.parse.quote("about:blank", safe=""), method="PUT")
            target = t; break
        except Exception: time.sleep(1)
    if not target: raise RuntimeError("Could not open a tab in reclickup's headless Edge.")
    tab = Tab(target["webSocketDebuggerUrl"])
    try:
        tab.call("Page.enable"); tab.call("Runtime.enable")
        tab.call("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        tab.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        tab.call("Page.navigate", {"url": page_url})
        time.sleep(4); wait_editor(tab)
        titled = set_title_if_untitled(tab, title)
        click_editor(tab)
        res = tab.eval(PASTE_JS.replace("__HTML__", json.dumps(html)).replace("__APPEND__", "true" if append else "false"))
        if res != "PASTED": raise RuntimeError(f"Paste was not accepted by the editor ({res}).")
        time.sleep(6)                                     # let ClickUp sync the change
        tab.call("Page.reload"); time.sleep(4); wait_editor(tab); time.sleep(2)
        v = json.loads(tab.eval(VERIFY_JS)); v["titled"] = titled; return v
    finally:
        tab.close()
        try: urllib.request.urlopen(CDP + "/json/close/" + target["id"], timeout=5).read()
        except Exception: pass


def summary(v, append):
    lines = [f"{'Appended to' if append else 'Replaced'} the Doc page. After reload: {len(v['tables'])} tables, {v['chars']} chars." + (" Page was untitled - title set." if v.get("titled") else "")]
    bad = 0
    for i, t in enumerate(v["tables"], 1):
        ok = sum(t["widths"]) == 720 and t["green"] > 0 and t["aligned"] is not False
        bad += not ok
        lines.append(f"{i}. {t['head']} | widths {'/'.join(map(str, t['widths']))} (sum {sum(t['widths'])}) | green cells {t['green']} | aligned {t['aligned']}{'' if ok else '  <-- CHECK'}")
    lines.append("All tables OK." if not bad else f"{bad} table(s) need a look (tables not written by this tool may differ).")
    return "\n".join(lines)


TOOL = {
    "name": "clickup_doc_write",
    "description": ("Write a user story into a ClickUp DOC page with the team table style (column widths, "
                    "green header cells, bold), directly - no copy/paste for the user. Uses reclickup's own "
                    "headless Edge (no window); if it reports NOT_LOGGED_IN, call clickup_relogin. Give the Doc page link and EITHER the "
                    "draft markdown (team ticket format) OR a Quill delta. mode 'replace' (default) "
                    "overwrites the page body; 'append' adds at the end. Returns per-table widths/colour "
                    "read back after a reload."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "page_url": {"type": "string", "description": "https://app.clickup.com/<ws>/v/dc/<docId>/<pageId>"},
            "markdown": {"type": "string", "description": "Draft ticket markdown (the *_DRAFT.md content). A leading '# Title' line is skipped."},
            "delta": {"type": "object", "description": "Quill delta {ops:[...]} as built for a task (840px tables are refitted to the Doc's 720px)."},
            "mode": {"type": "string", "enum": ["replace", "append"], "default": "replace"},
            "title": {"type": "string", "description": "Page title, used only if the page is untitled. Defaults to the markdown's first '# ' line."},
        },
        "required": ["page_url"],
    },
}


# ---------------------------------------------------------------- official ClickUp MCP passthrough
# Every tool of the official server (mcp.clickup.com) is exposed unchanged by running it through
# mcp-remote (OAuth handled there, token cached in ~/.mcp-auth). Our own tools are added on top.

import threading

import shutil
NPX = os.environ.get("RECLICKUP_NPX") or shutil.which("npx.cmd" if sys.platform == "win32" else "npx") or "npx"
UPSTREAM_URL = os.environ.get("RECLICKUP_UPSTREAM", "https://mcp.clickup.com/mcp")
UPSTREAM_CMD = [NPX, "-y", "mcp-remote@0.15.1", UPSTREAM_URL]
OUT_LOCK = threading.Lock()


def write_out(obj):
    with OUT_LOCK:
        sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


class Upstream:
    def __init__(self):
        self.proc = None; self.n = 0; self.pending = {}; self.lock = threading.Lock()
        self.ready = threading.Event(); self.error = None; self.tools = []

    def start(self):
        threading.Thread(target=self._boot, daemon=True).start()

    def _boot(self):
        try:
            logdir = os.path.join(os.path.expanduser("~"), ".reclickup"); os.makedirs(logdir, exist_ok=True)
            log = open(os.path.join(logdir, "upstream.log"), "a")
            self.proc = subprocess.Popen(UPSTREAM_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                         text=True, bufsize=1)
            threading.Thread(target=self._read, daemon=True).start()
            self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "reclickup-mcp", "version": "0.1.0"}}, timeout=300)
            self.notify("notifications/initialized")
            self.tools = self.request("tools/list", {}, timeout=120).get("tools", [])
            # The client may have listed tools before the upstream was ready (first run waits for OAuth
            # in the browser): tell it to list again.
            write_out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception as e:
            self.error = str(e)
        finally:
            self.ready.set()

    def _read(self):
        for line in self.proc.stdout:
            try: m = json.loads(line)
            except Exception: continue
            if "id" in m and ("result" in m or "error" in m):
                slot = self.pending.pop(m["id"], None)
                if slot: slot[1].update(m); slot[0].set()
            elif "id" in m and "method" in m:          # request from upstream to us (ping etc.)
                self._send({"jsonrpc": "2.0", "id": m["id"], "result": {}} if m["method"] == "ping" else
                           {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "not supported"}})
            elif m.get("method") == "notifications/tools/list_changed":
                threading.Thread(target=self._refresh, daemon=True).start()
        self.error = self.error or "official ClickUp MCP process exited (see ~/.reclickup/upstream.log)"

    def _refresh(self):
        try:
            self.tools = self.request("tools/list", {}, timeout=120).get("tools", [])
            write_out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception: pass

    def _send(self, m):
        with self.lock:
            self.proc.stdin.write(json.dumps(m) + "\n"); self.proc.stdin.flush()

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def request(self, method, params, timeout=180):
        with self.lock: self.n += 1; i = self.n
        ev, box = threading.Event(), {}
        self.pending[i] = (ev, box)
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        if not ev.wait(timeout):
            self.pending.pop(i, None); raise RuntimeError(f"official ClickUp MCP timed out on {method}")
        if "error" in box: raise RuntimeError(box["error"].get("message", str(box["error"])))
        return box["result"]


UP = Upstream()


RELOGIN_TOOL = {
    "name": "clickup_relogin",
    "description": ("Refresh the ClickUp session of reclickup's private headless browser (used by clickup_doc_write). "
                    "macOS: copies the clickup.com cookies from the user's real Microsoft Edge (a Keychain prompt "
                    "'Microsoft Edge Safe Storage' may appear - the user must click Allow). Windows: opens an Edge window "
                    "at the ClickUp login; the user signs in once (waits up to 5 minutes). Use on first use or when "
                    "clickup_doc_write reports NOT_LOGGED_IN."),
    "inputSchema": {"type": "object", "properties": {}},
}


def handle(msg):
    m, mid = msg.get("method"), msg.get("id")
    if m == "initialize":
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "reclickup-mcp", "version": "0.1.0"}}
    if m == "tools/list":
        # Don't hold the client for long: on a first run the official server waits for OAuth in the
        # browser. Our tools are listed now; tools/list_changed follows once the official ones arrive.
        UP.ready.wait(15)
        mine = {TOOL["name"], RELOGIN_TOOL["name"]}
        return {"tools": [t for t in UP.tools if t.get("name") not in mine] + [TOOL, RELOGIN_TOOL]}
    if m == "tools/call":
        p = msg["params"]; a = p.get("arguments") or {}
        if p.get("name") == RELOGIN_TOOL["name"]:
            try:
                n = browser.relogin()
                return {"content": [{"type": "text", "text": f"ClickUp session refreshed in reclickup's headless browser ({n} cookies)."}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        if p.get("name") != TOOL["name"]:
            UP.ready.wait(90)
            if UP.error and not UP.tools:
                return {"content": [{"type": "text", "text": f"Official ClickUp MCP unavailable: {UP.error}"}], "isError": True}
            try: return UP.request("tools/call", p, timeout=300)
            except Exception as e: return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        try:
            title = a.get("title")
            md = a.get("markdown") or ""
            if not title and md.lstrip().startswith("# "): title = md.lstrip().splitlines()[0][2:].replace("**", "").strip()
            if a.get("delta"): delta = a["delta"]
            elif a.get("markdown"): delta = md_to_delta(a["markdown"])
            else: raise RuntimeError("Pass either 'markdown' or 'delta'.")
            append = a.get("mode") == "append"
            return {"content": [{"type": "text", "text": summary(write_doc(a["page_url"], delta, append, title), append)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    if m == "ping": return {}
    if mid is None: return None          # notification
    raise KeyError(m)


def respond(msg):
    try:
        res = handle(msg)
        if msg.get("id") is None: return
        out = {"jsonrpc": "2.0", "id": msg["id"], "result": res}
    except KeyError as e:
        out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": f"method not found: {e}"}}
    except Exception as e:
        out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
    write_out(out)


def main():
    UP.start()
    for line in sys.stdin:
        if not line.strip(): continue
        msg = json.loads(line)
        if msg.get("method") == "initialize": respond(msg)          # in order
        else: threading.Thread(target=respond, args=(msg,), daemon=True).start()


if __name__ == "__main__":
    main()
