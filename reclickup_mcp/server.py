#!/usr/bin/env python3
"""reclickup-mcp (stdio): write a formatted user story straight into a ClickUp DOC page.

ClickUp's public Docs API is markdown-only (equal-width columns, no cell colour). The Doc
editor, however, accepts a paste whose text/html carries each table as
<span class="ql-table-embed" data-table-embed-value=BASE64(json)>. This server opens the page
in reclickup's own headless Edge (browser.py, CDP :9335, session copied once), fires that paste, reloads,
verifies widths/colours, and closes the tab. Nothing for the user to copy.
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import websocket                      # websocket-client
from md2delta import md_to_delta
from delta2doc import convert

import browser
CDP = browser.CDP     # private headless Edge (see browser.py), not the user's debug Edge


def _version():
    try:
        txt = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py"), encoding="utf-8").read()
        return re.search(r'__version__\s*=\s*"([^"]+)"', txt).group(1)
    except Exception: return "0"


VERSION = _version()

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
    """A CDP session on one page target. A call that gets no answer in 10 s (page busy loading) raises
    RuntimeError("PAGE_BUSY ...") instead of blocking past the call's deadline."""
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=10); self.n = 0
    def call(self, method, params=None):
        self.n += 1; self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            try: m = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                raise RuntimeError(f"PAGE_BUSY: no answer to {method} in 10 s")
            if m.get("id") == self.n:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    def eval(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError("page script failed: " + str((d.get("exception") or {}).get("description") or d.get("text"))[:300])
        return r.get("result", {}).get("value")
    def close(self):
        try: self.ws.close()
        except Exception: pass


def cdp_json(path, method="GET"):
    req = urllib.request.Request(CDP + path, method=method)
    return json.load(urllib.request.urlopen(req, timeout=5))


def left(deadline):
    return deadline - time.time()


def wait_editor(tab, deadline, settle=2.0):
    """Wait for the Doc editor, then let it settle: a paste straight after the editor appears is ignored
    (NOT_HANDLED) because ClickUp attaches its handlers a moment later."""
    reloaded = False; start = time.time(); last = None
    while left(deadline) > 0:
        try: st = json.loads(tab.eval("JSON.stringify({u: location.href, n: document.querySelectorAll('.ql-editor').length, "
                                      "c: ((document.querySelector('.ql-editor') || {}).innerText || '').length})") or "{}")
        except RuntimeError: st = {}                       # page navigating
        if "/login" in st.get("u", ""):
            raise RuntimeError("NOT_LOGGED_IN: the ClickUp session in reclickup's browser expired - run clickup_relogin.")
        if st.get("n"):
            if last is not None and st.get("c") == last:   # content stopped changing: loaded
                time.sleep(max(0.0, min(settle, left(deadline)))); return
            last = st.get("c")
        elif not reloaded and time.time() - start > 20:
            tab.call("Page.reload"); reloaded = True
        time.sleep(0.7)
    raise RuntimeError(TIMEOUT_MSG)


TIMEOUT_MSG = ("TIMEOUT: the Doc page did not finish loading in time (ClickUp slow, wrong link, or no access). "
               "Nothing was pasted; check the link and call clickup_doc_write again.")


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


def write_doc(page_url, delta, append=False, title=None, deadline=None):
    """Whole job inside `deadline` (the client drops a call after ~60 s) and inside the shared browser lock."""
    deadline = deadline or time.time() + CALL_BUDGET
    if "/v/dc/" not in page_url and "/docs/" not in page_url:
        raise RuntimeError("page_url must be a ClickUp Doc page link (contains /v/dc/ or /docs/).")
    html = convert(delta["ops"] if isinstance(delta, dict) else delta)
    with browser.job(timeout=min(15, left(deadline) - 30)):
        try:
            browser.ensure()
            return _write_doc(page_url, html, append, title, deadline)
        except RuntimeError as e:
            if "NOT_LOGGED_IN" not in str(e) or left(deadline) < 25: raise
            browser.import_session(from_real_edge=not browser.IS_WIN)   # stale copy: refresh once, retry
            return _write_doc(page_url, html, append, title, deadline)


def _write_doc(page_url, html, append, title, deadline):
    target = None
    for _ in range(3):
        try:
            target = cdp_json("/json/new?" + urllib.parse.quote("about:blank", safe=""), method="PUT"); break
        except Exception: time.sleep(1)
    if not target: raise RuntimeError("Could not open a tab in reclickup's headless Edge.")
    tab = Tab(target["webSocketDebuggerUrl"])
    try:
        tab.call("Page.enable"); tab.call("Runtime.enable")
        tab.call("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        tab.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        try: tab.call("Page.navigate", {"url": page_url})
        except RuntimeError as e:                          # slow network: navigation still going, wait_editor follows it
            if "PAGE_BUSY" not in str(e): raise
        time.sleep(1)
        wait_editor(tab, deadline - 18)                    # keep ~18 s for paste, save and the read-back
        titled = set_title_if_untitled(tab, title)
        js = PASTE_JS.replace("__HTML__", json.dumps(html)).replace("__APPEND__", "true" if append else "false")
        for attempt in range(6):
            # NOT_HANDLED = the editor's paste handler is not attached yet (ClickUp still loading): nothing changed,
            # so wait and paste again.
            click_editor(tab)
            res = tab.eval(js)
            if res == "PASTED" or left(deadline) < 16: break
            time.sleep(1.5)
        if res != "PASTED": raise RuntimeError(f"TIMEOUT: the editor did not accept the paste in time ({res}); nothing was changed.")
        time.sleep(SAVE_WAIT)                              # let ClickUp sync the change before reloading
        try: tab.call("Page.reload")
        except RuntimeError as e:
            if "PAGE_BUSY" not in str(e): raise
        time.sleep(1)
        try: wait_editor(tab, deadline, settle=0.5)
        except RuntimeError as e:
            if "TIMEOUT" not in str(e): raise
            return {"chars": 0, "tables": [], "titled": titled, "unverified": True}
        v = json.loads(tab.eval(VERIFY_JS)); v["titled"] = titled; return v
    finally:
        tab.close()
        try: urllib.request.urlopen(CDP + "/json/close/" + target["id"], timeout=5).read()
        except Exception: pass


SAVE_WAIT = float(os.environ.get("RECLICKUP_SAVE_WAIT", "4"))   # 2 s already persisted in a test; 4 s leaves margin


def summary(v, append):
    if v.get("unverified"):
        return (f"{'Appended to' if append else 'Replaced'} the Doc page, but it did not reload in time to read the "
                "result back. Open the page to check it; do not write again before checking.")
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


def kill_tree(proc):
    """Stop the upstream and its children. On Windows npx.cmd runs node as a child of cmd.exe, and terminate()
    would only stop cmd.exe, leaving mcp-remote running."""
    if not proc or proc.poll() is not None: return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        else: proc.terminate()
    except Exception:
        try: proc.kill()
        except Exception: pass


def write_out(obj):
    with OUT_LOCK:
        sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


CALL_BUDGET = int(os.environ.get("RECLICKUP_CALL_BUDGET", "50"))   # Claude Desktop/Cowork give up on a call after ~60 s
LOG_MAX = 2_000_000
READY_WAIT = max(min(5, CALL_BUDGET / 2), CALL_BUDGET - 20)   # how long a call waits for the upstream to connect

KNOWN_CACHE = os.path.join(os.path.expanduser("~"), ".reclickup", "official_tools.json")
KNOWN_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "official_tools.json")


def load_known_tools():
    """Official tools from the last live listing (or the snapshot shipped with the package).

    While the official server is still connecting (first run waiting for OAuth, slow start, sign-in never
    approved) Claude would otherwise see only clickup_doc_write / clickup_relogin and tell users it cannot
    create tasks. tools/list_changed follows once the live list arrives."""
    for path in (KNOWN_CACHE, KNOWN_BUNDLED):
        try:
            with open(path, encoding="utf-8") as f:
                tools = json.load(f)
            if tools: return tools
        except Exception: pass
    return []


def save_known_tools(tools):
    if not tools: return
    try:
        os.makedirs(os.path.dirname(KNOWN_CACHE), exist_ok=True)
        with open(KNOWN_CACHE, "w", encoding="utf-8") as f: json.dump(tools, f)
    except Exception: pass


class Upstream:
    def __init__(self):
        self.proc = None; self.n = 0; self.pending = {}; self.lock = threading.Lock()
        self.ready = threading.Event(); self.error = None; self.tools = []; self.gen = 0; self.started = 0.0
        self.log = None
        self.known = load_known_tools()   # listed until the live upstream answers (see tools/list)

    def start(self):
        self.gen += 1; self.started = time.time()
        threading.Thread(target=self._boot, args=(self.gen, self.ready), daemon=True).start()

    def dead(self):
        return self.ready.is_set() and (self.error is not None or not self.proc or self.proc.poll() is not None)

    def restart(self):
        """The official server exited or stopped answering (sign-in timed out, network drop...): start a fresh one."""
        if not self.ready.is_set() and time.time() - self.started < 10: return     # a fresh one is already starting
        kill_tree(self.proc)
        self.proc = None; self.pending = {}; self.error = None; self.ready = threading.Event()
        self.start()

    def state(self):
        """One line on what the official server is doing, from the tail of its log (no tokens or URLs)."""
        try:
            with open(os.path.join(os.path.expanduser("~"), ".reclickup", "upstream.log"), "rb") as f:
                f.seek(0, 2); f.seek(max(0, f.tell() - 6000)); tail = f.read().decode("utf-8", "replace").lower()
        except Exception: tail = ""
        waiting = ("waiting for authorization", "to authorize this client", "running the sign-in for this server",
                   "sign-in for this server is already under way", "could not open a browser",
                   "requires authorization, completing sign-in")
        last = max([tail.rfind(w) for w in waiting])
        done = max(tail.rfind("proxy established"), tail.rfind("re-authorized with the remote server"))
        if last >= 0 and done < last:
            return ("it is waiting for the ClickUp sign-in: in the browser page that opened, pick the workspace and "
                    "click Connect Workspace")
        return "it is still starting (the first start downloads mcp-remote)"

    def _boot(self, gen, ready):
        try:
            logdir = os.path.join(os.path.expanduser("~"), ".reclickup"); os.makedirs(logdir, exist_ok=True)
            path = os.path.join(logdir, "upstream.log")
            try:                                   # mcp-remote logs every message: keep the file small
                if os.path.getsize(path) > LOG_MAX: os.replace(path, path + ".1")
            except OSError: pass                   # missing, or held open by another copy on Windows
            log = open(path, "a", encoding="utf-8")
            if gen != self.gen: log.close(); return
            old, self.log = self.log, log
            if old:
                try: old.close()
                except Exception: pass
            # UTF-8 explicitly: on Windows the default is cp1252, which cannot decode some Vietnamese characters
            # (e.g. "ờ" = E1 BB 9D) - the reader thread died on them and every later call timed out.
            proc = subprocess.Popen(UPSTREAM_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            if gen != self.gen: kill_tree(proc); return
            self.proc = proc
            threading.Thread(target=self._read, args=(proc, gen), daemon=True).start()
            self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "reclickup-mcp", "version": VERSION}}, timeout=300)
            self.notify("notifications/initialized")
            self.tools = self.request("tools/list", {}, timeout=120).get("tools", [])
            save_known_tools(self.tools)
            # The client may have listed tools before the upstream was ready (first run waits for OAuth
            # in the browser): tell it to list again.
            write_out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception as e:
            if gen == self.gen: self.error = str(e)
        finally:
            ready.set()

    def _read(self, proc, gen):
        while True:
            try: line = proc.stdout.readline()
            except Exception: continue                      # never let one bad line kill the reader
            if not line: break
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
            elif m.get("method") in ("notifications/resources/list_changed", "notifications/resources/updated",
                                     "notifications/prompts/list_changed"):
                write_out(m)
        if gen != self.gen: return                       # an old process we replaced: leave the new one alone
        self.error = self.error or "official ClickUp MCP process exited (see ~/.reclickup/upstream.log)"
        for ev, box in list(self.pending.values()):      # fail waiting requests now instead of at their timeout
            box["error"] = {"message": self.error}; ev.set()
        self.pending.clear()

    def _refresh(self):
        try:
            self.tools = self.request("tools/list", {}, timeout=120).get("tools", [])
            save_known_tools(self.tools)
            write_out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception: pass

    def _send(self, m):
        with self.lock:
            self.proc.stdin.write(json.dumps(m) + "\n"); self.proc.stdin.flush()

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def send(self, method, params):
        """Send a request without waiting: returns (id, event, box); the reader fills box and sets event."""
        with self.lock: self.n += 1; i = self.n
        ev, box = threading.Event(), {}
        self.pending[i] = (ev, box)
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        return i, ev, box

    @staticmethod
    def result(box):
        if "error" in box: raise RuntimeError(box["error"].get("message", str(box["error"])))
        return box["result"]

    def request(self, method, params, timeout=180):
        i, ev, box = self.send(method, params)
        if not ev.wait(timeout):
            self.pending.pop(i, None); raise RuntimeError(f"official ClickUp MCP timed out on {method}")
        return self.result(box)

    def responsive(self, timeout=8):
        """True if the remote ClickUp server still answers (mcp-remote forwards ping upstream)."""
        try: self.request("ping", {}, timeout=timeout); return True
        except Exception: return False


