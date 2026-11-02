# reclickup-mcp

An MCP server that gives you **every tool of the official ClickUp MCP** plus one thing it cannot do:
**write formatted tables into a ClickUp Doc** — set column widths, green header cells, bold text —
straight from Markdown, with nothing to copy or paste.

## Why

ClickUp's public Docs API (and the official MCP's `create/update_document_page`) only accepts Markdown
or plain text. Tables written that way always get equal-width columns and no cell colours.

The Doc editor does accept a **paste** whose `text/html` carries each table as

```html
<span class="ql-table-embed" data-table-embed-value="BASE64(JSON table-embed)"></span>
```

That is what ClickUp itself puts on the clipboard when you copy a task description. Column widths,
`cell-bg-color`, bold, links and headings all survive, and the result is saved server-side.
reclickup builds that HTML and pastes it inside its own **headless Microsoft Edge**: no window and
no clipboard.

## Tools

| Tool | What it does |
| --- | --- |
| all `clickup_*` tools of the official server | Proxied unchanged from `https://mcp.clickup.com/mcp` through [`mcp-remote`](https://www.npmjs.com/package/mcp-remote), so they stay current. |
| `clickup_doc_write` | Writes into a Doc page (`page_url`) from `markdown` (or a Quill `delta`). `mode` is `replace` (default) or `append`. If the page is untitled, it is named after the first `# ` line. Reloads the page and returns the widths, green cells and alignment of every table. Takes about 25 s. |
| `clickup_relogin` | Refreshes the ClickUp session of reclickup's headless browser. |

### Markdown it understands

`# Heading`, paragraphs, `**bold**`, `[links](url)` and pipe tables. Every table gets a bold header
row with green background cells. A table whose first header cell is `User Story Name` is a
key/value table: its first column is styled instead. Columns are sized to the Doc's 720 px text
column. Presets cover the common user-story tables (`md2delta.py` / `delta2doc.py`); any other
table is scaled proportionally.

## How it works

- **Proxy:** `server.py` speaks MCP over stdio. It starts `npx -y mcp-remote@0.15.1 https://mcp.clickup.com/mcp`,
  forwards `tools/list` and `tools/call`, and adds its own tools. Each request runs in its own
  thread, so a slow Doc write does not block other calls.
- **Browser:** `browser.py` runs a private headless Edge on port **9335** with its own profile
  (`~/.reclickup/headless-profile`). It starts on demand and stops after 10 minutes idle
  (`RECLICKUP_IDLE_STOP`).
- **Session:** the ClickUp session (`cu_jwt` cookie) is copied once into that profile:
  - **macOS:** from a running debug Edge on `:9222` if one is signed in, else decrypted from your
    real Edge profile. Keychain asks once for "Microsoft Edge Safe Storage": click Allow.
  - **Windows:** `clickup_relogin` opens an Edge window at the ClickUp login. Sign in once; the
    profile keeps the session.

## Install

Requirements: Python ≥ 3.9, Node.js (for `npx`), Microsoft Edge.

```bash
git clone https://github.com/haonguyenstech/reclickup-mcp.git
cd reclickup-mcp
python3 -m pip install -r requirements.txt
```

Authorize the official ClickUp MCP once. A browser opens: sign in and approve. The token is
cached in `~/.mcp-auth`.

```bash
npx -y mcp-remote@0.15.1 https://mcp.clickup.com/mcp
# wait for "Connected", then Ctrl+C
```

### Claude Desktop

Add the server to `claude_desktop_config.json` and restart Claude Desktop:

```json
{
  "mcpServers": {
    "reclickup-mcp": {
      "command": "python3",
      "args": ["/absolute/path/to/reclickup-mcp/server.py"],
      "env": { "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" }
    }
  }
}
```

`PATH` must reach `node`/`npx`. On Windows use `"command": "python"` and a Windows path.

### Claude Code

```bash
claude mcp add reclickup-mcp -- python3 /absolute/path/to/reclickup-mcp/server.py
```

## Environment variables

| Variable | Default | |
| --- | --- | --- |
| `RECLICKUP_PORT` | `9335` | CDP port of the headless Edge |
| `RECLICKUP_IDLE_STOP` | `600` | Seconds of inactivity before the headless Edge is closed |
| `RECLICKUP_BROWSER` | auto | Path to the Edge executable |
| `RECLICKUP_EDGE_PROFILE` | `~/Library/Application Support/Microsoft Edge/Default` | Real Edge profile to copy the session from (macOS) |
| `RECLICKUP_NPX` | `npx` on `PATH` | `npx` to run `mcp-remote` |
| `RECLICKUP_UPSTREAM` | `https://mcp.clickup.com/mcp` | Upstream MCP URL |

Upstream (`mcp-remote`) stderr is logged to `upstream.log` next to `server.py`.

## Caveats

- `clickup_doc_write` relies on how ClickUp's web editor handles a paste, not on a public API.
  It can break if ClickUp changes the editor. The read-back check after each write reports
  that right away.
- Doc pages and tasks are different editors. `clickup_doc_write` only targets Doc pages
  (`/v/dc/…` or `/docs/…` links).

## License

MIT
