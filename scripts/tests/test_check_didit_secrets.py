"""Synthetic regression cases; no real credentials are read or exercised."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "check_didit_secrets", Path(__file__).resolve().parents[1] / "check_didit_secrets.py",
)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
KEY = "DIDIT_" + "API_KEY"
WEBHOOK = "DIDIT_" + "WEBHOOK_SECRET"
SYNTHETIC = "synthetic_" + "fixture_0123456789"


class DiditSecretCheckTests(unittest.TestCase):
    def test_env_and_quoted_assignments(self):
        for key in (KEY, WEBHOOK, KEY.lower()):
            for quote in ("", '"', "'"):
                with self.subTest(key=key, quote=quote):
                    self.assertEqual(scanner.finding_lines(
                        f"# preamble\nexport {key}={quote}{SYNTHETIC}{quote}\n"
                    ), [2])

    def test_json_and_multiline_json(self):
        for whitespace in (" ", "\n  "):
            self.assertEqual(scanner.finding_lines(
                '{"' + KEY + '":' + whitespace + '"' + SYNTHETIC + '"}'
            ), [1])

    def test_markdown_handoff_table(self):
        self.assertEqual(scanner.finding_lines(
            f"| Variable | Value | Source |\n| `{KEY}` | `{SYNTHETIC}` | handoff |"
        ), [2])

    def test_references_placeholders_and_runtime_reads(self):
        examples = [
            f"Read `{KEY}` from the environment.",
            f'{KEY}="<set securely>"',
            f'{KEY}="${{{KEY}}}"',
            f'{KEY}=your-api-key-here',
            f'| `{KEY}` | `REDACTED-PENDING-ROTATION` | removed |',
            f'{KEY}=os.environ.get("{KEY}")',
            f'{KEY} = _require_env("{KEY}")',
        ]
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(scanner.finding_lines(example), [])

    def test_reports_only_path_and_line_never_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "handoff.md").write_text(f"\n{KEY}={SYNTHETIC}\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = scanner.scan_paths(root, ["handoff.md"])
            self.assertEqual(status, 1)
            self.assertIn("handoff.md:2:", output.getvalue())
            self.assertNotIn(SYNTHETIC, output.getvalue())

    def test_unsupported_names_and_short_literals_are_outside_scope(self):
        self.assertEqual(scanner.finding_lines(f"OTHER_KEY={SYNTHETIC}"), [])
        self.assertEqual(scanner.finding_lines(f"{KEY}=short"), [])


if __name__ == "__main__":
    unittest.main()
