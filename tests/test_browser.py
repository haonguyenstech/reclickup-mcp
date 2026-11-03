"""browser.py without a real browser: the cross-process lock, the shared idle stop, the Windows sign-in flow."""
import os, shutil, subprocess, sys, tempfile, textwrap, time, types, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "reclickup_mcp"))
import browser


class Isolated(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="reclickup-browser-")
        self.saved = {k: getattr(browser, k) for k in ("STATE_DIR", "LOCK_FILE", "LAST_FILE", "LOGIN_MARK", "alive", "launch",
                                                        "stop", "browser_cookies", "time", "IS_WIN", "IDLE_STOP")}
        browser.STATE_DIR = self.d; browser.LOCK_FILE = os.path.join(self.d, "browser.lock")
        browser.LAST_FILE = os.path.join(self.d, "browser.last"); browser.LOGIN_MARK = os.path.join(self.d, "login-window")
        self.st = {"up": False, "cookies": [], "launches": [], "stops": 0}
        browser.alive = lambda port=browser.PORT: {"webSocketDebuggerUrl": "x"} if self.st["up"] else None
        browser.launch = lambda headless=True, url="about:blank": (self.st.update(up=True), self.st["launches"].append(headless))
        def stop(): self.st["stops"] += 1; self.st["up"] = False
        browser.stop = stop
        browser.browser_cookies = lambda port=browser.PORT: self.st["cookies"]

    def tearDown(self):
        browser.hold()
        for k, v in self.saved.items(): setattr(browser, k, v)
        shutil.rmtree(self.d, ignore_errors=True)


class LockTests(Isolated):
    def test_lock_is_exclusive_across_processes(self):
        code = textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {os.path.join(ROOT, 'reclickup_mcp')!r})
            import browser; browser.STATE_DIR = {self.d!r}; browser.LOCK_FILE = {browser.LOCK_FILE!r}
            l = browser.FileLock(); assert l.acquire(5); print('locked', flush=True); time.sleep(3); l.release()""")
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "locked")
        mine = browser.FileLock()
        self.assertFalse(mine.acquire(0.5))                     # held by the other process
        self.assertTrue(mine.acquire(10)); mine.release()       # free once it lets go
        p.wait(timeout=10)

    def test_job_raises_busy_when_held(self):
        other = browser.FileLock(); self.assertTrue(other.acquire(0))
        try:
            with self.assertRaises(browser.Busy):
                with browser.job(timeout=0.3): pass
        finally: other.release()
        with browser.job(timeout=1): pass                       # free again

    def test_idle_stop_respects_other_copies(self):
        browser.IDLE_STOP = 100
        with open(browser.LAST_FILE, "w") as f: f.write(f"999999 {time.time()}")   # another copy used Edge just now
        browser._idle_stop(); self.assertEqual(self.st["stops"], 0)
        with open(browser.LAST_FILE, "w") as f: f.write(f"999999 {time.time() - 200}")
        browser._idle_stop(); self.assertEqual(self.st["stops"], 1)

    def test_idle_stop_waits_for_a_running_job(self):
        browser.IDLE_STOP = 1
        with open(browser.LAST_FILE, "w") as f: f.write(f"1 {time.time() - 50}")
        other = browser.FileLock(); other.acquire(0)
        try: browser._idle_stop(); self.assertEqual(self.st["stops"], 0)
        finally: other.release()

    def test_exit_leaves_edge_to_a_copy_that_used_it(self):
        browser.IDLE_STOP = 100
        with open(browser.LAST_FILE, "w") as f: f.write(f"999999 {time.time()}")
        browser.stop_if_unused(); self.assertEqual(self.st["stops"], 0)
        with open(browser.LAST_FILE, "w") as f: f.write(f"{os.getpid()} {time.time()}")
        browser.stop_if_unused(); self.assertEqual(self.st["stops"], 1)


class WindowsReloginTests(Isolated):
    def test_pending_then_picked_up(self):
        browser.IS_WIN = True
        browser.time = types.SimpleNamespace(time=time.time, sleep=lambda s: time.sleep(min(s, 0.02)))
        old_wait = browser.LOGIN_WAIT; browser.LOGIN_WAIT = 0.3
        try:
            with self.assertRaises(RuntimeError) as e: browser.relogin()
            self.assertIn("LOGIN_PENDING", str(e.exception)); self.assertEqual(self.st["launches"], [False])
            self.assertTrue(os.path.exists(browser.LOGIN_MARK))
            self.st["cookies"] = [{"name": "cu_jwt", "domain": ".clickup.com", "expires": -1}]   # the user signed in
            self.assertEqual(browser.relogin(), 1)
            self.assertEqual(self.st["launches"], [False, True])                           # reused the window, then headless
            self.assertFalse(os.path.exists(browser.LOGIN_MARK))
        finally: browser.LOGIN_WAIT = old_wait

    def test_write_does_not_run_in_the_sign_in_window(self):
        open(browser.LOGIN_MARK, "w").close(); self.st["up"] = True
        self.st["cookies"] = [{"name": "cu_jwt", "domain": ".clickup.com", "expires": -1}]
        browser.ensure()
        self.assertEqual(self.st["stops"], 1); self.assertEqual(self.st["launches"], [True])
        self.assertFalse(os.path.exists(browser.LOGIN_MARK))


if __name__ == "__main__":
    unittest.main()
