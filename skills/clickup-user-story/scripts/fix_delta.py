"""Repair an existing ClickUp task description delta: column widths (total 840), green bold header row (or key column
of the "User Story Name" table), bold "Scenario N" lines. Text, links, ids, other colours and non-table content are kept.
   python3 -I fix_delta.py old.json > new.json        (old.json may hold the raw `content` string)"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")   # Windows defaults to cp1252
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md2delta import PRESETS, HEADER_BG, fallback

d = json.load(open(sys.argv[1], encoding="utf-8"))
if isinstance(d, str): d = json.loads(d)
SCEN = re.compile(r'^\s*Scenario\s+\d+', re.I)

def lines(ops):
    """Cell ops as lines of (insert, attrs) segments; a newline op's own attrs are kept. Handles merged ops."""
    out=[]; cur=[]
    for o in ops:
        ins=o["insert"]; a=o.get("attributes")
        if not isinstance(ins,str): cur.append((ins,a)); continue
        parts=ins.split("\n")
        for i,p in enumerate(parts):
            if p: cur.append((p,a))
            if i<len(parts)-1: out.append((cur,a if ins=="\n" else None)); cur=[]
    if cur: out.append((cur,None))
    return out

def rebuild(ops, force_bold=False):
    res=[]
    for segs,nl in lines(ops):
        text="".join(s for s,_ in segs if isinstance(s,str))
        b = force_bold or bool(SCEN.match(text))
        for s,a in segs:
            a=dict(a or {})
            if b and isinstance(s,str): a["bold"]=True
            res.append({"insert":s,**({"attributes":a} if a else {})})
        res.append({"insert":"\n",**({"attributes":nl} if nl else {})})
    return res

def cell_text(c): return "".join(o["insert"] for o in c["content"] if isinstance(o["insert"],str)).strip()

report=[]
for o in d["ops"]:
    ins=o.get("insert")
    if not (isinstance(ins,dict) and "table-embed" in ins): continue
    te=ins["table-embed"]; n=len(te["columns"])
    header=[cell_text(te["cells"].get(f"1:{c}",{"content":[]})) for c in range(1,n+1)]
    kv = header[0]=="User Story Name"
    key=("User Story Name",) if kv else tuple(header)
    widths=PRESETS.get(key) or fallback(header)
    if len(widths)!=n: widths=fallback(header)
    old=[c.get("attributes",{}).get("width") for c in te["columns"]]
    for col,w in zip(te["columns"],widths): col.setdefault("attributes",{})["width"]=str(w)
    for k,cell in te["cells"].items():
        r,c=map(int,k.split(":"))
        is_head=(r==1 and not kv) or (kv and c==1)
        cell["content"]=rebuild(cell["content"], force_bold=is_head)
        if is_head: cell.setdefault("attributes",{})["cell-bg-color"]=HEADER_BG
    report.append(f"{header[:3]}... widths {old} -> {widths}")
print("\n".join(report), file=sys.stderr)
print(json.dumps(d,ensure_ascii=False,separators=(",",":")))
