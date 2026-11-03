"""The browser reclickup drives: a private *headless* Edge (no window) on its own profile and port,
modelled on refigma-mcp's lib/browser.mjs.

- Started on demand, stopped again after IDLE_STOP seconds without use (nothing left running hot).
- The clickup.com session is copied in from the debug Edge (:9222) if it is up and signed in,
  else decrypted from the user's real Edge profile (macOS Keychain prompt "Microsoft Edge Safe Storage").
- On Windows the real profile cannot be read (app-bound encrypted cookies), so relogin() opens this
  profile in a visible Edge window once for the user to sign in; the profile keeps the session.
"""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request

import websocket

IS_WIN = sys.platform == "win32"
PORT = int(os.environ.get("RECLICKUP_PORT", "9335"))
CDP = f"http://127.0.0.1:{PORT}"
PROFILE = os.path.join(os.path.expanduser("~"), ".reclickup", "headless-profile")
IDLE_STOP = int(os.environ.get("RECLICKUP_IDLE_STOP", "600"))
LOGIN_WAIT = int(os.environ.get("RECLICKUP_LOGIN_WAIT", "40"))   # one call must answer well inside the client's ~60 s
AUTH = "cu_jwt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0"
      if IS_WIN else
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0")


def find_edge():
    if os.environ.get("RECLICKUP_BROWSER"): return os.environ["RECLICKUP_BROWSER"]
    if not IS_WIN: return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    exe = os.path.join("Microsoft", "Edge", "Application", "msedge.exe")
    dirs = [d for d in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")) if d]
    return next((os.path.join(d, exe) for d in dirs if os.path.exists(os.path.join(d, exe))), os.path.join(dirs[0] if dirs else r"C:\Program Files (x86)", exe))


EDGE = find_edge()


def alive(port=PORT):
    try: return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2))
    except Exception: return None


class Session:
    """CDP session on a browser or page websocket."""
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


def browser_cookies(port=PORT):
    v = alive(port)
    if not v: return []
    b = Session(v["webSocketDebuggerUrl"])
    try: return b.call("Storage.getCookies").get("cookies", [])
    finally: b.close()


def is_clickup(c): return c.get("domain", "").lstrip(".").endswith("clickup.com")


def logged_in(cookies):
    now = time.time()
    return any(c["name"] == AUTH and is_clickup(c) and (not c.get("expires") or c["expires"] < 0 or c["expires"] > now)
               for c in cookies)


