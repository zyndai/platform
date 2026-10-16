"""Validate and reproducibly package the ZYND plugin (stdlib only).

Run `python3 plugins/zynd/build.py --output /tmp/zynd-draft.zip` from any cwd.
Submission validation is stricter: `--submission` refuses missing verified
listing/review data. No ZIP is written on validation failure.
"""

import argparse
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
SKILLS = ("zynd-memory", "zynd-context", "zynd-card")
TOOLS = {
    "report_user_info", "get_my_context", "confirm_fact_tool", "forget_fact_tool",
    "list_pending_facts", "list_intros", "approve_fact", "dismiss_fact",
    "set_looking_for",
}
SCOPES = ["memory:write", "cards:read", "cards:approve"]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and bool(parsed.hostname) and
            not parsed.username and not parsed.password and not parsed.fragment and
            not parsed.query and parsed.path != "/placeholder")


def files(root):
    allowed = {"plugin.json", "mcp.json", "assets/zynd-logo.png"}
    for skill in SKILLS:
        allowed.update({f"skills/{skill}/SKILL.md", f"skills/{skill}/agents/openai.yaml"})
    discovered = set()
    for item in root.rglob("*"):
        rel = item.relative_to(root).as_posix()
        require(not item.is_symlink(), f"symlink forbidden: {rel}")
        require(not item.is_file() or rel in allowed or rel in {"build.py", "test_build.py"},
                f"unexpected package file: {rel}")
        if rel in allowed:
            require(item.is_file(), f"missing regular file: {rel}")
            discovered.add(rel)
    require(discovered == allowed, f"missing package files: {sorted(allowed - discovered)}")
    for name in discovered:
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts and
                all(part not in ("", ".") for part in path.parts), f"unsafe path: {name}")
    return sorted(discovered)


def validate(root=ROOT, submission=False):
    names = files(root)
    plugin = json.loads((root / "plugin.json").read_text())
    mcp = json.loads((root / "mcp.json").read_text())
    require(plugin.get("$schema") == PLUGIN_SCHEMA and plugin.get("name") == "zynd" and
            re.fullmatch(r"\d+\.\d+\.\d+", plugin.get("version", "")), "invalid plugin identity")
    require(mcp.get("$schema") == MCP_SCHEMA and set(mcp) == {"$schema", "mcpServers"},
            "invalid portable MCP fields")
    require(set(mcp["mcpServers"]) == {"zynd"}, "expected one ZYND MCP server")
    server = mcp["mcpServers"]["zynd"]
    # The published Agent Plugins MCP schema disallows unknown server keys;
    # OpenAI's documented OAuth extension is checked independently below.
    require(set(server) == {"type", "url", "extensions"} and
            server["type"] == "streamable-http" and server["url"] == "https://api.zynd.ai/mcp",
            "invalid MCP transport or endpoint")
    auth = server["extensions"]["com.openai"]["auth"]
    require(set(auth) == {"type", "client", "resource", "baseScopes"} and
            auth["type"] == "oauth" and auth["resource"] == server["url"] and
            auth["client"] == {"mode": "provided", "clientId": "zynd-chatgpt-plugin",
                               "tokenEndpointAuthMethod": "none"} and
            auth["baseScopes"] == SCOPES, "invalid public OAuth configuration")
    require("headers" not in server, "server headers forbidden")
    interface = plugin["extensions"]["com.openai"]["interface"]
    require(all(interface.get(key) for key in ("displayName", "shortDescription",
                                           "longDescription", "developerName", "category")),
            "missing listing description")
    require(interface["logo"] == "./assets/zynd-logo.png" and
            interface["composerIcon"] == "./assets/zynd-logo.png", "missing brand image references")
    image = (root / "assets/zynd-logo.png").read_bytes()
    require(image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) <= 5 * 1024 * 1024 and
            int.from_bytes(image[16:20], "big") == int.from_bytes(image[20:24], "big") and
            48 <= int.from_bytes(image[16:20], "big") <= 4096, "logo must be a valid-size square PNG")
    for skill in SKILLS:
        body = (root / f"skills/{skill}/SKILL.md").read_text()
        require(body.startswith(f"---\nname: {skill}\ndescription: ") and
                "\n---\n" in body, f"invalid skill header: {skill}")
        referenced = set(re.findall(r"`([a-z][a-z_]+)`", body)) & (TOOLS | {
            "export_my_context", "find_people", "send_persona_message", "publish_page"})
        require(referenced <= TOOLS, f"unavailable tool in {skill}: {referenced - TOOLS}")
        dependency = (root / f"skills/{skill}/agents/openai.yaml").read_text()
        require('value: "zynd"' in dependency and
                'transport: "streamable_http"' in dependency and
                'url: "https://api.zynd.ai/mcp"' in dependency, f"invalid MCP dependency: {skill}")
    text = "\n".join((root / name).read_text() for name in names if name.endswith((".json", ".md", ".yaml")))
    require(not re.search(r"(?i)(authorization\s*[:=]|bearer\s+\S+|clientsecret|api[_-]?key\s*[:=]|-----BEGIN .*PRIVATE KEY-----)", text),
            "possible credential or authorization header in package")
    require("https://api.zynd.ai/mcp" in text, "missing endpoint")
    review = plugin["extensions"]["com.openai"].get("review", {})
    cases = review.get("test_cases", {})
    require(len(cases.get("positive", [])) == 5 and len(cases.get("negative", [])) == 3,
            "five positive and three negative review cases required")
    for kind in ("positive", "negative"):
        for case in cases[kind]:
            require(all(case.get(key) for key in ("description", "prompt", "expected_behavior")),
                    f"incomplete {kind} review case")
    if submission:
        for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
            require(safe_url(interface.get(key)), f"submission requires verified {key}")
        require(safe_url(review.get("demo_recording_url")), "submission requires actual walkthrough URL")
        require(plugin["extensions"]["com.openai"].get("publication", {}).get("countries"),
                "submission requires verified country availability")
        # The review account and credentials belong only in the private portal, never in this ZIP.
        raise ValueError("submission requires external reviewer account, executed cases, domain verification and live OAuth/tool scan")
    return names


def build(output, root=ROOT, submission=False):
    names = validate(root, submission)
    output = Path(output).resolve()
    require(not output.is_relative_to(root.resolve()), "write the generated ZIP outside the plugin folder")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="ZIP output path (outside plugins/zynd)")
    parser.add_argument("--submission", action="store_true", help="fail closed until submission prerequisites are verified")
    args = parser.parse_args()
    try:
        if args.output:
            print(build(args.output, submission=args.submission))
        else:
            print(f"Validated {len(validate(submission=args.submission))} package files; no ZIP written")
        if args.submission:
            print("Portal steps still required: reviewer account, executed cases, domain verification, live OAuth/tool scan.")
    except ValueError as exc:
        parser.exit(1, f"Package invalid: {exc}\n")
