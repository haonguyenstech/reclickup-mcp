# Draft markdown -> ClickUp Quill delta (the clickup-user-story skill ships the same file as scripts/md2delta.py)
#   python3 md2delta.py draft.md > delta.json
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

# Markdown backslash escapes. ClickUp's own markdown export writes them (clickup\_doc\_write, \## ...), so a page read
# back and written again must not keep the backslashes. Escaped characters are swapped for private-use code points
# while the inline syntax is parsed, then restored.
ESCAPABLE = "\\`*_{}[]()#+-.!|>~"
PROTECT = {c: chr(0xE000 + i) for i, c in enumerate(ESCAPABLE)}
RESTORE = {v: k for k, v in PROTECT.items()}
def protect(s): return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", lambda m: PROTECT[m.group(1)], s)
def restore(s): return "".join(RESTORE.get(ch, ch) for ch in s)

def fallback(header):
    w=[60 if restore(h).strip().lower() in NARROW else None for h in header]
    rest=TOTAL-sum(x for x in w if x); k=sum(1 for x in w if x is None) or 1
    w=[x if x else rest//k for x in w]; w[-1]+=TOTAL-sum(w); return w

INLINE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|\[([^\]]+)\]\(([^)\s]+)\)|`([^`]+)`|~~(.+?)~~"
                    r"|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])")
def inline(text, base=None):
    """**bold**, __bold__, *italic*, _italic_, `code`, ~~strike~~, [link](url). Expects protect()ed text."""
    base = base or {}
    ops=[]; pos=0
    def add(s, extra=None):
        if s: ops.append({"insert":restore(s), **({"attributes":{**base, **(extra or {})}} if (base or extra) else {})})
    for m in INLINE.finditer(text):
        add(text[pos:m.start()])
        b, b2, lt, lu, code, strike, it, it2 = m.groups()
        if b is not None or b2 is not None: ops += inline(b if b is not None else b2, {**base, "bold": True})
        elif lt is not None: ops += inline(lt, {**base, "link": restore(lu)})
        elif code is not None: add(code, {"code": True})
        elif strike is not None: ops += inline(strike, {**base, "strike": True})
        else: ops += inline(it if it is not None else it2, {**base, "italic": True})
        pos=m.end()
    add(text[pos:])
    for o in ops:
        if "attributes" in o and not o["attributes"]: del o["attributes"]
    return ops
def unesc(s): return s.replace("&lt;","<").replace("&gt;",">").replace("&amp;","&")
SCENARIO = re.compile(r'^\s*(?:\*\*)?\s*(Scenario\s+\d+[^*]*?)\s*(?:\*\*)?\s*$', re.I)
def cell_ops(text):
    ops=[]
    for part in re.split(r"<br\s*/?>", unesc(text)):
        m=SCENARIO.match(part)
        if m:   # always bold the scenario title line, whether or not the spec had **...**
            ops.append({"insert":restore(m.group(1).strip()),"attributes":{"bold":True}})
        else:
            ops+=inline(part)
        ops.append({"insert":"\n"})
    return ops
def bold(ops): return [dict(o,attributes={**o.get("attributes",{}),"bold":True}) if o["insert"]!="\n" else o for o in ops]
def split_row(line):
    """Cells of a pipe-table row. Expects protect()ed text, so an escaped \\| stays inside its cell."""
    s=line.strip()
    if s.startswith("|"): s=s[1:]
    if s.endswith("|"): s=s[:-1]
    return [c.strip() for c in s.split("|")]
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(?:\[([ xX])\]\s+)?(.*)$")
ORDERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
def md_to_delta(text):
    src=[protect(l) for l in text.replace("\r\n","\n").split("\n")]
    ops=[]; t=[0]
    def add_table(rows):
        # ClickUp's markdown export does not escape a "|" inside a cell, so a row read back can have more cells than
        # the header: join the extra ones into the last column (the long text column: Description, Criteria...)
        # instead of adding columns or dropping text.
        n0=len(rows[0])
        rows=[r if len(r)<=n0 else r[:n0-1]+[" | ".join(r[n0-1:])] for r in rows]
        t[0]+=1; n=max(len(r) for r in rows); head=[restore(c) for c in rows[0]]; kv = head[0]=="User Story Name"
        key=("User Story Name",) if kv else tuple(head)
        widths=PRESETS.get(key) or fallback(rows[0])
        if len(widths)!=n: widths=fallback(rows[0] + [""] * (n - len(rows[0])))
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
    def line_end(attrs=None): ops.append({"insert":"\n", **({"attributes":attrs} if attrs else {})})
    indents=[]          # indent widths of the current list, outermost first: 2-space and 4-space nesting both work
    def list_level(ind):
        w=len(ind.replace("\t","    "))
        while indents and indents[-1]>w: indents.pop()
        if not indents or indents[-1]<w: indents.append(w)
        return min(len(indents)-1, 4)
    i=0; first=True
    while i<len(src):
        line=src[i]
        if line.lstrip().startswith("|"):
            rows=[]
            while i<len(src) and src[i].lstrip().startswith("|"):
                r=split_row(src[i])
                if not all(re.fullmatch(r"-+",c.replace(" ","").replace(":","")) for c in r): rows.append(r)
                i+=1
            if rows: add_table(rows)
            first=False; continue
        h=HEADING.match(line)
        if h and first and len(h.group(1))==1: i+=1; first=False; continue   # title line = page/task name
        if line.strip(): first=False
        if line.strip() and not (BULLET.match(line) or ORDERED.match(line)): indents.clear()
        if h:
            hl=min(len(h.group(1)),3); txt=h.group(2).strip()
            if txt:
                txt=re.sub(r"^\*\*(.*)\*\*$", r"\1", txt)        # "# **Heading**": the heading is bold anyway
                ops+=bold(inline(txt)); line_end({"header":hl})
        elif RULE.match(line): pass
        elif BULLET.match(line):
            ind, box, txt = BULLET.match(line).groups()
            a={"list":"bullet" if box is None else ("checked" if box.lower()=="x" else "unchecked")}
            lv=list_level(ind)
            if lv: a["indent"]=lv
            ops+=inline(unesc(txt)); line_end(a); i+=1; continue
        elif ORDERED.match(line):
            ind, txt = ORDERED.match(line).groups()
            a={"list":"ordered"}
            lv=list_level(ind)
            if lv: a["indent"]=lv
            ops+=inline(unesc(txt)); line_end(a); i+=1; continue
        elif line.lstrip().startswith(">"):
            ops+=inline(unesc(line.lstrip()[1:].lstrip())); line_end({"blockquote":True})
        elif line.strip():
            ops+=inline(unesc(line)); line_end()
        i+=1
    return {"ops":ops}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")      # Windows consoles/pipes default to cp1252
    print(json.dumps(md_to_delta(open(sys.argv[1], encoding="utf-8").read()), ensure_ascii=False))
