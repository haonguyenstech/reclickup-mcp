"""Sanity check a task delta before creating the task: width sum, green cells, bold scenario titles per table.
   python3 -I check_delta.py delta.json"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")   # Windows defaults to cp1252
d = json.load(open(sys.argv[1], encoding="utf-8"))
if isinstance(d, str): d = json.loads(d)
for n, o in enumerate((o for o in d["ops"] if isinstance(o["insert"], dict) and "table-embed" in o["insert"]), 1):
    te = o["insert"]["table-embed"]
    head = "".join(x["insert"] for x in te["cells"].get("1:1", {"content": []})["content"] if isinstance(x["insert"], str)).strip()
    green = [k for k, v in te["cells"].items() if v.get("attributes", {}).get("cell-bg-color")]
    loose = [x["insert"] for v in te["cells"].values() for x in v["content"]
             if isinstance(x["insert"], str) and x["insert"].lstrip().lower().startswith("scenario") and not x.get("attributes", {}).get("bold")]
    print(f"table {n} ({head[:24]}): sum {sum(int(c['attributes']['width']) for c in te['columns'])}, green cells {len(green)}, scenarios not bold: {loose}")
