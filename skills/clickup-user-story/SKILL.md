---
name: "clickup-user-story"
description: "Turn a BA user-story spec into a clean draft and publish it to ClickUp in the team table style (840px tables with set column widths, green header rows, bold scenario titles) - as a TASK, or on a ClickUp DOC page; also fixes EXISTING tickets whose tables are half width. Use when the user says \"make-ticket\", \"make a ticket\", \"tạo ticket\", \"draft ticket\", \"user story\", \"fix table\", \"sửa table ticket\", \"table trong doc\", \"đưa story vào doc\", gives a ClickUp Doc link (/v/dc/ or /docs/), or asks to push a user story (M-xxx-x / W-xxx) to ClickUp."
---

# clickup-user-story


**Mode A (Steps 0–3, default):** turn a user-story spec (usually an exported markdown file like `M-012-1_ Configure organisation plan.md`) into:
1. a cleaned-up **draft ticket (.md)** in the team's table format, and
2. a **ClickUp task with full-width tables, green header rows and bold scenario titles** (via Quill delta, NOT markdown).

**Mode B (fix existing ticket):** see the "Mode B" section — repairs a ticket that already exists in ClickUp with half-width tables.

**Mode C (target is a ClickUp Doc page, not a task):** see the "Mode C" section — the user gives a Doc page link and the story is written straight into that page with the `clickup_doc_write` tool (only on MCP `reclickup-mcp`). No copy/paste, no staging task.