UP = Upstream()


RELOGIN_TOOL = {
    "name": "clickup_relogin",
    "description": ("Refresh the ClickUp session of reclickup's private headless browser (used by clickup_doc_write). "
                    "macOS: copies the clickup.com cookies from the user's real Microsoft Edge (a Keychain prompt "
                    "'Microsoft Edge Safe Storage' may appear - the user must click Allow). Windows: opens an Edge window "
                    "at the ClickUp login and waits about 40 s for the user to sign in; if it returns LOGIN_PENDING, the "
                    "window is still open: ask the user to sign in there, then call clickup_relogin again. Use on first "
                    "use or when clickup_doc_write reports NOT_LOGGED_IN."),
    "inputSchema": {"type": "object", "properties": {}},
}


SLOW_CALL = int(os.environ.get("RECLICKUP_SLOW_CALL", "20"))   # then check that the connection to ClickUp still answers


def stale(note):
    return {"content": [{"type": "text", "text": "STALE_CONNECTION: " + note + " reclickup restarted it, so call the tool "
             "again now. If this was a write (create/update/delete), first check whether it already happened."}],
            "isError": True}


def call_upstream(p, deadline):
    """Forward a tools/call. A connection that stopped answering (VPN reconnect, dropped session...) makes every
    later call hang too, so detect it with a ping and restart mcp-remote instead of timing out call after call."""
    try: i, ev, box = UP.send("tools/call", {k: v for k, v in p.items() if k != "_retried"})
    except Exception as e:
        UP.restart(); return stale(f"the connection to ClickUp was broken ({e}).")
    if not ev.wait(max(1, min(SLOW_CALL, deadline - time.time()))):
        if not UP.responsive(timeout=min(8, max(2, deadline - time.time() - 2))):
            UP.pending.pop(i, None)
            if UP.state().startswith("it is waiting for the ClickUp sign-in"):
                return {"content": [{"type": "text", "text": f"NOT_READY: ClickUp asked to sign in again; {UP.state()}. "
                         "Then call this tool again."}], "isError": True}
            UP.restart()
            return stale("the connection to ClickUp had stopped answering (a network or VPN change, or an expired session).")
        if not ev.wait(max(1, deadline - time.time())):
            UP.pending.pop(i, None); UP.restart()
            return stale(f"ClickUp did not answer {p.get('name')} within {CALL_BUDGET} s.")
    try: return UP.result(box)
    except Exception as e:
        # A network blip ("fetch failed", reset, timeout) on a read-only tool is safe to try once more.
        if is_transient(e) and read_only(p.get("name")) and deadline - time.time() > 10 and not p.get("_retried"):
            time.sleep(1.5)
            return call_upstream(dict(p, _retried=True), deadline)
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


