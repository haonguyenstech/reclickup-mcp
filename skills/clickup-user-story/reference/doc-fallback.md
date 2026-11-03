# Doc fallback: only when `clickup_doc_write` is NOT available

Use this only if the `reclickup-mcp` tool `clickup_doc_write` is missing from the tool list. First tell the user that
installing reclickup-mcp makes this automatic.

The Doc editor accepts a paste whose `text/html` carries each table as
`<span class="ql-table-embed" data-table-embed-value="BASE64(UTF-8 JSON of the table-embed)">` (what ClickUp itself
puts on the clipboard when you copy a task description). `scripts/delta2doc.py` builds that HTML from the Mode A delta
and refits every table to the Doc's 720px column.

1. `mkdir -p /tmp/conv && python3 -I "SKILL_DIR/scripts/md2delta.py" "<draft.md>" > /tmp/conv/delta.json`
2. Deliver, first that applies:
   - **A browser tool can run JavaScript in a ClickUp tab where the user is signed in** (agent-browser, Playwright,
     Claude in Chrome): `python3 -I "SKILL_DIR/scripts/delta2doc.py" /tmp/conv/delta.json --fragment > /tmp/conv/doc.html`,
     open the Doc page, wait for `.ql-editor` (a page just created through the API may need a reload) plus ~2 s, click
     into the body, then run this with `HTML` = the contents of `doc.html` as a JS string literal and `APPEND` = `false`
     to replace the page, `true` to add at the end:

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
       await new Promise(res => setTimeout(res, 500));
       const dt = new DataTransfer(); dt.setData('text/html', html); dt.setData('text/plain', ' ');
       const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
       ed.dispatchEvent(ev);
       await new Promise(res => setTimeout(res, 2000));
       return ev.defaultPrevented ? 'PASTED tables=' + document.querySelectorAll('table').length : 'NOT_HANDLED';
     })()
     ```

     Wait ~6 s, reload, and check: `[...document.querySelectorAll('table')].map(t => [...t.querySelectorAll('col')].map(c => c.getAttribute('width')).join('/') + ' green=' + t.querySelectorAll('[data-cell-bg-color]').length)`
     must show widths summing to 720 and green cells for every table.
   - **Otherwise (no browser tool, e.g. a Cowork session):**
     `python3 -I "SKILL_DIR/scripts/delta2doc.py" /tmp/conv/delta.json --page "M-XXX-X: Title" > "<outputs>/M-XXX-X_copy_to_doc.html"`
     and present that file. Tell the user: open it → **Copy for ClickUp Doc** → open the Doc page → click in the body →
     Ctrl/Cmd+A, Ctrl/Cmd+V to replace the page (or just paste to insert at the cursor).
3. Check afterwards with `clickup_get_document_pages`: every section present, same number of tables as the delta, no
   leftover `placeholder`. The API markdown never shows widths or colours; for formatting problems ask for a screenshot.
