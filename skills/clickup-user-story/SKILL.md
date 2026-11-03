---
name: "clickup-user-story"
description: "Turn a BA user-story spec into a clean draft and publish it to ClickUp in the team table style (840px tables with set column widths, green header rows, bold scenario titles) - as a TASK, or on a ClickUp DOC page; edits existing Doc pages; also fixes EXISTING tickets whose tables are half width. Use when the user says \"make-ticket\", \"make a ticket\", \"tạo ticket\", \"draft ticket\", \"user story\", \"fix table\", \"sửa table ticket\", \"table trong doc\", \"đưa story vào doc\", gives a ClickUp Doc link (/v/dc/ or /docs/), or asks to push a user story (M-xxx-x / W-xxx) to ClickUp."
---

# clickup-user-story

- **Mode A (default, Steps 0–3):** spec (e.g. `M-012-1_ Configure organisation plan.md`) → cleaned **draft ticket .md** → **ClickUp task** with full-width tables, green header rows, bold scenario titles (Quill delta, NOT markdown).
- **Mode B:** fix an existing task whose tables are half width.
- **Mode C:** the target is a ClickUp **Doc page**: write the story into it with `clickup_doc_write`. **Mode C2:** edit a Doc page that already has content.

`SKILL_DIR` below = the folder this SKILL.md is in (the skill's base directory). Its `scripts/` hold the converters; run them, don't retype them.

Reply in the user's language. Ticket content itself stays in English.

## Tools: reclickup-mcp

ClickUp tools come from the **`reclickup-mcp`** MCP server (local, on the user's machine; https://github.com/haonguyenstech/reclickup-mcp). It proxies the official ClickUp MCP (`mcp.clickup.com`), so every official tool keeps its name (`clickup_get_task`, `clickup_execute_operator`, `clickup_get_document_pages`, …; listed as `mcp__reclickup-mcp__<name>`), plus two of its own:
- `clickup_doc_write`: writes formatted markdown into a Doc page through reclickup's own headless Edge (nothing on screen).
- `clickup_relogin`: refreshes that browser's ClickUp session.

**Never tell the user you have no tool to create, update or read a task or Doc, and never ask them to paste content by hand.** If only `clickup_doc_write` / `clickup_relogin` are listed, the official tools have not connected yet: tell the user to quit and reopen Claude Desktop (tray icon → Quit) and approve the ClickUp page if one opens. If `reclickup-mcp` is missing entirely, tell them to add it (README of the repo) and restart Claude Desktop.

**Errors that mean "retry", not "broken"** (every reclickup call answers within ~50 s):

| Error | Meaning | Do |
| --- | --- | --- |
| `NOT_READY` | Official ClickUp MCP still connecting; nothing was sent | If the text says it waits for the sign-in: tell the user to pick the workspace and click **Connect Workspace** on the ClickUp page in the browser. Call the same tool again (up to 3 times, a few seconds apart). |
| `STALE_CONNECTION` | The connection had stopped answering; reclickup restarted it | Call again right away. For a write, first check with a read whether it already happened. |
| `BUSY` | Another Doc write / sign-in is using reclickup's browser | Wait ~10 s, call again. |
| `NOT_LOGGED_IN` (`clickup_doc_write`) | reclickup's browser has no ClickUp session | Call `clickup_relogin`, then retry once. Tell the user first: macOS may show a Keychain prompt "Microsoft Edge Safe Storage" → **Allow**; on Windows an Edge window opens at the ClickUp login → sign in once. |
| `LOGIN_PENDING` (`clickup_relogin`, Windows) | The sign-in window is open, not signed in yet | Ask the user to sign in there and say when done, then call `clickup_relogin` again. |
| `TIMEOUT` (`clickup_doc_write`) | The page did not load in time; nothing was pasted | Check the link, call again once. |
| client says the device "did not respond within 60s" | The call may or may not have run | Reads (`clickup_get_*`, `clickup_list_*`, `clickup_search`): run once more. Writes: ask the user before retrying. |

## Step 0 — Defaults (don't ask unless missing)

| Item | Default |
| --- | --- |
| Workspace | Read it from a link the user gave (`app.clickup.com/<workspace_id>/…`) or from `clickup_get_workspace_hierarchy`; ask only if there are several. Always pass `workspace_id`. |
| List | The list the user names or links (`…/li/<list_id>`); if none, ask once. |
| Assignee | none |
| Task name | `M-XXX-X: <Story title>` (from the file's `# ` title) |
| Status in the ticket table | `Draft` |
| Table style | 840px per table; header row (or the key column of the `User Story Name` table) bold + green; "Scenario N: …" lines bold |

Don't ask questions the user has already answered. If the source holds several stories (e.g. an HTML export with many `<h1>` and yellow "rev" rows), ask once which story to draft, or whether to make one change-summary ticket.

## Step 1 — Read the spec & draft the ticket

Keep **exactly this section order and table format**:

1. Header table (2 cols): `User Story Name | User Story | Status | Created By | Figma Design | Diagrams (If any)`; first column is the key. Figma link as `[Phase name](url)`.
2. `# **Main Flow/User Journey**` → `| Step | Description |`
3. `# **Acceptance Criteria**` → `| No. | Acceptance Criteria |`, each cell
   `**Scenario N: Title**<br>• Given ...<br>• When ...<br>• Then ...<br>     And ...<br>     And ...`
   (the converter also bolds any cell line starting with `Scenario <n>`).
4. `# **Screen Description**` → per screen/popup a bold line `**Screen: ...**` / `**Popup: ...**`, then `| No. | Field name | Field Type | Required? | Description |` (description bullets `• ` separated by `<br>`; numbering continues across screens).
5. `# **Messages**` (if the spec has message codes) → `| Code | Type | Message | Shown when |`. ACs refer to messages by code only ("shows M286").
6. `# **Dependencies**` → `| Depends On | Reason |`
7. `# **Open Questions**` (if any) → `| No. | Question | Related |`

Escape `<n>` style placeholders as `&lt;n&gt;`. A literal `|` inside a cell is written `\|`.

**Quality pass (always, and report what changed):** contradictions between ACs (resolve toward the stricter rule, update `Required?`, e.g. `Conditional`, add an Open Question if it affects other scenarios); duplicated sentences, typos, missing Given/When/Then, unbolded scenario titles; `Required?`/validation in Screen Description vs the ACs; uncovered edge cases (both values changed at once, unlimited → number, placeholders, toast type/placement) → Open Questions.

Save `M-XXX-X_<Title_With_Underscores>_DRAFT.md` in the outputs folder, present it, summarize fixes + open questions. If the user only asked for a draft, stop and offer to create it in ClickUp.

## Step 2 — Create the task (Mode A)

Markdown descriptions give every table column 238px (half width) and no header colour, and `update_task` cannot set a delta. ClickUp stores descriptions as Quill delta, and `task.create_many` accepts one: columns `attributes.width` = `"<px>"` (total 840; 880 overflows), cells `attributes["cell-bg-color"]` = `"green"` (palette: red, orange, yellow, blue, purple, pink, gray), text `attributes.bold`, `link`, H1 = `{"insert":"\n","attributes":{"header":1}}`.

1. **Convert:** `mkdir -p /tmp/conv && python3 -I "SKILL_DIR/scripts/md2delta.py" "<draft.md>" > /tmp/conv/delta.json`
2. **Check:** `python3 -I "SKILL_DIR/scripts/check_delta.py" /tmp/conv/delta.json`: every table must say `sum 840`, have green cells, and `scenarios not bold: []`.
3. **Create:** `clickup_execute_operator(workspace_id="<workspace_id>", model="task", operator="create_many", parameters={"list_id": <list_id>}, body={"tasks":[{"name":"M-XXX-X: Title","description": <the delta object from delta.json>}]}, query="tasks[*].{id: id, name: name}")`. `description` is the JSON object, not a string. Optional: `assignee_ids` (ints), `priority` 1-4, `tags` [{name}], `status_label`.
4. **Verify:** `clickup_execute_operator(model="task", operator="get_many", body={"ids":[id]}, query="tasks[0].data.content")` → widths, `cell-bg-color` on header cells, bold scenarios, complete content. (`clickup_get_task`'s markdown hides colours and bold in cells; trust the delta.)

To replace an existing ticket use Mode B. Always archive, never delete (only delete throwaway test tasks you created). To learn a style the user made by hand, read that task's delta (`task.get_many` → `tasks[0].data.content`) and copy the attribute names/values.

## Mode B — Fix an EXISTING task with broken tables

For a task whose tables are half width (all columns `238`), lack the green header, or have unbolded scenario titles. The source is the ticket's own delta, so manual edits are kept. (A Doc link → Mode C / C2.)

**Tell the user first (one line):** the API cannot rewrite a description as delta, so the fix creates a **new** task and archives the old one; comments, history, attachments, subtasks, relationships and time entries stay on the old task, and the link changes. For tickets with a lot of discussion, offer the manual alternative: select a cell → table toolbar → **fit container**.

1. **Read:** `clickup_execute_operator(model="task", operator="get_many", body={"ids":[old_id]}, query="tasks[0].data.{name: name, content: content, priority: priority, status: status.status, tags: tags[*].name, users: users, list: subcategory}")`. Assignees = `users` entries with `type: "assignee"`.
2. Save `content` (a JSON string) to `/tmp/fix/old.json` with a quoted heredoc (`<<'EOF'`).
3. **Fix:** `python3 -I "SKILL_DIR/scripts/fix_delta.py" /tmp/fix/old.json > /tmp/fix/new.json` (prints old → new widths per table on stderr; only tables change: widths, green bold header, bold `Scenario <n>` lines).
4. **Create** the replacement with `task.create_many` in the same list: same `name`, `priority`, `status_label`, `assignee_ids`, `tags`, `description` = the object in `new.json`.
5. **Verify** as in Step 2 (compare the cell count with the old task).
6. **Comment** on the old task with the new link (`clickup_create_comment`), then **archive** it (`task.archive`). Never delete it.
7. **Report:** new link, widths fixed per table, what did NOT move.

## Mode C — Write the story into a ClickUp Doc page

The Docs API takes markdown only (equal-width tables, no colours; raw HTML shows as text). `clickup_doc_write` instead pastes the formatted content into the page in reclickup's headless Edge: tables fitted to the Doc's **720px** text column (edges aligned with the headings), green header cells, bold, links, headings `#`–`###`, lists, checklists.

1. Draft exactly as in Step 1 and save the `_DRAFT.md`.
2. **Target page:** the Doc page URL the user gave (`app.clickup.com/<ws>/v/dc/<docId>/<pageId>`; an empty "Untitled" page is fine). Otherwise create one with `clickup_create_document_page` (name `M-XXX-X: Title`, content `placeholder`) and build its URL from the returned ids.
3. **Write:** `clickup_doc_write(page_url=…, markdown=<the full draft text>, mode="replace")` (`"append"` adds at the end of the page). The first `# Title` line names an untitled page and is not written into the body. It takes ~25 s and returns, per table, widths / green cells / alignment after a reload: report it; every table should read `sum 720`, green > 0, `aligned True`.
4. Never fall back to `clickup_update_document_page` with the tables without asking: that gives half-width, uncolored tables.
5. **Only if `clickup_doc_write` is missing from the tool list** (reclickup-mcp not installed), read `SKILL_DIR/reference/doc-fallback.md` and follow it (copy page / browser paste).

## Mode C2 — Edit a Doc page that already has content

For "add a scenario under Acceptance Criteria", "fix row 3", etc. You CAN read the page.

1. **Read:** from `app.clickup.com/<ws>/v/dc/<docId>/<pageId>` call `clickup_get_document_pages(workspace_id=<ws>, document_id=<docId>, page_ids=[<pageId>], content_format="text/md")`. Markdown = `pages[0].content`, title = `pages[0].name`.
2. **Restore** before editing: put `# <pages[0].name>` as the first line, and write `<br>And …` lines inside a scenario as `<br>     And …` (5 spaces; the export drops the indent). Leave everything else as it came back: the converter removes ClickUp's backslash escapes (`\_`, `\#`), re-bolds `Scenario N:` lines, and keeps `# **Heading**`, `| ---|` and `<br>`.
3. **Edit** only what was asked (a new scenario gets the next `No.`; message codes stay unique). Save as `_DRAFT.md` and show the changed part.
4. **Write back** the WHOLE page with `clickup_doc_write`, `mode="replace"` (`append` cannot insert under a section). Report the per-table result.

## Step 3 — Report (concise)

- Link: `[M-XXX-X: Title](https://app.clickup.com/t/<id>)` for a task, or the Doc page URL (inline link, never bare).
- The list it went to; assignee none.
- Fixes made to the spec + Open Questions for the BA.
- Tip: a table with a horizontal scrollbar on a narrow screen → the table's **fit container** icon in ClickUp.

## Gotchas

- Always pass `workspace_id`.
- `help.clickup.com` / `feedback.clickup.com` are blocked for fetch; don't retry.
- There is no API to delete a Doc or Doc page: don't create throwaway pages for testing, reuse one.
- You can't see the ClickUp UI: for visual confirmation ask for a screenshot.
