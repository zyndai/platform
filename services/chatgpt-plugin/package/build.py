"""Validate and reproducibly package the ZYND plugin (stdlib only).

Run `python3 services/chatgpt-plugin/package/build.py --output /tmp/zynd-draft.zip` from any cwd.
Submission validation is stricter: `--submission` refuses missing verified
listing/review data. No ZIP is written on validation failure.
"""

import argparse
import json
import re
import zipfile
from urllib.request import urlopen
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
SKILLS = ("zynd-memory", "zynd-context", "zynd-card")
TOOLS = {
    "recall_memories", "propose_memory", "get_proposal_status",
    "list_pending_facts", "propose_card_fact", "get_public_card",
}
SKILL_TOOLS = {
    "zynd-memory": {"propose_memory", "get_proposal_status"},
    "zynd-context": {"recall_memories"},
    "zynd-card": {"list_pending_facts", "propose_card_fact", "get_proposal_status", "get_public_card"},
}
SCOPES = ["memory:recall", "memory:propose", "cards:review"]
MCP_URL = "https://api.zynd.ai/chatgpt/mcp"
REVIEW_ORIGIN = "https://cards.zynd.ai"
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
        require(not item.is_file() or rel in allowed or rel in {"build.py", "test_build.py"} or
                (item.parent.name == "__pycache__" and item.parent.parent == root and
                 re.fullmatch(r"(?:build|test_build)\.cpython-[\w.-]+\.pyc", item.name)),
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
            server["type"] == "streamable-http" and server["url"] == MCP_URL,
            "invalid MCP transport or endpoint")
    require(set(server["extensions"]) == {"com.openai"} and
            set(server["extensions"]["com.openai"]) == {"auth"}, "unexpected MCP extension")
    auth = server["extensions"]["com.openai"]["auth"]
    require(set(auth) == {"type", "client", "resource", "baseScopes"} and
            auth["type"] == "oauth" and auth["resource"] == server["url"] and
            auth["client"] == {"mode": "provided", "clientId": "zynd-chatgpt-plugin",
                               "tokenEndpointAuthMethod": "none"} and
            auth["baseScopes"] == SCOPES, "invalid public OAuth configuration")
    require("headers" not in server, "server headers forbidden")
    interface = plugin["extensions"]["com.openai"]["interface"]
    require(interface.get("displayName") == "Zynd", "display name must be Zynd")
    require(set(plugin["extensions"]) == {"com.openai"} and
            set(plugin["extensions"]["com.openai"]) <= {"interface", "review", "publication"},
            "unexpected plugin extension or lifecycle hook")
    require(all(interface.get(key) for key in ("displayName", "shortDescription",
                                           "longDescription", "developerName", "category")),
            "missing listing description")
    # The portal rejects a listing without these, so a draft ZIP must carry them too.
    for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
        value = interface.get(key)
        require(safe_url(value), f"listing requires {key} as a plain HTTPS URL")
        require(value == REVIEW_ORIGIN or value.startswith(REVIEW_ORIGIN + "/"),
                f"{key} must be on {REVIEW_ORIGIN}")
    # Listing text is public; it must not announce itself as an unverified draft.
    listing = " ".join([interface["shortDescription"], interface["longDescription"],
                        plugin["extensions"]["com.openai"].get("publication", {}).get("release_notes", "")])
    require(not re.search(r"(?i)\bdraft (?:contract|\d)|not yet verified|unverified|not for public", listing),
            "listing text must not describe the plugin as an unverified draft")
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
        referenced = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", body))
        require(referenced == SKILL_TOOLS[skill],
                f"unavailable tool or missing expected tool in {skill}: {referenced ^ SKILL_TOOLS[skill]}")
        dependency = (root / f"skills/{skill}/agents/openai.yaml").read_text()
        require(re.fullmatch(
            r'dependencies:\n  tools:\n    - type: "mcp"\n      value: "zynd"\n'
            r'      description: "[^"\n]+"\n      transport: "streamable_http"\n'
            r'      url: "https://api\.zynd\.ai/chatgpt/mcp"\n\s*', dependency),
            f"invalid MCP dependency: {skill}")
    text = "\n".join((root / name).read_text() for name in names if name.endswith((".json", ".md", ".yaml")))
    require(not re.search(r"(?i)(authorization\s*[:=]|bearer\s+\S+|clientsecret|api[_-]?key\s*[:=]|-----BEGIN .*PRIVATE KEY-----)", text),
            "possible credential or authorization header in package")
    require("https://api.zynd.ai/chatgpt/mcp" in text, "missing endpoint")
    review = plugin["extensions"]["com.openai"].get("review", {})
    cases = review.get("test_cases", {})
    require(len(cases.get("positive", [])) == 5 and len(cases.get("negative", [])) == 6,
            "five positive and six negative review cases required")
    for kind in ("positive", "negative"):
        for case in cases[kind]:
            require(all(case.get(key) for key in ("description", "prompt", "expected_behavior")),
                    f"incomplete {kind} review case")
    if submission:
        require(safe_url(review.get("demo_recording_url")), "submission requires actual walkthrough URL")
        require(plugin["extensions"]["com.openai"].get("publication", {}).get("countries"),
                "submission requires verified country availability")
        # The review account and credentials belong only in the private portal, never in this ZIP.
        raise ValueError("submission requires external reviewer account, executed cases, domain verification and live OAuth/tool scan")
    return names


