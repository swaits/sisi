"""Nothing in sisi/ is defined and never called: a function or class whose name appears nowhere else in the
product (sisi/, bin/, tools/) is dead code, and a test of it only keeps it alive."""
import ast, collections, glob, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Seams that are documented and exercised by real-behaviour tests (docs/evaluation.md); keep them.
# retry_choice is the pure ladder the `sisi route --retry-of` command calls; it lands with that command.
SEAMS = {"validate_check", "capture_case", "compare_for_candidate", "retry_choice"}


def _files():
    out = glob.glob(os.path.join(ROOT, "sisi", "*.py")) + glob.glob(os.path.join(ROOT, "bin", "*"))
    out += [f for f in glob.glob(os.path.join(ROOT, "tools", "**", "*"), recursive=True) if os.path.isfile(f)]
    return out


class NoDeadCode(unittest.TestCase):
    def test_every_function_and_class_in_sisi_is_referenced_somewhere(self):
        text = ""
        for f in _files():
            try:
                text += open(f, encoding="utf-8").read() + "\n"
            except (OSError, UnicodeDecodeError):
                pass
        words = collections.Counter(re.findall(r"\w+", text))
        dead = []
        for f in sorted(glob.glob(os.path.join(ROOT, "sisi", "*.py"))):
            for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith("__") \
                        and n.name not in SEAMS and words[n.name] <= 1:
                    dead.append("%s:%s" % (os.path.basename(f), n.name))
        self.assertEqual(dead, [])


if __name__ == "__main__":
    unittest.main()
