import json
import shutil
import tempfile
import unittest
from pathlib import Path

from build import ROOT, build, validate


class PackageTests(unittest.TestCase):
    def test_draft_valid_and_reproducible(self):
        self.assertEqual(len(validate()), 9)
        with tempfile.TemporaryDirectory() as directory:
            first = build(Path(directory) / "first.zip")
            second = build(Path(directory) / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_submission_needs_real_metadata(self):
        with self.assertRaisesRegex(ValueError, "supportURL"):
            validate(submission=True)

    def test_missing_file(self):
        with self.fixture() as root:
            (root / "skills/zynd-card/SKILL.md").unlink()
            with self.assertRaisesRegex(ValueError, "missing package files"):
                validate(root)

    def test_secret_header_rejected(self):
        with self.fixture() as root:
            path = root / "mcp.json"
            data = json.loads(path.read_text())
            data["mcpServers"]["zynd"]["headers"] = {"Authorization": "Bearer example"}
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "MCP transport|headers"):
                validate(root)

    def test_unsafe_symlink_rejected(self):
        with self.fixture() as root:
            (root / "skills/zynd-card/SKILL.md").unlink()
            (root / "skills/zynd-card/SKILL.md").symlink_to("../../../../etc/passwd")
            with self.assertRaisesRegex(ValueError, "symlink forbidden"):
                validate(root)

    def test_unavailable_tool_rejected(self):
        with self.fixture() as root:
            path = root / "skills/zynd-context/SKILL.md"
            path.write_text(path.read_text() + "\nCall `find_people` for everyone.\n")
            with self.assertRaisesRegex(ValueError, "unavailable tool"):
                validate(root)

    def test_unexpected_file_rejected(self):
        with self.fixture() as root:
            (root / "assets/secret.txt").write_text("token")
            with self.assertRaisesRegex(ValueError, "unexpected package file"):
                validate(root)

    def fixture(self):
        class Copy:
            def __enter__(self):
                self.temp = tempfile.TemporaryDirectory()
                self.root = Path(self.temp.name) / "zynd"
                shutil.copytree(ROOT, self.root)
                return self.root

            def __exit__(self, *_):
                self.temp.cleanup()

        return Copy()


if __name__ == "__main__":
    unittest.main()