**ClickUp tools come from the `reclickup-mcp` MCP server** (runs locally on the user's machine; https://github.com/haonguyenstech/reclickup-mcp). It is a proxy of the official ClickUp MCP (`mcp.clickup.com`, via `mcp-remote`, OAuth token cached in `~/.mcp-auth`), so every official tool keeps its usual name (`clickup_get_task`, `clickup_execute_operator`, `clickup_create_document_page`, …), **plus `clickup_doc_write`** and **`clickup_relogin`**, which only `reclickup-mcp` has: `clickup_doc_write` writes the formatted story into a Doc page through reclickup's own **headless** Edge (no window, profile `~/.reclickup/headless-profile`, stops itself after 10 min idle); `clickup_relogin` refreshes that browser's ClickUp session. In the tool list they appear as `mcp__reclickup-mcp__<name>`. If both `reclickup-mcp` and the official `clickup` server are connected, either works for the official tools; `clickup_doc_write` exists only on `reclickup-mcp`. **Never tell the user you have no tool to create or update a task.** If only `clickup_doc_write` / `clickup_relogin` are listed (the official tools have not arrived yet: Claude Desktop reads the tool list once at startup), tell the user, in their language, to quit and reopen Claude Desktop (tray icon → Quit) and approve the ClickUp page if one opens, then retry. Do not suggest pasting the content by hand instead. If `reclickup-mcp` is missing, tell the user (Vietnamese) to restart Claude Desktop; if its official tools fail with an auth error, the OAuth token expired: re-run `npx -y mcp-remote@0.15.1 https://mcp.clickup.com/mcp` once in a terminal and approve in the browser.

Reply in the user's language. Ticket content itself stays in English.

---

## Step 0 — Defaults (don't ask unless missing)

| Item | Default |
| --- | --- |
| Workspace | The user's ClickUp workspace id. If unknown, read it from a link the user gave (`app.clickup.com/<workspace_id>/…`) or from `clickup_get_workspace_hierarchy`, and ask only if there are several. Always pass `workspace_id` (accounts with several workspaces error out otherwise). |
| List | The list the user names or links (`…/li/<list_id>`); if none was given, ask once which list to use. |
| Assignee | none |
| Task name | `M-XXX-X: <Story title>` (from the file's `# ` title) |
| Status field in ticket table | `Draft` |
| Table style | total width 840px per table, header row (or key column of the first key-value table) bold + green background; "Scenario N: ..." title lines in AC cells bold |

If the user names another list/board (or pastes a ClickUp URL like `.../v/b/li/<list_id>`), use that list id instead. Don't use AskUserQuestion if the user has already given enough info — the user dislikes unnecessary questions.

If the source file contains several user stories (e.g. an HTML export with many `<h1>` stories and yellow "rev" rows), ask in one short message which story to draft, or whether to make one change-summary ticket, before drafting.

## Step 1 — Read the spec & draft the ticket

Read the source file. Keep **exactly this section order and table format**:

1. Header table (2 cols): `User Story Name | User Story | Status | Created By | Figma Design | Diagrams (If any)` — first column is the key. Figma link as `[Phase name](url)`.
2. `# **Main Flow/User Journey**` → `| Step | Description |`
3. `# **Acceptance Criteria**` → `| No. | Acceptance Criteria |`. Each cell:
   `**Scenario N: Title**<br>• Given ...<br>• When ...<br>• Then ...<br>     And ...<br>     And ...`
   The scenario title line must be **bold**. Write it with `**...**` in the draft; the converter also auto-bolds any cell line starting with `Scenario <number>` (even if the source spec forgot the `**`), so it is bold in ClickUp either way.
4. `# **Screen Description**` → for each screen/popup a bold line `**Screen: ...**` / `**Popup: ...**` then `| No. | Field name | Field Type | Required? | Description |` (description bullets `• ` separated by `<br>`). Numbering continues across screens.
5. `# **Messages**` (add if the spec has message codes) → `| Code | Type | Message | Shown when |`. In ACs refer to messages by code only (e.g. "shows M286").
6. `# **Dependencies**` → `| Depends On | Reason |`
7. `# **Open Questions**` (add if any issues found) → `| No. | Question | Related |`

Escape `<n>` style placeholders as `&lt;n&gt;` in the markdown.

### Quality pass (always do it, and report what changed)
Check the spec for and fix/flag:
- Contradictions between ACs (e.g. "optional, may be left empty" vs a "required" error message) → resolve toward the stricter/validated rule, update `Required?` column (e.g. `Conditional`), and add an Open Question if it affects other scenarios (e.g. migration of legacy data).
- Duplicated sentences, typos ("ticked empty" → "ticked"), missing Given/When/Then bullets, inconsistent indentation, scenario titles not bolded.
- Fields whose Required? / validation in Screen Description don't match the ACs.
- Edge cases not covered (both values changed at once, switching from unlimited to a number, placeholders like `<n>`, toast type/placement) → Open Questions.

Save the draft to the outputs folder as `M-XXX-X_<Title_With_Underscores>_DRAFT.md`, present it, and summarize fixes + open questions (short, in the user's language).

If the user only asked for a draft, stop here and offer to create it in ClickUp.

## Step 2 — Create in ClickUp with full-width, green-header tables

**Why not markdown:** `clickup_create_task(markdown_description=...)` gives every table column a fixed width of 238px → tables render at ~half width, and no header color; bold inside table cells is also unreliable. Markdown cannot specify widths/colors, and `clickup_update_task` / `task.update_many` cannot set a delta description.

**What works:** ClickUp stores descriptions as Quill delta. `clickup_execute_operator` → `task.create_many` accepts `description` as a delta object `{ "ops": [...] }`. In a `table-embed`:
- column width: `columns[i].attributes.width` = `"<px>"` (string). Keep each table's total ≈ **840px** (880px overflows the description pane → horizontal scrollbar).
- cell background: `cells["r:c"].attributes["cell-bg-color"]` = palette name — `"green"` (the light green header color the user wants). Other names follow the ClickUp swatches: red, orange, yellow, blue, purple, pink, gray.
- bold text: op `attributes.bold = true` (used for headers and "Scenario N: ..." titles); link: `attributes.link`; H1: `{"insert":"\n","attributes":{"header":1}}` after the heading text.
- Narrow headers wrap ("No." needs ≥60px, "Field Type" ≥120px, "Required?" ≥110px).

### 2a. Convert the draft markdown → delta
Write this script to `/tmp/conv/md2delta.py` (keep scripts out of the outputs/uploads dirs) and run:
`python3 -I /tmp/conv/md2delta.py "<draft.md path in bash>" > /tmp/conv/delta.json`

```python
import json, re, sys
src = open(sys.argv[1]).read().splitlines()
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
print(json.dumps({"ops":ops},ensure_ascii=False,separators=(",",":")))
```

Sanity check before creating — print, per table, the width sum (must be 840) and which cells have `cell-bg-color`; also confirm every "Scenario N" op has `bold: true`:
```
python3 -c "import json;d=json.load(open('/tmp/conv/delta.json'))
for o in d['ops']:
  if isinstance(o['insert'],dict):
    te=o['insert']['table-embed']; print(sum(int(c['attributes']['width']) for c in te['columns']), [k for k,v in te['cells'].items() if v['attributes'].get('cell-bg-color')])
    print('scenarios not bold:', [x['insert'] for v in te['cells'].values() for x in v['content'] if x['insert'].lstrip().lower().startswith('scenario') and not x.get('attributes',{}).get('bold')])"
```

### 2b. Create the task
`cat /tmp/conv/delta.json`, then call:

```
clickup_execute_operator(
  workspace_id="<workspace_id>", model="task", operator="create_many",
  parameters={"list_id": <list_id>},
  body={"tasks":[{"name":"M-XXX-X: Title","description": <the delta object>}]},
  query="tasks[*].{id: id, name: name}")
```
(`description` must be the JSON object, not a string. Optional fields: `assignee_ids` (ints), `priority` 1-4, `tags` [{name}], `status_label`.)

### 2c. Verify
`clickup_execute_operator(model="task", operator="get_many", body={"ids":[id]}, query="tasks[0].data.content")` → confirm column widths, `cell-bg-color` on header cells, bold scenario titles, and complete content. (`clickup_get_task`'s markdown view hides bold-in-cells, colors and leading spaces — display only; trust the delta.)

### 2d. Replacing an existing ticket
Use **Mode B** below — it works from the ticket's own delta, no spec file needed. Always archive (not delete) the old task; only delete throwaway test tasks you created.

### Learning new styles
If the user styles something by hand in ClickUp (color, width, etc.) and wants it in the skill, read that task's raw delta with `task.get_many` → `tasks[0].data.content` and copy the attribute names/values exactly.

## Mode B — Fix an EXISTING ticket with broken tables

Use when the user gives an existing ClickUp ticket (link/ID) whose tables are half width (all columns `238`), have no green header, or unbolded scenario titles. No spec file is needed: the source is the ticket's own delta, so manual edits made in ClickUp are kept. (If the link is a Doc — `/docs/` or `/v/dc/` — use Mode C instead.)

**Always tell the user first (one line):** the API cannot rewrite an existing description as delta, so the fix creates a **new** task and archives the old one. Comments, activity history, attachments, subtasks, relationships and time entries stay on the old task and do not move; the link/ID changes. For tickets with lots of discussion, suggest the manual alternative instead: select a cell → table toolbar → **"fit container"** (true 100% width, keeps everything).

1. **Read the old task:** `clickup_execute_operator(model="task", operator="get_many", body={"ids":[old_id]}, query="tasks[0].data.{name: name, content: content, priority: priority, status: status.status, tags: tags[*].name, users: users, list: subcategory}")`. Assignees are the `users` entries with `type: "assignee"`; ignore owner/creator/watcher.
2. **Save `content`** (a JSON string) to `/tmp/fix/old.json` with a quoted heredoc (`<<'EOF'`).
3. **Run the fixer** (write it to `/tmp/fix/fix_delta.py`): `python3 -I /tmp/fix/fix_delta.py /tmp/fix/old.json > /tmp/fix/new.json`. It prints old → new widths per table on stderr. It only touches tables: column widths (same presets/fallback as Mode A, total 840), header row (or key column of the "User Story Name" table) bold + `cell-bg-color: green`, and bolds any cell line starting with `Scenario <n>`. Text, links, row/column ids, other cell colors and everything outside tables are kept as is. It also handles ClickUp's merged ops (several lines in one insert).

```python
# Repair an existing ClickUp description delta: column widths (total 840), green header, bold headers + "Scenario N" titles.
import json, re, sys, copy
d = json.load(open(sys.argv[1]))
if isinstance(d, str): d = json.loads(d)          # accept the raw `content` string too
TOTAL = 840
HEADER_BG = "green"
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
SCEN = re.compile(r'^\s*Scenario\s+\d+', re.I)
def fallback(header):
    w=[60 if h.strip().lower() in NARROW else None for h in header]
    rest=TOTAL-sum(x for x in w if x); k=sum(1 for x in w if x is None) or 1
    w=[x if x else rest//k for x in w]; w[-1]+=TOTAL-sum(w); return w
def lines(ops):
    """split cell ops into lines of (insert, attrs) segments; newline ops' own attrs kept"""
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
```

4. **Create the replacement** with `task.create_many` in the old task's list: same `name`, `priority` (number), `status_label` (old status), `assignee_ids`, `tags` [{name}], and `description` = the object in `new.json`.
5. **Verify** the new task's delta (widths sum 840, green headers, bold scenarios, content complete — compare cell count with the old one).
6. **Comment on the old task** with a link to the new one (`clickup_create_comment`), then **archive** it (`task.archive`). Never delete it.
7. **Report (in the user's language):** new link, what was fixed (widths per table), and what did NOT move (comments/history/attachments/subtasks).

## Mode C — Target is a ClickUp Doc page (not a task)

Use when the user wants the story in a ClickUp **Doc** (URL contains `/docs/` or `/v/dc/`), or says the Doc version has half-width / uncolored tables.

**Facts (tested 2026-11-03):**
- The Docs API (`clickup_create_document_page` / `clickup_update_document_page`) takes markdown or plain text only → tables come out equal-width (~half page) with no cell color. No operator writes delta to a Doc. Raw HTML (`<table>`, `style`, `data-colwidth`) shows as literal text — never use it.
- **The Doc editor accepts a paste whose `text/html` carries each table as `<span class="ql-table-embed" data-table-embed-value="BASE64(UTF-8 JSON of the table-embed object)">`.** That is exactly what ClickUp puts on the clipboard when you copy a task description. Column widths, `cell-bg-color`, bold, links, H1 and Vietnamese text all survive, and the result is saved server-side (survives reload, readable through the API).
- So the delta from Mode A goes straight to the Doc; **do not create `[DOC STAGING]` tasks any more**.
- **A Doc's text column is 720px** (headings are 720 wide). A table wider than 720 gets class `ql-table-embed-wide` and sticks out to the left of the headings (and scrolls on small windows). So Doc tables total **720**, not 840: `delta2doc.py` re-widths every table with its own `DOC_PRESETS` (unknown tables are scaled proportionally). Keep the task delta at 840; the converter does the Doc fit. Verified 2026-11-03: table left/right edges == H1 edges.

**Workflow:**
1. Build the draft exactly as in Mode A Step 1 (quality pass included) and save `M-XXX-X_<Title>_DRAFT.md` in outputs.
2. **Target page.** If the user gave a Doc page URL (`app.clickup.com/<ws>/v/dc/<docId>/<pageId>`), use it — even an empty "Untitled" page is fine. Otherwise create the page with `clickup_create_document_page` (name = `M-XXX-X: Title`, content = `placeholder`) and build its URL from the returned ids.
3. **Write it — default path:** call **`clickup_doc_write`** (`mcp__reclickup-mcp__clickup_doc_write` — the `reclickup-mcp` server, runs on the user's machine; not part of the official ClickUp MCP) with:
   - `page_url` = the Doc page link,
   - `markdown` = the full text of the draft .md (read the file and pass its content; the first `# Title` line becomes the page title if the page is untitled),
   - `mode` = `"replace"` (default, overwrites the page body) or `"append"` if the user wants it added under existing content.
   It takes ~25-30 s: it opens the page in reclickup's headless Edge (nothing appears on screen), pastes the formatted content (column widths fitted to the Doc's 720px, green header cells, bold), reloads and returns per-table widths / green cell counts / alignment with the H1. **Report that result**; every line should read `sum 720`, green cells > 0, `aligned True`.
   - Error `NOT_LOGGED_IN`: call **`clickup_relogin`** (no arguments), then retry `clickup_doc_write` once. Before calling it, tell the user (in their language): on macOS a Keychain prompt "Microsoft Edge Safe Storage" may appear — click **Allow**; on Windows an Edge window opens at the ClickUp login — sign in once. If relogin itself fails on macOS ("no clickup.com session"), the user must sign in to ClickUp in their normal Microsoft Edge first.
   - Never pass the markdown to `clickup_update_document_page` as a fallback without asking — that gives half-width, uncolored tables.
4. **Only if `clickup_doc_write` is NOT in the tool list** (MCP not installed / Desktop not restarted), use the converter below:
   a. **Write the converter** to `/tmp/conv/delta2doc.py` (verbatim):

```python
# Quill delta (task format) -> what the ClickUp DOC editor accepts on paste.
# Tables become <span class="ql-table-embed" data-table-embed-value="BASE64(json)">, exactly what
# ClickUp itself puts on the clipboard when you copy a task description.
#   python3 -I delta2doc.py delta.json --page "Title" > copy_to_doc.html   (page with a Copy button)
#   python3 -I delta2doc.py delta.json --fragment > doc.html              (raw clipboard HTML)
import base64, html, json, sys

def inline(text, a):
    t = html.escape(text, quote=False)
    if a.get("link"): t = f'<a href="{html.escape(a["link"])}">{t}</a>'
    if a.get("bold"): t = f"<strong>{t}</strong>"
    if a.get("italic"): t = f"<em>{t}</em>"
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

def convert(ops):
    out, line = [], []
    for op in ops:
        ins = op["insert"]
        if isinstance(ins, dict):
            if "table-embed" in ins:
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
                h, lst = a.get("header"), a.get("list")
                if h: out.append(f"<h{h}>{body}</h{h}>")
                elif lst in ("bullet", "ordered"):
                    tag = "ul" if lst == "bullet" else "ol"
                    out.append(f"<{tag}><li>{body}</li></{tag}>")
                else: out.append(f"<p>{body}</p>")
                line = []
    if line: out.append(f"<p>{''.join(line)}</p>")
    return "".join(out)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Copy to ClickUp Doc</title>
<style>body{font:15px -apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#222}
button{font-size:18px;padding:14px 28px;border:0;border-radius:8px;background:#7b68ee;color:#fff;cursor:pointer}
#ok{color:#1a7f37;font-weight:600;margin-left:12px} ol{line-height:1.8}</style></head><body>
<h2>__TITLE__</h2>
<p><button id="b">Copy for ClickUp Doc</button><span id="ok"></span></p>
<ol><li>Click the Copy button above.</li><li>Open the ClickUp Doc page and click in the body.</li>
<li>Replace the page: <b>Cmd+A</b> then <b>Cmd+V</b>. Insert at the cursor: just <b>Cmd+V</b>.</li></ol>
<script>
const HTML = __HTML__;
document.getElementById('b').onclick = () => {
  const h = e => { e.clipboardData.setData('text/html', HTML); e.clipboardData.setData('text/plain', ' '); e.preventDefault(); };
  document.addEventListener('copy', h, {once: true});
  const ok = document.execCommand('copy');
  document.getElementById('ok').textContent = ok ? 'Copied - now Cmd+V in the Doc' : 'Copy failed';
};
</script></body></html>"""

if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    frag = convert(d["ops"] if isinstance(d, dict) else d)
    if "--page" in sys.argv:
        title = sys.argv[sys.argv.index("--page") + 1] if len(sys.argv) > sys.argv.index("--page") + 1 else "ClickUp Doc"
        print(PAGE.replace("__TITLE__", html.escape(title)).replace("__HTML__", json.dumps(frag).replace("</", "<\\/")))
    else:
        print(frag)
```

   b. **Deliver** — pick the first that applies:
   - **A browser tool that can run JavaScript in a ClickUp tab where the user is logged in is available** (Claude in Chrome, agent-browser, Playwright): run `python3 -I /tmp/conv/delta2doc.py /tmp/conv/delta.json --fragment > /tmp/conv/doc.html`, open the Doc page, wait until `.ql-editor` exists (a page just created through the API may need a reload), then run this with `HTML` = the contents of `doc.html` as a JS string literal and `APPEND` = `false` to replace the page, `true` to add at the end:

```js
(async () => {
  const html = HTML, append = APPEND;
  const ed = document.querySelector('.cu-dashboard-doc-page_editor-wrapper .ql-editor') || document.querySelector('.ql-editor');
  if (!ed) return 'NO_EDITOR';
  ed.focus();
  const r = document.createRange();
  if (append) { const b = ed.querySelectorAll(':scope > *'); r.selectNodeContents(b[b.length - 1] || ed); r.collapse(false); }
  else r.selectNodeContents(ed);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  await new Promise(res => setTimeout(res, 500));          // let Quill pick up the selection
  const dt = new DataTransfer(); dt.setData('text/html', html); dt.setData('text/plain', ' ');
  const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  ed.dispatchEvent(ev);
  await new Promise(res => setTimeout(res, 2000));
  return ev.defaultPrevented ? 'PASTED tables=' + document.querySelectorAll('table').length : 'NOT_HANDLED';
})()
```

     Wait ~5 s, reload, and verify in the page: `[...document.querySelectorAll('table')].map(t => [...t.querySelectorAll('col')].map(c => c.getAttribute('width')).join('/') + ' green=' + t.querySelectorAll('[data-cell-bg-color]').length)` must show widths summing to 720 and green header cells for every table; the table's left edge should equal the H1's (`getBoundingClientRect().left`).
   - **Otherwise (normal Cowork session — there is no browser tool):** run `python3 -I /tmp/conv/delta2doc.py /tmp/conv/delta.json --page "M-XXX-X: Title" > "<outputs>/M-XXX-X_copy_to_doc.html"` and present that file. Tell the user (short, in their language): open the file → click **Copy for ClickUp Doc** → open the Doc page (link) → click in the body → **Cmd+A, Cmd+V** to replace the page (or just Cmd+V to insert at the cursor). The button uses a `copy` event + `execCommand('copy')`, so it works when the file is opened in any browser.
5. **Check** (fallback path only — `clickup_doc_write` already verifies) after the paste or after the user says done: `clickup_get_document_pages` for that page → the markdown must contain every section and the same number of tables as the delta, and no leftover `placeholder`. The API markdown never shows widths/colors; if the user reports a formatting problem, ask for a screenshot.
6. Writing tables into a Doc through the markdown API is only for when the user explicitly asks for a quick unformatted version.

## Step 3 — Report (in the user's language, concise)
- Link: `[M-XXX-X: Title](https://app.clickup.com/t/<id>)` for a task, or the Doc page URL for Mode C (inline markdown link, never a bare URL).
- List it was created in, assignee none.
- Fixes made to the spec + Open Questions to send to the BA.
- Tip: on a narrower screen, if a table shows a horizontal scrollbar, click the table's "fit container" icon in ClickUp to auto-fit.

## Gotchas
- Always pass `workspace_id` to ClickUp tools (multi-workspace → error otherwise).
- `help.clickup.com` / `feedback.clickup.com` are blocked for fetch; don't retry.
- Docs ≠ tasks: the delta API only works on tasks; Docs get the same delta through a paste (Mode C). There is no API to delete a Doc or a Doc page, so don't create throwaway Docs/pages for testing — reuse a test page.
- Can't see ClickUp UI directly; if visual confirmation is needed, ask the user for a screenshot rather than a multiple-choice question.

