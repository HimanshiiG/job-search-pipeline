"""Resume Markdown -> LaTeX converter. Run: py -m unittest discover tests"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jobhunt import latex  # noqa: E402

MD = """<!-- note -->
# Jane Doe
Data Engineer | Streaming & CDC
+1 555 | jane@example.com | linkedin.com/in/jane
Berlin, Germany | Open to relocation

## Professional Summary
Builds pipelines, cut cost 50% and
moved data 6 hours earlier.

## Technical Skills
- **Streaming & CDC:** Kafka, Change Data Capture (CDC)

## Experience
### Acme Corp | Data Engineer | Berlin | Jun 2025 - Present
- Cut scans ~300x for $0 with R&D_team
  on a continuation line.

## Education
Uni | B.Tech | Mumbai, India | 2021 - 2025
"""


class Latex(unittest.TestCase):
    def test_structure_and_escaping(self):
        t = latex.md_to_tex(MD)
        self.assertIn(r"\textbf{Jane Doe}", t)
        self.assertNotIn("note", t)                                    # comments dropped
        self.assertIn(r"\href{mailto:jane@example.com}", t)
        self.assertIn(r"\section{Professional Summary}", t)
        self.assertIn("cut cost 50\\% and moved data", t)              # one paragraph, % escaped
        self.assertIn(r"\item[] \textbf{Streaming \& CDC}: Kafka", t)
        self.assertIn(r"\entry{Acme Corp}{Data Engineer}{Berlin}{Jun 2025 - Present}", t)
        self.assertIn(r"\$0 with R\&D\_team on a continuation line.", t)
        self.assertIn(r"\textasciitilde{}300x", t)
        self.assertIn(r"\entry{Uni}{B.Tech}{Mumbai, India}{2021 - 2025}", t)
        self.assertEqual(t.count(r"\begin{itemize}"), t.count(r"\end{itemize}"))
        self.assertTrue(t.rstrip().endswith(r"\end{document}"))


if __name__ == "__main__":
    unittest.main()
