# Draft markdown -> ClickUp Quill delta (copied from the clickup-user-story skill)
import json, re, sys
TOTAL = 840
HEADER_BG = "green"   # ClickUp cell palette: red, orange, yellow, blue, purple, pink, green, gray
# column width presets keyed by header row (each sums to 840)
PRESETS = {
 ("User Story Name",): [170, 670],
 ("Step","Description"): [90, 750],
 ("No.","Acceptance Criteria"): [60, 780],
 ("No.","Field name","Field Type","Required?","Description"): [60, 170, 120, 110, 380],
 ("Code","Type","Message","Shown when"): [70, 120, 370, 280],
 ("Depends On","Reason"): [300, 540],
 ("No.","Question","Related"): [60, 610, 170],
}
NARROW = {"no.","no","#","step","code","id","stt"}
def fallback(header):
    w=[60 if h.strip().lower() in NARROW else None for h in header]
    rest=TOTAL-sum(x for x in w if x); k=sum(1 for x in w if x is None) or 1
    w=[x if x else rest//k for x in w]; w[-1]+=TOTAL-sum(w); return w
def inline(text):
    ops=[]; pat=re.compile(r'\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)'); pos=0
    for m in pat.finditer(text):
        if m.start()>pos: ops.append({"insert":text[pos:m.start()]})
        if m.group(1) is not None: ops.append({"insert":m.group(1),"attributes":{"bold":True}})
        else: ops.append({"insert":m.group(2),"attributes":{"link":m.group(3)}})
        pos=m.end()
    if pos<len(text): ops.append({"insert":text[pos:]})
    return [o for o in ops if o["insert"]!=""]
def unesc(s): return s.replace("&lt;","<").replace("&gt;",">").replace("&amp;","&")
SCENARIO = re.compile(r'^\s*(?:\*\*)?\s*(Scenario\s+\d+[^*]*?)\s*(?:\*\*)?\s*$', re.I)
def cell_ops(text):
    ops=[]
    for part in unesc(text).split("<br>"):
        m=SCENARIO.match(part)
        if m:   # always bold the scenario title line, whether or not the spec had **...**
            ops.append({"insert":m.group(1).strip(),"attributes":{"bold":True}})
        else:
            ops+=inline(part)
        ops.append({"insert":"\n"})
    return ops
def bold(ops): return [dict(o,attributes={**o.get("attributes",{}),"bold":True}) if o["insert"]!="\n" else o for o in ops]
def split_row(line): return [c.strip() for c in line.strip().strip("|").split("|")]
def md_to_delta(text):
    src=text.splitlines()
    ops=[]; t=[0]
    def add_table(rows):
        t[0]+=1; n=len(rows[0]); kv = rows[0][0]=="User Story Name"
        key=("User Story Name",) if kv else tuple(rows[0])
        widths=PRESETS.get(key) or fallback(rows[0])
        if len(widths)!=n: widths=fallback(rows[0])
        cells={}
        for r,row in enumerate(rows,1):
            for c in range(n):
                co=cell_ops(row[c] if c<len(row) else "")
                attrs={"colspan":"1","rowspan":"1"}
                if (r==1 and not kv) or (kv and c==0):   # header row, or key column of the key-value table
                    co=bold(co); attrs["cell-bg-color"]=HEADER_BG
                cells[f"{r}:{c+1}"]={"content":co,"attributes":attrs}
        ops.append({"insert":{"table-embed":{
            "rows":[{"insert":{"id":f"row-t{t[0]}r{i}"}} for i in range(len(rows))],
            "columns":[{"insert":{"id":f"column-t{t[0]}c{i}"},"attributes":{"width":str(w)}} for i,w in enumerate(widths)],
            "cells":cells}}})
        ops.append({"insert":"\n"})
    i=0
    while i<len(src):
        line=src[i]
        if line.startswith("|"):
            rows=[]
            while i<len(src) and src[i].startswith("|"):
                r=split_row(src[i])
                if not all(re.fullmatch(r"-+",c.replace(" ","").replace(":","")) for c in r): rows.append(r)
                i+=1
            add_table(rows); continue
        if i==0 and line.startswith("# "): i+=1; continue   # title = task name
        if line.startswith("# "):
            txt=line[2:].replace("**","").strip()
            if txt: ops.append({"insert":txt,"attributes":{"bold":True}}); ops.append({"insert":"\n","attributes":{"header":1}})
        elif line.strip():
            ops+=inline(unesc(line)); ops.append({"insert":"\n"})
        i+=1
    return {"ops":ops}
