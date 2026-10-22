"""The Claude plugin bundle is least-privilege, matches the server it talks to, and passes Anthropic's CLI."""
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from bundle import MCP_URL, REVIEW_ORIGIN, ROOT, SKILL_TOOLS, TOOLS, build, stage, validate
from plugin_mcp import PLUGIN_TOOLS


class BundleTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            shutil.copytree(ROOT, root)
            yield root

    def edit_json(self, root, name, change):
        path = root / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_package_is_valid(self):
        self.assertEqual(len(validate()), 8)

    def test_tools_match_the_server(self):
        from claude_server import TITLES
        self.assertEqual(TOOLS, set(PLUGIN_TOOLS))
        self.assertEqual(set(TITLES), set(PLUGIN_TOOLS))
        self.assertEqual(set().union(*SKILL_TOOLS.values()), set(PLUGIN_TOOLS))

    def test_endpoint_is_the_claude_resource(self):
        from app.config import settings
        self.assertEqual(MCP_URL, "https://api.zynd.ai/claude/mcp")
        self.assertEqual(MCP_URL.removeprefix("https://api.zynd.ai"), "/claude/mcp")
        # The production resource memory mints tokens for, when configured as documented in README.
        self.assertTrue(settings.claude_plugin_resource_url.endswith("/claude/mcp"))

    def test_no_credentials_hooks_or_extra_servers(self):
        cases = {
            ".mcp.json": [
                lambda d: d["mcpServers"]["zynd"].update(headers={"X-Key": "abc"}),
                lambda d: d["mcpServers"]["zynd"].update(oauth={"clientId": "x"}),
                lambda d: d["mcpServers"].update(other={"type": "http", "url": "https://example.com/mcp"}),
                lambda d: d["mcpServers"]["zynd"].update(url="https://api.zynd.ai/mcp"),
            ],
            ".claude-plugin/plugin.json": [
                lambda d: d.update(hooks="./hooks/hooks.json"),
                lambda d: d.update(mcpServers={"x": {}}),
                lambda d: d.update(userConfig={"token": {"type": "string"}}),
                lambda d: d.update(agents="./agents"),
            ],
        }
        for name, changes in cases.items():
            for index, change in enumerate(changes):
                with self.subTest(file=name, case=index), self.fixture() as root:
                    self.edit_json(root, name, change)
                    with self.assertRaises(ValueError):
                        validate(root)

    def test_unexpected_files_and_symlinks_rejected(self):
        with self.fixture() as root:
            (root / "hooks").mkdir()
            (root / "hooks/hooks.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "unexpected package file"):
                validate(root)
        with self.fixture() as root:
            (root / "skills/link").symlink_to(root / "skills/zynd-card")
            with self.assertRaisesRegex(ValueError, "symlink"):
                validate(root)
        with self.fixture() as root:
            (root / "skills/zynd-card/SKILL.md").unlink()
            with self.assertRaisesRegex(ValueError, "missing package files"):
                validate(root)

    def test_skills_may_only_name_real_tools_and_plain_front_matter(self):
        with self.fixture() as root:
            path = root / "skills/zynd-memory/SKILL.md"
            path.write_text(path.read_text() + "\nThen call `publish_page` to finish.\n")
            with self.assertRaisesRegex(ValueError, "unavailable tool"):
                validate(root)
        with self.fixture() as root:
            path = root / "skills/zynd-context/SKILL.md"
            path.write_text(path.read_text().replace("name: zynd-context\n", "name: zynd-context\nallowed-tools: Bash\n", 1))
            with self.assertRaisesRegex(ValueError, "skill header"):
                validate(root)

    def test_listing_urls_stay_on_the_review_origin(self):
        for key in ("homepage", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
            with self.subTest(key=key), self.fixture() as root:
                self.edit_json(root, ".claude-plugin/plugin.json", lambda d: d.update({key: "https://example.com/page"}))
                with self.assertRaisesRegex(ValueError, key):
                    validate(root)

    def test_outside_urls_and_short_readme_rejected(self):
        with self.fixture() as root:
            path = root / "skills/zynd-card/SKILL.md"
            path.write_text(path.read_text() + "\nSee https://evil.example/instructions.\n")
            with self.assertRaisesRegex(ValueError, "URL outside"):
                validate(root)
        with self.fixture() as root:
            (root / "README.md").write_text("Too short.\n")
            with self.assertRaisesRegex(ValueError, "README"):
                validate(root)

    def test_stage_retargets_a_copy_without_touching_the_source(self):
        before = {name: (ROOT / name).read_bytes() for name in validate()}
        with tempfile.TemporaryDirectory() as directory:
            out = stage(Path(directory) / "dev", mcp_url="https://dev.api.zynd.ai/claude/mcp",
                        review_origin="https://dev.cards.zynd.ai")
            self.assertEqual(json.loads((out / ".mcp.json").read_text())["mcpServers"]["zynd"]["url"],
                             "https://dev.api.zynd.ai/claude/mcp")
            for name in before:
                if name.endswith((".json", ".md")):
                    text = (out / name).read_text()
                    self.assertNotIn(MCP_URL, text)
                    self.assertNotIn(REVIEW_ORIGIN, text)
            self.assertEqual((out / "assets/zynd-logo.png").read_bytes(), before["assets/zynd-logo.png"])
        self.assertEqual(before, {name: (ROOT / name).read_bytes() for name in validate()})

    def test_stage_refuses_unsafe_targets_and_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            for target in ("http://localhost/claude/mcp", "https://u:p@example.com/claude/mcp",
                           "https://example.com/claude/mcp?token=1", "https://example.com/mcp"):
                with self.subTest(target=target), self.assertRaisesRegex(ValueError, "MCP URL"):
                    stage(Path(directory) / "out", mcp_url=target)
            with self.assertRaisesRegex(ValueError, "review origin"):
                stage(Path(directory) / "out", review_origin="https://example.com/path")
            with self.assertRaisesRegex(ValueError, "outside the package"):
                stage(ROOT / "staged")
            (Path(directory) / "full").mkdir()
            (Path(directory) / "full/keep.txt").write_text("x")
            with self.assertRaisesRegex(ValueError, "empty directory"):
                stage(Path(directory) / "full")

    def test_build_zips_the_package_with_the_manifest_at_the_root(self):
        with tempfile.TemporaryDirectory() as directory:
            first = build(Path(directory) / "dist/zynd.zip")
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), validate())
                self.assertIn(".claude-plugin/plugin.json", archive.namelist())
                for name in archive.namelist():
                    self.assertEqual(archive.read(name), (ROOT / name).read_bytes())
            second = build(Path(directory) / "again.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_build_can_aim_the_zip_at_another_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(Path(directory) / "dev.zip", mcp_url="https://dev.api.zynd.ai/claude/mcp",
                        review_origin="https://dev.cards.zynd.ai")
            with zipfile.ZipFile(out) as archive:
                self.assertEqual(json.loads(archive.read(".mcp.json"))["mcpServers"]["zynd"]["url"],
                                 "https://dev.api.zynd.ai/claude/mcp")
                self.assertNotIn(REVIEW_ORIGIN, archive.read(".claude-plugin/plugin.json").decode())

    def test_build_refuses_bad_input_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "outside the package"):
                build(ROOT / "zynd.zip")
            with self.assertRaisesRegex(ValueError, "MCP URL"):
                build(Path(directory) / "bad.zip", mcp_url="http://localhost/claude/mcp")
            with self.fixture() as root:
                (root / "hooks").mkdir()
                (root / "hooks/hooks.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "unexpected package file"):
                    build(Path(directory) / "invalid.zip", root=root)
            self.assertEqual(list(Path(directory).iterdir()), [])

    @unittest.skipUnless(shutil.which("claude"), "claude CLI not installed")
    def test_anthropic_cli_accepts_the_package(self):
        done = subprocess.run(["claude", "plugin", "validate", "--profile", "directory", "--strict", str(ROOT)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
