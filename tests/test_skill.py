"""The skill's scripts: same converters as the package, and they run from the command line."""
import filecmp, json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills", "clickup-user-story")
DRAFT = """# M-1-1: Export

| User Story Name | M-1-1 Export |
| --- | --- |
| Status | Draft |

# **Acceptance Criteria**

| No. | Acceptance Criteria |
| --- | --- |
| 01 | Scenario 1: Xuất file ờ ự<br>• Given x<br>     And y |
"""


def run(*args, stdin=None):
    return subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, encoding="utf-8", check=True)


class SkillTests(unittest.TestCase):
    def test_scripts_match_the_package(self):
        for f in ("md2delta.py", "delta2doc.py"):
            self.assertTrue(filecmp.cmp(os.path.join(ROOT, "reclickup_mcp", f), os.path.join(SK, "scripts", f), shallow=False),
                            f"skills/.../scripts/{f} differs from reclickup_mcp/{f}: copy it over")

    def test_skill_references_exist(self):
        text = open(os.path.join(SK, "SKILL.md"), encoding="utf-8").read()
        for rel in ("scripts/md2delta.py", "scripts/check_delta.py", "scripts/fix_delta.py", "reference/doc-fallback.md"):
            self.assertIn(rel, text + open(os.path.join(SK, "reference", "doc-fallback.md"), encoding="utf-8").read())
            self.assertTrue(os.path.exists(os.path.join(SK, rel)), rel)

    def test_cli_pipeline(self):
        d = tempfile.mkdtemp()
        md = os.path.join(d, "draft.md"); open(md, "w", encoding="utf-8").write(DRAFT)
        delta = run(os.path.join(SK, "scripts", "md2delta.py"), md).stdout
        dj = os.path.join(d, "delta.json"); open(dj, "w", encoding="utf-8").write(delta)
        out = run(os.path.join(SK, "scripts", "check_delta.py"), dj).stdout
        self.assertEqual(out.count("sum 840"), 2); self.assertIn("scenarios not bold: []", out)
        # break the widths and colours as a markdown-created task has them, then repair
        d2 = json.loads(delta)
        for o in d2["ops"]:
            if isinstance(o["insert"], dict):
                for c in o["insert"]["table-embed"]["columns"]: c["attributes"]["width"] = "238"
                for c in o["insert"]["table-embed"]["cells"].values(): c["attributes"].pop("cell-bg-color", None)
        old = os.path.join(d, "old.json"); open(old, "w", encoding="utf-8").write(json.dumps(json.dumps(d2)))   # raw content string
        fixed = run(os.path.join(SK, "scripts", "fix_delta.py"), old).stdout
        nj = os.path.join(d, "new.json"); open(nj, "w", encoding="utf-8").write(fixed)
        out = run(os.path.join(SK, "scripts", "check_delta.py"), nj).stdout
        self.assertEqual(out.count("sum 840"), 2); self.assertNotIn("green cells 0", out)
        page = run(os.path.join(SK, "scripts", "delta2doc.py"), dj, "--page", "M-1-1: Export").stdout
        self.assertIn("Copy for ClickUp Doc", page); self.assertIn("ql-table-embed", page)


if __name__ == "__main__":
    unittest.main()
