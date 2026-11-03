# Quill delta (task format) -> what the ClickUp DOC editor accepts on paste.
# Tables become <span class="ql-table-embed" data-table-embed-value="BASE64(json)">, exactly what
# ClickUp itself puts on the clipboard when you copy a task description.
#   python3 -I delta2doc.py delta.json --page "Title" > copy_to_doc.html   (page with a Copy button)
#   python3 -I delta2doc.py delta.json --fragment > doc.html              (raw clipboard HTML)
import base64, html, json, sys

def inline(text, a):
    t = html.escape(text, quote=False)
    if a.get("code"): t = f"<code>{t}</code>"
    if a.get("link"): t = f'<a href="{html.escape(a["link"])}">{t}</a>'
    if a.get("bold"): t = f"<strong>{t}</strong>"
    if a.get("italic"): t = f"<em>{t}</em>"
    if a.get("strike"): t = f"<s>{t}</s>"
    return t

# A Doc's text column is 720px. A table wider than that gets class ql-table-embed-wide and
# sticks out past the headings (and scrolls on small windows), so Doc tables total 720, not 840.
DOC_TOTAL = 720
DOC_PRESETS = {
 ("User Story Name",): [160, 560],
 ("Step","Description"): [80, 640],
 ("No.","Acceptance Criteria"): [60, 660],
 ("No.","Field name","Field Type","Required?","Description"): [60, 140, 110, 110, 300],
 ("Code","Type","Message","Shown when"): [70, 100, 310, 240],
 ("Depends On","Reason"): [240, 480],
 ("No.","Question","Related"): [60, 510, 150],
}

def fit_doc(te):
    """Return a copy of a table-embed with column widths summing to DOC_TOTAL."""
    te = json.loads(json.dumps(te)); cols = te["columns"]; n = len(cols)
    head = ["".join(o["insert"] for o in te["cells"].get(f"1:{c}", {"content": []})["content"]
                    if isinstance(o["insert"], str)).strip() for c in range(1, n + 1)]
    key = ("User Story Name",) if head and head[0] == "User Story Name" else tuple(head)
    w = DOC_PRESETS.get(key)
    if not w or len(w) != n:            # unknown table: scale the current widths proportionally
        cur = [int(c.get("attributes", {}).get("width", 238)) for c in cols]
        w = [max(50, round(x * DOC_TOTAL / sum(cur))) for x in cur]
        w[w.index(max(w))] += DOC_TOTAL - sum(w)
    for c, x in zip(cols, w): c.setdefault("attributes", {})["width"] = str(x)
    return te

LIST_KINDS = ("bullet", "ordered", "checked", "unchecked")

def convert(ops):
    # Lists are written the way ClickUp's editor (Quill 2) stores them: one <ol> whose <li data-list="..."> carry the
    # kind (bullet / ordered / checked / unchecked), nesting as class ql-indent-N. <ul data-checked> (Quill 1)
    # pastes as plain bullets.
    out, line, in_list = [], [], False
    def close_list():
        nonlocal in_list
        if in_list: out.append("</ol>"); in_list = False
    for op in ops:
        ins = op["insert"]
        if isinstance(ins, dict):
            if "table-embed" in ins:
                close_list()
                b64 = base64.b64encode(json.dumps(fit_doc(ins["table-embed"]), ensure_ascii=False,
                                                  separators=(",", ":")).encode()).decode()
                out.append(f'<span class="ql-table-embed" data-table-embed-value="{b64}"></span>')
            continue
        parts = ins.split("\n")
        for i, part in enumerate(parts):
            if part: line.append(inline(part, op.get("attributes", {})))
            if i < len(parts) - 1:   # newline closes the line; a lone "\n" op carries block attrs
                a = op.get("attributes", {}) if ins == "\n" else {}
                body = "".join(line) or "<br>"
                h, kind = a.get("header"), a.get("list")
                if kind in LIST_KINDS:
                    if not in_list: out.append("<ol>"); in_list = True
                    ind = f' class="ql-indent-{a["indent"]}"' if a.get("indent") else ""
                    out.append(f'<li data-list="{kind}"{ind}>{body}</li>')
                else:
                    close_list()
                    if h: out.append(f"<h{h}>{body}</h{h}>")
                    elif a.get("blockquote"): out.append(f"<blockquote>{body}</blockquote>")
                    else: out.append(f"<p>{body}</p>")
                line = []
    close_list()
    if line: out.append(f"<p>{''.join(line)}</p>")
    return "".join(out)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Copy to ClickUp Doc</title>
<style>body{font:15px -apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#222}
button{font-size:18px;padding:14px 28px;border:0;border-radius:8px;background:#7b68ee;color:#fff;cursor:pointer}
#ok{color:#1a7f37;font-weight:600;margin-left:12px} ol{line-height:1.8}</style></head><body>
<h2>__TITLE__</h2>
<p><button id="b">Copy for ClickUp Doc</button><span id="ok"></span></p>
<ol><li>Click the Copy button above.</li><li>Open the ClickUp Doc page and click in the body.</li>
<li>Replace the page: <b>Ctrl/Cmd+A</b> then <b>Ctrl/Cmd+V</b>. Insert at the cursor: just <b>Ctrl/Cmd+V</b>.</li></ol>
<script>
const HTML = __HTML__;
document.getElementById('b').onclick = () => {
  const h = e => { e.clipboardData.setData('text/html', HTML); e.clipboardData.setData('text/plain', ' '); e.preventDefault(); };
  document.addEventListener('copy', h, {once: true});
  const ok = document.execCommand('copy');
  document.getElementById('ok').textContent = ok ? 'Copied - now paste in the Doc' : 'Copy failed';
};
</script></body></html>"""

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")      # Windows consoles/pipes default to cp1252
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    frag = convert(d["ops"] if isinstance(d, dict) else d)
    if "--page" in sys.argv:
        title = sys.argv[sys.argv.index("--page") + 1] if len(sys.argv) > sys.argv.index("--page") + 1 else "ClickUp Doc"
        print(PAGE.replace("__TITLE__", html.escape(title)).replace("__HTML__", json.dumps(frag).replace("</", "<\\/")))
    else:
        print(frag)