def validate_official_schemas(root=ROOT):
    """Check current vendor schemas independently of local policy (requires jsonschema).

    The portable MCP schema currently forbids OpenAI's documented extensions.
    Validate the portable projection, then the OAuth extension via validate().
    This is deliberately not a claim that the full MCP file passes that schema.
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError("--official-schemas requires jsonschema in your validation environment") from exc

    validate(root)
    for filename, schema_url in (("plugin.json", PLUGIN_SCHEMA), ("mcp.json", MCP_SCHEMA)):
        with urlopen(schema_url, timeout=30) as response:
            schema = json.load(response)
        Draft202012Validator.check_schema(schema)
        document = json.loads((root / filename).read_text())
        if filename == "mcp.json":
            document["mcpServers"]["zynd"].pop("extensions")
        Draft202012Validator(schema).validate(document)


def build(output, root=ROOT, submission=False, mcp_url=MCP_URL, review_origin=REVIEW_ORIGIN):
    require(safe_url(mcp_url) and urlsplit(mcp_url).path == "/chatgpt/mcp", "MCP URL must be HTTPS with path /chatgpt/mcp")
    require(safe_url(review_origin) and urlsplit(review_origin).path == "", "review origin must be an HTTPS origin without a path")
    require(not submission or (mcp_url == MCP_URL and review_origin == REVIEW_ORIGIN),
            "submission cannot use test targets")
    names = validate(root, submission)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.is_relative_to(root.resolve()), "write the generated ZIP outside the plugin folder")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            content = (root / name).read_bytes()
            if name.endswith((".json", ".md", ".yaml")):
                content = content.decode().replace(MCP_URL, mcp_url).replace(REVIEW_ORIGIN, review_origin).encode()
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="ZIP output path (outside services/chatgpt-plugin/package)")
    parser.add_argument("--submission", action="store_true", help="fail closed until submission prerequisites are verified")
    parser.add_argument("--mcp-url", default=MCP_URL, help="explicit isolated HTTPS /mcp target for draft ZIPs")
    parser.add_argument("--review-origin", default=REVIEW_ORIGIN, help="trusted HTTPS review origin for draft ZIPs")
    parser.add_argument("--official-schemas", action="store_true", help="fetch current schemas; requires jsonschema; validate portable projection and OAuth independently")
    args = parser.parse_args()
    try:
        require(args.output or (args.mcp_url == MCP_URL and args.review_origin == REVIEW_ORIGIN),
                "test targets require --output")
        if args.official_schemas:
            validate_official_schemas()
            print("Official plugin schema and portable MCP projection passed; OpenAI OAuth extension checked separately (schema mismatch remains).")
        if args.output:
            print(build(args.output, submission=args.submission, mcp_url=args.mcp_url, review_origin=args.review_origin))
        else:
            print(f"Validated {len(validate(submission=args.submission))} package files; no ZIP written")
        if args.submission:
            print("Portal steps still required: reviewer account, executed cases, domain verification, live OAuth/tool scan.")
    except ValueError as exc:
        parser.exit(1, f"Package invalid: {exc}\n")