def real_edge_cookies():
    """clickup.com cookies of the user's real Edge profile (macOS), decrypted via the Keychain."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    profile = os.environ.get("RECLICKUP_EDGE_PROFILE", os.path.expanduser("~/Library/Application Support/Microsoft Edge/Default"))
    pw = subprocess.run(["security", "find-generic-password", "-ws", "Microsoft Edge Safe Storage"],
                        capture_output=True, text=True).stdout.strip().encode()
    if not pw: raise RuntimeError('could not read "Microsoft Edge Safe Storage" from the Keychain (prompt denied?)')
    key = hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", 1003, 16)

    def dec(b):
        if not b: return ""
        if b[:3] not in (b"v10", b"v11"):
            try: return b.decode()
            except Exception: return ""
        d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        p = d.update(b[3:]) + d.finalize()
        if p: p = p[:-p[-1]]
        try: return p.decode()
        except UnicodeDecodeError: return p[32:].decode(errors="replace")   # Chromium 130+: 32-byte host hash prefix

    fd, tmp = tempfile.mkstemp(suffix=".db"); os.close(fd)
    try:
        shutil.copyfile(os.path.join(profile, "Cookies"), tmp)
        rows = sqlite3.connect(tmp).execute(
            "select host_key,name,encrypted_value,path,is_secure,is_httponly,expires_utc,samesite from cookies "
            "where host_key like '%clickup.com'").fetchall()
    finally:
        os.remove(tmp)
    out = []
    for h, n, v, path, sec, ho, exp, ss in rows:
        val = dec(v)
        if not val: continue
        c = {"name": n, "value": val, "domain": h, "path": path, "secure": bool(sec), "httpOnly": bool(ho)}
        s = {0: "None", 1: "Lax", 2: "Strict"}.get(ss)
        if s: c["sameSite"] = s
        if exp: c["expires"] = exp / 1_000_000 - 11644473600
        out.append(c)
    return out


def session_cookies(from_real_edge=False):
    if not from_real_edge and alive(9222):     # the debug Edge is signed in: no Keychain prompt needed
        ck = [c for c in browser_cookies(9222) if is_clickup(c)]
        if logged_in(ck):
            drop = {"size", "session", "priority", "sourceScheme", "sourcePort", "partitionKey"}
            return [{k: v for k, v in c.items() if k not in drop} for c in ck]
    if IS_WIN: return []
    return real_edge_cookies()


def import_session(from_real_edge=False):
    cookies = session_cookies(from_real_edge)
    if not logged_in(cookies):
        raise RuntimeError("NOT_LOGGED_IN: reclickup has no clickup.com session yet - run clickup_relogin"
                           + (" and sign in in the Edge window it opens" if IS_WIN else " (sign in to ClickUp in Microsoft Edge first)"))
    b = Session(alive()["webSocketDebuggerUrl"])
    try: b.call("Storage.setCookies", {"cookies": cookies})
    finally: b.close()
    return len(cookies)


def launch(headless=True, url="about:blank"):
    os.makedirs(PROFILE, exist_ok=True)
    # The visible sign-in window gets no automation flags: Edge shows a yellow "unsupported command-line flag"
    # warning for --disable-blink-features, and the user types their own password there anyway.
    hidden = ["--headless=new", f"--user-agent={UA}", "--disable-blink-features=AutomationControlled"] if headless else []
    args = [EDGE] + hidden + [f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", "--window-size=1600,1000",
                              "--no-first-run", "--no-default-browser-check", "--disable-extensions", url]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WIN: kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else: kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
    for _ in range(75):
        v = alive()
        if v: return v
        time.sleep(0.2)
    raise RuntimeError(f"could not start Edge ({EDGE})")


def stop():
    v = alive()
    if not v: return
    b = Session(v["webSocketDebuggerUrl"])
    try: b.call("Browser.close")
    except Exception: pass
    finally: b.close()
    for _ in range(50):
        if not alive(): break
        time.sleep(0.2)
    time.sleep(0.5)        # the profile lock goes a moment after the port


# ------------------------------------------------------------------ sharing the browser between processes
# Claude Desktop starts reclickup more than once (one per window/agent), and every copy drives the SAME Edge
# (one port, one profile). A job (a Doc write, a relogin) holds the lock file shared by all copies, and the idle
# stop / shutdown only close Edge when no copy is using it.
STATE_DIR = os.path.join(os.path.expanduser("~"), ".reclickup")
LOCK_FILE = os.path.join(STATE_DIR, "browser.lock")
LAST_FILE = os.path.join(STATE_DIR, "browser.last")      # "<pid> <unix time>" of the last use by any copy
LOGIN_MARK = os.path.join(STATE_DIR, "login-window")     # exists while Edge runs as the visible sign-in window


class FileLock:
    """Exclusive lock on LOCK_FILE across processes (and threads: each acquire opens its own handle)."""
    def __init__(self): self.f = None
    def acquire(self, timeout=0.0):
        os.makedirs(STATE_DIR, exist_ok=True)
        end = time.time() + timeout
        while True:
            f = open(LOCK_FILE, "a+")
            try:
                if IS_WIN:
                    import msvcrt
                    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.f = f; return True
            except OSError:
                f.close()
                if time.time() >= end: return False
                time.sleep(0.2)
    def release(self):
        f, self.f = self.f, None
        if not f: return
        try:
            if IS_WIN:
                import msvcrt
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError: pass
        f.close()


class Busy(RuntimeError): pass


class job:
    """with browser.job(timeout): one browser job at a time across all reclickup processes."""
    def __init__(self, timeout): self.timeout = timeout; self.lock = FileLock()
    def __enter__(self):
        if not self.lock.acquire(max(0.0, self.timeout)):
            raise Busy("BUSY: another reclickup job is using the browser right now (a Doc write or a sign-in). "
                       "Nothing was changed; wait a few seconds and call the tool again.")
        hold(); return self
    def __exit__(self, *exc):
        touch(); self.lock.release()


def last_use():
    try:
        with open(LAST_FILE) as f: pid, t = f.read().split()
        return int(pid), float(t)
    except Exception: return None, 0.0


def mark_use():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LAST_FILE, "w") as f: f.write(f"{os.getpid()} {time.time()}")
    except OSError: pass


_idle = {"timer": None}
_lock = threading.Lock()


def _arm(delay):
    with _lock:
        if _idle["timer"]: _idle["timer"].cancel()
        t = threading.Timer(max(1.0, delay), _idle_stop); t.daemon = True; t.start(); _idle["timer"] = t


def touch():
    """Record a use and (re)arm the idle timer: Edge stops IDLE_STOP s after the last use by ANY copy."""
    mark_use(); _arm(IDLE_STOP)


def _idle_stop():
    pid, t = last_use()
    left = IDLE_STOP - (time.time() - t)
    if left > 1: _arm(left); return                    # another copy used it since: wait for its idle time
    lk = FileLock()
    if not lk.acquire(0): _arm(30); return               # a job is running in some copy
    try: stop()
    finally: lk.release()


def stop_if_unused():
    """On exit: close Edge unless another reclickup copy is using it or used it recently."""
    pid, t = last_use()
    if pid not in (None, os.getpid()) and time.time() - t < IDLE_STOP: return
    lk = FileLock()
    if not lk.acquire(0): return
    try: stop()
    finally: lk.release()


def hold():
    """Cancel the idle stop while a job runs; the caller re-arms it with touch() when done."""
    with _lock:
        if _idle["timer"]: _idle["timer"].cancel(); _idle["timer"] = None


def ensure():
    """Headless Edge up and signed in to ClickUp; returns the CDP base URL. Run inside a job()."""
    if not alive() or os.path.exists(LOGIN_MARK):   # the visible sign-in window is no place for a write
        if alive(): stop()
        _clear_login_mark(); launch()
    if not logged_in(browser_cookies()): import_session()
    return CDP


def _clear_login_mark():
    try: os.remove(LOGIN_MARK)
    except OSError: pass


def relogin():
    """Refresh the session. macOS: copy from the real Edge profile (freshest). Windows: sign in once in a window.

    On Windows a call waits at most LOGIN_WAIT s. If the user has not signed in by then, the window stays open and
    LOGIN_PENDING is raised: calling relogin() again (from any reclickup copy) picks the sign-in up. Run inside a job()."""
    if IS_WIN:
        if not (os.path.exists(LOGIN_MARK) and alive()):
            stop(); launch(headless=False, url="https://app.clickup.com/login")
            with open(LOGIN_MARK, "w") as f: f.write(str(time.time()))
        end = time.time() + LOGIN_WAIT
        while True:
            if not alive():
                _clear_login_mark()
                raise RuntimeError("NOT_LOGGED_IN: the sign-in window was closed before ClickUp signed in")
            if logged_in(browser_cookies()): break
            if time.time() > end:        # the window closes itself after the idle timeout if nobody signs in
                raise RuntimeError("LOGIN_PENDING: an Edge window is open at the ClickUp login. Ask the user to sign "
                                   "in there, then call clickup_relogin again.")
            time.sleep(1)
        time.sleep(2); stop(); _clear_login_mark(); launch()
        n = len([c for c in browser_cookies() if is_clickup(c)])
    else:
        if not alive(): launch()
        n = import_session(from_real_edge=True)
    return n