TRANSIENT = ("fetch failed", "econnreset", "etimedout", "socket hang up", "network", "eai_again", "503", "502")


def is_transient(e):
    return any(w in str(e).lower() for w in TRANSIENT)


def read_only(name):
    for t in UP.tools or UP.known:
        if t.get("name") == name: return bool((t.get("annotations") or {}).get("readOnlyHint"))
    return False


# Methods that belong to the official server: its MCP Apps UIs (ui://clickup/task-card.html for
# clickup_get_task, task-table for clickup_filter_tasks, timers...) are fetched by the client with resources/read.
FORWARDED = {"resources", "prompts", "completion"}


def forward(method, params):
    UP.ready.wait(READY_WAIT)
    if not UP.ready.is_set() or UP.error:
        if method.endswith("/list"):                                   # nothing yet; list_changed follows later
            return {{"resources/templates/list": "resourceTemplates"}.get(method, method.split("/")[0]): []}
        if UP.dead(): UP.restart()
        raise RuntimeError(f"official ClickUp MCP not connected yet; {UP.state()}")
    try: return UP.request(method, params, timeout=CALL_BUDGET / 2)
    except RuntimeError as e:                 # resources/prompts are reads: one more try after a network blip
        if not is_transient(e): raise
        time.sleep(1.5); return UP.request(method, params, timeout=CALL_BUDGET / 2)


