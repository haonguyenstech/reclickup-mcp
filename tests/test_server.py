"""The MCP proxy against a fake official server (tests/fake_upstream.py): no ClickUp account, no network.

Run: python -m unittest discover -s tests -v
"""
import json, os, queue, shutil, subprocess, sys, tempfile, threading, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "reclickup_mcp", "server.py")
FAKE = os.path.join(ROOT, "tests", "fake_upstream.py")
BUDGET = 12


def npx_wrapper(d):
    """RECLICKUP_NPX is called as `<npx> -y mcp-remote@x <url>`: a wrapper that runs the fake instead."""
    if sys.platform == "win32":
        p = os.path.join(d, "npx.cmd")
        with open(p, "w") as f: f.write(f'@"{sys.executable}" "{FAKE}"\r\n')
    else:
        p = os.path.join(d, "npx.sh")
        with open(p, "w") as f: f.write(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}"\n')
        os.chmod(p, 0o755)
    return p


class Server:
    def __init__(self, mode="normal", npx=None, **env):
        self.home = tempfile.mkdtemp(prefix="reclickup-test-")
        e = dict(os.environ, HOME=self.home, USERPROFILE=self.home, RECLICKUP_CALL_BUDGET=str(BUDGET),
                 RECLICKUP_SLOW_CALL="4", FAKE_MODE=mode, FAKE_STATE=os.path.join(self.home, "fake-count"),
                 RECLICKUP_NPX=npx or npx_wrapper(self.home), **env)
        for k in ("PYTHONUTF8", "PYTHONIOENCODING"): e.pop(k, None)     # prove the server sets UTF-8 itself
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=e)
        self.q = {}; self.notes = queue.Queue(); self.n = 0
        threading.Thread(target=self._read, daemon=True).start()
        self.call_raw("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})

    def _read(self):
        for raw in self.p.stdout:
            m = json.loads(raw.decode("utf-8"))
            if "id" in m: self.q.setdefault(m["id"], queue.Queue()).put(m)
            else: self.notes.put(m)

    def call_raw(self, method, params, timeout=BUDGET + 15):
        self.n += 1; i = self.n
        self.q.setdefault(i, queue.Queue())
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        return self.q[i].get(timeout=timeout)

    def tool(self, name, args=None):
        t = time.time(); m = self.call_raw("tools/call", {"name": name, "arguments": args or {}})
        r = m["result"]; return r.get("isError", False), r["content"][0]["text"], time.time() - t

    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=20)
        except Exception: self.p.kill()
        shutil.rmtree(self.home, ignore_errors=True)


