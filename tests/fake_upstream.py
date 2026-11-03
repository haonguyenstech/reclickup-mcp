"""A stand-in for `npx mcp-remote https://mcp.clickup.com/mcp`, driven by environment variables:

FAKE_MODE   normal | hang (never answers) | exit (exits at once) | wedge (first process ignores tools/call and ping,
            later ones work) | slow (tools/call answers after FAKE_DELAY s) | flaky (the first tools/call of each tool fails
            with "fetch failed", like a network blip)
FAKE_STATE  file counting how many fake processes have started (to tell the first from a restarted one)
"""
import json, os, sys, threading, time

mode = os.environ.get("FAKE_MODE", "normal")
state = os.environ.get("FAKE_STATE")
n = 0
if state:
    n = int(open(state).read()) if os.path.exists(state) else 0
    open(state, "w").write(str(n + 1))
if mode == "exit": sys.exit(1)
if mode == "hang": time.sleep(600); sys.exit(0)
wedged = mode == "wedge" and n == 0
lock = threading.Lock()


def out(m):
    with lock:
        sys.stdout.buffer.write((json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8")); sys.stdout.buffer.flush()


TOOLS = [{"name": "clickup_get_task", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True},
          "_meta": {"ui": {"resourceUri": "ui://clickup/task-card.html"}}},
         {"name": "clickup_update_task", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}},
         {"name": "clickup_get_threaded_comments", "inputSchema": {"type": "object"}}]
failed_once = set()

for raw in sys.stdin.buffer:
    m = json.loads(raw.decode("utf-8")); mid = m.get("id"); meth = m.get("method")
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}, "resources": {}},
                                                     "serverInfo": {"name": "fake", "version": "1"}}})
    elif meth == "tools/list": out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif meth == "ping":
        if not wedged: out({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif meth == "resources/list":
        out({"jsonrpc": "2.0", "id": mid, "result": {"resources": [{"uri": "ui://clickup/task-card.html", "name": "task-card"}]}})
    elif meth == "resources/read":
        out({"jsonrpc": "2.0", "id": mid, "result": {"contents": [{"uri": m["params"]["uri"], "mimeType": "text/html;profile=mcp-app",
                                                                   "text": "<html>card</html>"}]}})
    elif meth == "prompts/list":
        out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})
    elif meth == "tools/call":
        if wedged: continue
        if mode == "flaky" and m["params"]["name"] not in failed_once:
            failed_once.add(m["params"]["name"])
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "mcp-remote: fetch failed"}}); continue
        text = f"proc {n} | Bình luận: Thời gian chờ ở đây | got=" + json.dumps(m["params"].get("arguments", {}), ensure_ascii=False)
        reply = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        if mode == "slow": threading.Timer(float(os.environ.get("FAKE_DELAY", "6")), out, args=(reply,)).start()
        else: out(reply)
