"""Markdown -> Quill delta -> Doc paste HTML."""
import base64, json, os, re, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reclickup_mcp"))
from md2delta import md_to_delta
from delta2doc import convert, fit_doc


def texts(ops): return "".join(o["insert"] for o in ops if isinstance(o["insert"], str))
def tables(ops): return [o["insert"]["table-embed"] for o in ops if isinstance(o["insert"], dict)]
def cell(te, rc): return texts(te["cells"][rc]["content"])


class MarkdownTests(unittest.TestCase):
    def test_backslash_escapes_are_removed(self):
        """ClickUp's markdown export escapes _ * # ...; writing it back must not keep the backslashes."""
        ops = md_to_delta("Dùng clickup\\_doc\\_write và \\*\\*không đậm\\*\\*\n\n\\## không phải heading")["ops"]
        self.assertIn("clickup_doc_write", texts(ops)); self.assertNotIn("\\", texts(ops))
        self.assertIn("**không đậm**", texts(ops)); self.assertIn("## không phải heading", texts(ops))
        self.assertFalse(any(o.get("attributes", {}).get("header") for o in ops))

    def test_escaped_pipe_stays_in_its_cell(self):
        te = tables(md_to_delta("| No. | Acceptance Criteria |\n| --- | --- |\n| 01 | a \\| b |")["ops"])[0]
        self.assertEqual(cell(te, "2:2"), "a | b\n"); self.assertEqual(len(te["columns"]), 2)

    def test_unescaped_pipe_from_clickup_export_joins_last_column(self):
        te = tables(md_to_delta('| No. | Acceptance Criteria |\n| ---| --- |\n| 01 | Given a name "A | B"<br>Then ok |')["ops"])[0]
        self.assertEqual(len(te["columns"]), 2); self.assertIn('"A | B"', cell(te, "2:2"))

    def test_headings_lists_and_inline(self):
        md = "# Page title\n\n## Sub\n\n### Third\n\n- one\n  - nested\n1. first\n- [x] done\n- [ ] todo\n\n*it* `code` ~~gone~~ **b [l](https://x.y)**\n> quote"
        ops = md_to_delta(md)["ops"]
        self.assertNotIn("Page title", texts(ops))                                  # first H1 = the page title
        attrs = [o.get("attributes", {}) for o in ops if o["insert"] == "\n"]
        self.assertIn({"header": 2}, attrs); self.assertIn({"header": 3}, attrs)
        self.assertIn({"list": "bullet"}, attrs); self.assertIn({"list": "bullet", "indent": 1}, attrs)
        self.assertIn({"list": "ordered"}, attrs); self.assertIn({"list": "checked"}, attrs); self.assertIn({"list": "unchecked"}, attrs)
        self.assertIn({"blockquote": True}, attrs)
        by = {o["insert"]: o.get("attributes", {}) for o in ops if isinstance(o["insert"], str)}
        self.assertEqual(by["it"], {"italic": True}); self.assertEqual(by["code"], {"code": True}); self.assertEqual(by["gone"], {"strike": True})
        self.assertEqual(by["l"], {"bold": True, "link": "https://x.y"})

    def test_scenario_titles_bold_and_presets(self):
        md = "| No. | Acceptance Criteria |\n| --- | --- |\n| 01 | Scenario 1: Export<br>• Given x<br>     And y |"
        te = tables(md_to_delta(md)["ops"])[0]
        self.assertEqual([c["attributes"]["width"] for c in te["columns"]], ["60", "780"])
        first = te["cells"]["2:2"]["content"][0]
        self.assertEqual(first, {"insert": "Scenario 1: Export", "attributes": {"bold": True}})
        self.assertIn("     And y", cell(te, "2:2"))
        self.assertEqual(te["cells"]["1:1"]["attributes"]["cell-bg-color"], "green")

    def test_key_value_table(self):
        te = tables(md_to_delta("| User Story Name | M-1 X |\n| --- | --- |\n| Status | Draft |")["ops"])[0]
        self.assertEqual(te["cells"]["2:1"]["attributes"].get("cell-bg-color"), "green")
        self.assertIsNone(te["cells"]["2:2"]["attributes"].get("cell-bg-color"))

    def test_unknown_table_widths_sum_to_840(self):
        te = tables(md_to_delta("| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |")["ops"])[0]
        self.assertEqual(sum(int(c["attributes"]["width"]) for c in te["columns"]), 840)

    def test_nesting_with_two_or_four_spaces(self):
        for md in ("- a\n  - b\n    - c\n- d", "*   a\n    *   b\n        *   c\n*   d"):   # common style / ClickUp export
            attrs = [o.get("attributes", {}) for o in md_to_delta(md)["ops"] if o["insert"] == "\n"]
            self.assertEqual([a.get("indent", 0) for a in attrs], [0, 1, 2, 0], md)

    def test_bold_line_is_not_a_bullet(self):
        ops = md_to_delta("**Screen: Invoices**")["ops"]
        self.assertEqual(ops[0], {"insert": "Screen: Invoices", "attributes": {"bold": True}})
        self.assertEqual(ops[1], {"insert": "\n"})


class DocHtmlTests(unittest.TestCase):
    def test_tables_fit_720_and_lists_group(self):
        md = "## Sub\n\n- a\n- b\n1. c\n\n| No. | Acceptance Criteria |\n| --- | --- |\n| 01 | x |\n\n| A | B |\n|---|---|\n| 1 | 2 |"
        html = convert(md_to_delta(md)["ops"])
        self.assertIn('<h2><strong>Sub</strong></h2><ol><li data-list="bullet">a</li><li data-list="bullet">b</li>'
                      '<li data-list="ordered">c</li></ol>', html)
        for b64 in re.findall(r'data-table-embed-value="([^"]+)"', html):
            te = json.loads(base64.b64decode(b64))
            self.assertEqual(sum(int(c["attributes"]["width"]) for c in te["columns"]), 720)

    def test_checklist_and_nesting_use_quill2_lists(self):
        html = convert(md_to_delta("- [ ] todo\n- [x] done\n- a\n  - b")["ops"])
        self.assertIn('<li data-list="unchecked">todo</li><li data-list="checked">done</li>', html)
        self.assertIn('<li data-list="bullet" class="ql-indent-1">b</li>', html)

    def test_html_is_escaped(self):
        self.assertIn("&lt;script&gt;", convert(md_to_delta("a <script> b")["ops"]))

    def test_fit_doc_presets(self):
        te = tables(md_to_delta("| Code | Type | Message | Shown when |\n|---|---|---|---|\n| M1 | t | m | s |")["ops"])[0]
        self.assertEqual([c["attributes"]["width"] for c in fit_doc(te)["columns"]], ["70", "100", "310", "240"])


if __name__ == "__main__":
    unittest.main()