class ProxyTests(unittest.TestCase):
    def test_lists_and_calls_official_tools(self):
        s = Server()
        try:
            names = [t["name"] for t in s.call_raw("tools/list", {})["result"]["tools"]]
            self.assertIn("clickup_get_task", names); self.assertIn("clickup_doc_write", names); self.assertIn("clickup_relogin", names)
            err, text, _ = s.tool("clickup_get_task", {"task_id": "1"})
            self.assertFalse(err); self.assertIn("proc 0", text)
        finally: s.close()

    def test_mcp_apps_views_are_stripped_from_the_tool_list(self):
        """Claude Desktop drops local tools that declare an MCP Apps view (create/get/update task...)."""
        s = Server()
        try:
            time.sleep(1)
            t = [x for x in s.call_raw("tools/list", {})["result"]["tools"] if x["name"] == "clickup_get_task"][0]
            self.assertNotIn("ui", t.get("_meta", {})); self.assertNotIn("ui/resourceUri", t.get("_meta", {}))
            self.assertEqual(t["annotations"], {"readOnlyHint": True})
        finally: s.close()
        s = Server(RECLICKUP_MCP_APPS="1")
        try:
            time.sleep(1)
            t = [x for x in s.call_raw("tools/list", {})["result"]["tools"] if x["name"] == "clickup_get_task"][0]
            self.assertIn("ui", t["_meta"])
        finally: s.close()

    def test_vietnamese_round_trip(self):
        """Windows decoded pipes as cp1252: 'ờ' (E1 BB 9D) killed the reader and every later call timed out."""
        s = Server()
        try:
            for _ in range(2):
                err, text, dt = s.tool("clickup_get_threaded_comments", {"text": "Thời gian ờ Ở ự"})
                self.assertFalse(err, text); self.assertIn("Thời gian chờ ở đây", text); self.assertIn("Thời gian ờ Ở ự", text)
                self.assertLess(dt, 5)
        finally: s.close()

    def test_tool_list_falls_back_to_bundled_snapshot(self):
        s = Server(mode="hang")
        try:
            names = [t["name"] for t in s.call_raw("tools/list", {}, timeout=30)["result"]["tools"]]
            for n in ("clickup_create_task", "clickup_update_task", "clickup_get_document_pages", "clickup_doc_write"):
                self.assertIn(n, names)
        finally: s.close()

    def test_hung_upstream_answers_not_ready_within_budget(self):
        s = Server(mode="hang")
        try:
            err, text, dt = s.tool("clickup_get_task")
            self.assertTrue(err); self.assertTrue(text.startswith("NOT_READY"), text); self.assertLess(dt, BUDGET)
        finally: s.close()

    def test_dead_upstream_fails_fast_and_restarts(self):
        s = Server(mode="exit")
        try:
            time.sleep(2)
            err, text, dt = s.tool("clickup_get_task")
            self.assertTrue(err); self.assertIn("NOT_READY", text); self.assertLess(dt, 3)
            time.sleep(1)
            with open(os.path.join(s.home, "fake-count")) as f:
                self.assertGreaterEqual(int(f.read()), 2)          # it restarted the upstream
        finally: s.close()

    def test_wedged_connection_is_restarted(self):
        s = Server(mode="wedge")
        try:
            time.sleep(1)
            err, text, dt = s.tool("clickup_get_task")
            self.assertTrue(err); self.assertTrue(text.startswith("STALE_CONNECTION"), text); self.assertLess(dt, BUDGET)
            err, text, dt = s.tool("clickup_get_task")
            self.assertFalse(err, text); self.assertIn("proc 1", text)
        finally: s.close()

    def test_slow_but_alive_call_is_not_restarted(self):
        s = Server(mode="slow", FAKE_DELAY="6")
        try:
            time.sleep(1)
            err, text, dt = s.tool("clickup_get_task")
            self.assertFalse(err, text); self.assertIn("proc 0", text); self.assertGreater(dt, 5)
        finally: s.close()

    def test_transient_error_retried_for_reads_only(self):
        s = Server(mode="flaky")
        try:
            time.sleep(1)
            err, text, _ = s.tool("clickup_get_task")            # read-only: retried once, succeeds
            self.assertFalse(err, text); self.assertIn("proc 0", text)
            err, text, _ = s.tool("clickup_update_task")         # a write is never repeated
            self.assertTrue(err); self.assertIn("fetch failed", text)
        finally: s.close()

    def test_resources_are_forwarded(self):
        """MCP Apps: the client fetches ui://clickup/... with resources/read."""
        s = Server()
        try:
            init = s.call_raw("initialize", {})["result"]
            self.assertIn("resources", init["capabilities"])
            time.sleep(1)
            r = s.call_raw("resources/read", {"uri": "ui://clickup/task-card.html"})["result"]
            self.assertEqual(r["contents"][0]["text"], "<html>card</html>")
            self.assertEqual(s.call_raw("resources/list", {})["result"]["resources"][0]["uri"], "ui://clickup/task-card.html")
            self.assertEqual(s.call_raw("prompts/list", {})["result"], {"prompts": []})   # upstream has no prompts
        finally: s.close()

    def test_resources_list_before_ready_is_empty_not_an_error(self):
        s = Server(mode="hang")
        try:
            self.assertEqual(s.call_raw("resources/list", {}, timeout=30)["result"], {"resources": []})
        finally: s.close()


if __name__ == "__main__":
    unittest.main()