def handle(msg):
    m, mid = msg.get("method"), msg.get("id")
    if m == "initialize":
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": True}, "resources": {"listChanged": True}, "prompts": {"listChanged": True}},
                "serverInfo": {"name": "reclickup-mcp", "version": VERSION}}
    if m == "tools/list":
        # Don't hold the client for long: on a first run the official server waits for OAuth in the
        # browser. Our tools are listed now; tools/list_changed follows once the official ones arrive.
        UP.ready.wait(15)
        mine = {TOOL["name"], RELOGIN_TOOL["name"]}
        official = UP.tools or UP.known
        return {"tools": [t for t in official if t.get("name") not in mine] + [TOOL, RELOGIN_TOOL]}
    if m == "tools/call":
        p = msg["params"]; a = p.get("arguments") or {}
        if p.get("name") == RELOGIN_TOOL["name"]:
            try:
                with browser.job(timeout=8): n = browser.relogin()
                return {"content": [{"type": "text", "text": f"ClickUp session refreshed in reclickup's headless browser ({n} cookies)."}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        if p.get("name") != TOOL["name"]:
            # Answer within CALL_BUDGET: the client drops a call after ~60 s and then cannot tell whether it ran.
            deadline = time.time() + CALL_BUDGET
            if UP.dead(): UP.restart()
            UP.ready.wait(READY_WAIT)
            if not UP.ready.is_set():
                return {"content": [{"type": "text", "text": f"NOT_READY: the official ClickUp MCP is not connected yet; "
                         f"{UP.state()}. Nothing was sent to ClickUp, so calling this tool again is safe."}], "isError": True}
            if UP.error:
                err = UP.error; UP.restart()
                return {"content": [{"type": "text", "text": f"NOT_READY: the official ClickUp MCP stopped ({err}). It is "
                         "restarting now; nothing was sent to ClickUp, so call this tool again in a few seconds."}], "isError": True}
            return call_upstream(p, deadline)
        deadline = time.time() + CALL_BUDGET
        try:
            title = a.get("title")
            md = a.get("markdown") or ""
            if not title and md.lstrip().startswith("# "): title = md.lstrip().splitlines()[0][2:].replace("**", "").strip()
            if a.get("delta"): delta = a["delta"]
            elif a.get("markdown"): delta = md_to_delta(a["markdown"])
            else: raise RuntimeError("Pass either 'markdown' or 'delta'.")
            append = a.get("mode") == "append"
            return {"content": [{"type": "text", "text": summary(write_doc(a["page_url"], delta, append, title, deadline), append)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    if m == "ping": return {}
    if mid is None: return None          # notification
    if m and m.split("/")[0] in FORWARDED:
        return forward(m, msg.get("params") or {})
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


def shutdown(*_):
    """Leave nothing running: the headless Edge is detached, so it would outlive this process. Another reclickup
    copy may still be using it, so stop it only if nobody is."""
    try: browser.stop_if_unused()
    except Exception: pass
    kill_tree(UP.proc)


def main():
    import atexit, signal
    # MCP stdio is UTF-8; Windows would otherwise decode the client's Vietnamese text as cp1252.
    for stream in (sys.stdin, sys.stdout):
        try: stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    atexit.register(shutdown)
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None: signal.signal(sig, lambda *a: sys.exit(0))
    UP.start()
    for line in sys.stdin:
        if not line.strip(): continue
        try: msg = json.loads(line)
        except Exception: continue
        if msg.get("method") == "initialize": respond(msg)          # in order
        else: threading.Thread(target=respond, args=(msg,), daemon=True).start()


if __name__ == "__main__":
    main()
