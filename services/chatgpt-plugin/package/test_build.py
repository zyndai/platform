import json
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from build import ROOT, MCP_URL, REVIEW_ORIGIN, SCOPES, TOOLS, build, validate


class PackageTests(unittest.TestCase):
    def test_draft_valid_and_reproducible(self):
        self.assertEqual(len(validate()), 9)
        with tempfile.TemporaryDirectory() as directory:
            first = build(Path(directory) / "first.zip")
            second = build(Path(directory) / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(sorted(archive.namelist()), validate())
                self.assertFalse(any("__pycache__" in name for name in archive.namelist()))

    def test_least_privilege_contract(self):
        data = json.loads((ROOT / "mcp.json").read_text())
        self.assertEqual(data["mcpServers"]["zynd"]["extensions"]["com.openai"]["auth"]["baseScopes"],
                         ["memory:recall", "memory:propose", "cards:review"])
        self.assertEqual(TOOLS, {"recall_memories", "propose_memory", "get_proposal_status",
                                 "list_pending_facts", "propose_card_fact", "get_public_card"})

    def test_legacy_or_extra_scopes_rejected(self):
        for scopes in (["user"], ["memory:write", "cards:read", "cards:approve"],
                       SCOPES + ["cards:approve"]):
            with self.subTest(scopes=scopes), self.fixture() as root:
                path = root / "mcp.json"
                data = json.loads(path.read_text())
                data["mcpServers"]["zynd"]["extensions"]["com.openai"]["auth"]["baseScopes"] = scopes
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "OAuth"):
                    validate(root)

    def test_isolated_targets_are_reproducible_and_do_not_change_source(self):
        with self.fixture() as root, tempfile.TemporaryDirectory() as directory:
            original = {name: (root / name).read_bytes() for name in validate(root)}
            options = dict(root=root, mcp_url="https://memory.test.example/chatgpt/mcp",
                           review_origin="https://review.test.example")
            first = build(Path(directory) / "test.zip", **options)
            second = build(Path(directory) / "test-again.zip", **options)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(original, {name: (root / name).read_bytes() for name in validate(root)})
            with zipfile.ZipFile(first) as archive:
                mcp = json.loads(archive.read("mcp.json"))
                server = mcp["mcpServers"]["zynd"]
                self.assertEqual(server["url"], options["mcp_url"])
                self.assertEqual(server["extensions"]["com.openai"]["auth"]["resource"], options["mcp_url"])
                for name in archive.namelist():
                    if name.endswith((".json", ".md", ".yaml")):
                        text = archive.read(name).decode()
                        self.assertNotIn(MCP_URL, text)
                        self.assertNotIn(REVIEW_ORIGIN, text)
                self.assertIn(options["review_origin"], archive.read("skills/zynd-card/SKILL.md").decode())

    def test_unsafe_test_targets_rejected_before_output(self):
        for target in ("http://localhost/chatgpt/mcp", "https://user:pass@example.com/chatgpt/mcp",
                       "https://example.com/chatgpt/mcp?token=secret", "https://example.com/chatgpt/mcp#frag",
                       "https://example.com/mcp"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "invalid.zip"
                with self.assertRaisesRegex(ValueError, "MCP URL"):
                    build(output, mcp_url=target)
                self.assertFalse(output.exists())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "review origin"):
                build(Path(directory) / "invalid.zip", review_origin="https://example.com/path")
            with self.assertRaisesRegex(ValueError, "test targets"):
                build(Path(directory) / "invalid.zip", submission=True, mcp_url="https://test.example/chatgpt/mcp")

    def test_hooks_and_extra_dependencies_rejected(self):
        with self.fixture() as root:
            path = root / "plugin.json"
            data = json.loads(path.read_text())
            data["extensions"]["com.openai"]["hooks"] = "./hooks.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "lifecycle hook"):
                validate(root)
        with self.fixture() as root:
            path = root / "skills/zynd-memory/agents/openai.yaml"
            path.write_text(path.read_text() + '    - type: "mcp"\n      value: "other"\n')
            with self.assertRaisesRegex(ValueError, "MCP dependency"):
                validate(root)

    def test_submission_still_blocked_with_listing_urls(self):
        with self.fixture() as root:
            path = root / "plugin.json"
            data = json.loads(path.read_text())
            extension = data["extensions"]["com.openai"]
            extension["review"]["demo_recording_url"] = "https://zynd.ai/example-recording"
            extension["publication"]["countries"] = ["US"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "external reviewer account"):
                validate(root, submission=True)

    def test_listing_urls_required_on_review_origin(self):
        for key in ("supportURL", "privacyPolicyURL", "termsOfServiceURL"):
            with self.subTest(missing=key), self.fixture() as root:
                path = root / "plugin.json"
                data = json.loads(path.read_text())
                del data["extensions"]["com.openai"]["interface"][key]
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, key):
                    validate(root)
            with self.subTest(off_origin=key), self.fixture() as root:
                path = root / "plugin.json"
                data = json.loads(path.read_text())
                data["extensions"]["com.openai"]["interface"][key] = "https://example.com/page"
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "must be on"):
                    validate(root)

    def test_listing_text_cannot_call_itself_an_unverified_draft(self):
        for field in ("longDescription", "shortDescription"):
            with self.subTest(field=field), self.fixture() as root:
                path = root / "plugin.json"
                data = json.loads(path.read_text())
                data["extensions"]["com.openai"]["interface"][field] += " Draft contract; installed-client behavior is not yet verified."
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "unverified draft"):
                    validate(root)
        with self.fixture() as root:
            path = root / "plugin.json"
            data = json.loads(path.read_text())
            data["extensions"]["com.openai"]["publication"]["release_notes"] = "Not for public submission."
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unverified draft"):
                validate(root)

    def test_official_schemas_validate_projection_independently(self):
        from build import validate_official_schemas

        try:
            import jsonschema
        except ImportError:
            self.skipTest("optional jsonschema dependency not installed")
        # Synthetic strict schemas verify the validator invokes the library and
        # removes only the documented OAuth extension from the MCP projection.
        schema = {"type": "object", "properties": {"mcpServers": {"type": "object",
                  "properties": {"zynd": {"type": "object", "properties": {
                      "type": {"const": "streamable-http"}, "url": {"const": MCP_URL}},
                      "additionalProperties": False}}}}}
        import io
        responses = [io.BytesIO(b'{"type":"object","required":["name","version"]}'),
                     io.BytesIO(json.dumps(schema).encode())]
        with patch("build.urlopen", side_effect=responses) as fetch:
            validate_official_schemas()
            self.assertEqual(fetch.call_count, 2)

    def test_submission_needs_real_metadata(self):
        with self.assertRaisesRegex(ValueError, "walkthrough"):
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
        for tool in ("find_people", "get_my_context", "report_user_info", "approve_fact",
                     "unknown_future_tool"):
            with self.subTest(tool=tool), self.fixture() as root:
                path = root / "skills/zynd-context/SKILL.md"
                path.write_text(path.read_text() + f"\nCall `{tool}`.\n")
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
