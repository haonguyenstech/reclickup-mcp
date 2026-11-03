"""Re-enable reclickup-mcp tools that Claude Desktop switched off (enabled_mcp_tools = false).
Quit Claude Desktop first.  python enable_tools.py [--apply]"""
import glob, json, os, sys
home = os.path.expanduser("~")
roots = [os.path.join(home, "Library", "Application Support", d) for d in ("Claude", "Claude-3p")]
for env in ("APPDATA", "LOCALAPPDATA"):
    base = os.environ.get(env)
    if base:
        roots += [os.path.join(base, d) for d in ("Claude", "Claude-3p")]
        roots += glob.glob(os.path.join(base, "Packages", "Claude_*", "LocalCache", "Roaming", "Claude*"))
apply = "--apply" in sys.argv
found = 0
for root in roots:
    for p in glob.glob(os.path.join(root, "local-agent-mode-sessions", "*", "*", "cowork_account_settings.json")):
        found += 1
        d = json.load(open(p, encoding="utf-8")); tools = d.get("enabled_mcp_tools") or {}
        off = [k for k, v in tools.items() if k.startswith("local:reclickup-mcp:") and v is False]
        names = sorted({k.split(":")[2].split("-")[0] for k in off})
        print(f"{p}\n  disabled reclickup tools: {names or 'none'}")
        if off and apply:
            for k in off: tools[k] = True
            with open(p, "w", encoding="utf-8") as f: json.dump(d, f)
            print("  -> re-enabled", len(off), "entries")
if not found: print("no cowork_account_settings.json found")
elif off and not apply: print("Run again with --apply (Claude Desktop must be closed).")
