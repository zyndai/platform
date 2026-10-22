"""Check the Claude plugin bundle in package/ and stage test copies of it (stdlib only).

    python3 services/claude-plugin/bundle.py
    python3 services/claude-plugin/bundle.py --output dist/zynd-claude-plugin.zip
    python3 services/claude-plugin/bundle.py --stage /tmp/zynd-dev \
        --mcp-url https://dev.api.zynd.ai/claude/mcp --review-origin https://dev.cards.zynd.ai

package/ is what Anthropic's directory reads from GitHub, so it holds only the plugin: no tooling,
no tests. The checks here are ours (consent wording, least privilege, one endpoint); Anthropic's own
are `claude plugin validate --profile directory --strict services/claude-plugin/package`.
"""

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent / "package"
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
MCP_URL = "https://api.zynd.ai/claude/mcp"
REVIEW_ORIGIN = "https://cards.zynd.ai"
REPOSITORY = "https://github.com/zyndai/platform"
MANIFEST_KEYS = {
    "name", "displayName", "version", "description", "author", "homepage", "repository", "license",
    "keywords", "icon", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl",
}
LISTING_URLS = ("homepage", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl")
FILES = {".claude-plugin/plugin.json", ".mcp.json", "LICENSE", "README.md", "assets/zynd-logo.png",
         *(f"skills/{skill}/SKILL.md" for skill in SKILLS)}
TEXT_SUFFIXES = (".json", ".md")
# Anthropic's checklist: non-image files under 256 KiB, at most 512 files.
MAX_TEXT_BYTES, MAX_FILES = 256 * 1024, 512


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and
            not parsed.password and not parsed.query and not parsed.fragment)


def on_origin(value, origin):
    return safe_url(value) and (value == origin or value.startswith(origin + "/"))


def files(root):
    found = set()
    for item in root.rglob("*"):
        rel = item.relative_to(root).as_posix()
        require(not item.is_symlink(), f"symlink forbidden: {rel}")
        if item.is_file():
            require(rel in FILES, f"unexpected package file: {rel}")
            found.add(rel)
    require(found == FILES, f"missing package files: {sorted(FILES - found)}")
    require(len(found) <= MAX_FILES, "too many files")
    for name in found:
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, f"unsafe path: {name}")
    return sorted(found)


def front_matter(body):
    match = re.match(r"---\n(.*?)\n---\n", body, re.S)
    require(match, "missing front matter")
    pairs = [line.split(": ", 1) for line in match.group(1).splitlines()]
    require(all(len(pair) == 2 for pair in pairs), "front matter must be single-line `key: value` pairs")
    return dict(pairs)


def validate(root=ROOT):
    names = files(root)
    for name in names:
        if name.endswith(TEXT_SUFFIXES) or name == "LICENSE":
            require((root / name).stat().st_size <= MAX_TEXT_BYTES, f"{name} is over 256 KiB")

    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
    # An allowlist of keys: no hooks, commands, agents, mcpServers, userConfig or other lifecycle hooks.
    require(set(plugin) == MANIFEST_KEYS, f"manifest keys differ: {sorted(set(plugin) ^ MANIFEST_KEYS)}")
    require(plugin["name"] == "zynd" and plugin["displayName"] == "Zynd" and
            re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"]), "invalid plugin identity")
    require(plugin["license"] == "MIT" and "MIT License" in (root / "LICENSE").read_text(),
            "license must be MIT, with its text in LICENSE")
    require(plugin["repository"] == REPOSITORY, "repository must be the public monorepo")
    require(set(plugin["author"]) == {"name", "url"} and on_origin(plugin["author"]["url"], REVIEW_ORIGIN),
            "author must be a name and a URL on the review origin")
    for key in LISTING_URLS:
        require(on_origin(plugin[key], REVIEW_ORIGIN), f"{key} must be a plain HTTPS URL on {REVIEW_ORIGIN}")
    require(re.search(r"(?i)\bdraft (?:contract|\d)|not yet verified|unverified|not for public",
                      plugin["description"]) is None, "description must not call the plugin a draft")

    mcp = json.loads((root / ".mcp.json").read_text())
    # One server, no headers/env/oauth block: the plugin ships no credential and no client id,
    # because Claude registers itself with the authorization server.
    require(mcp == {"mcpServers": {"zynd": {"type": "http", "url": MCP_URL}}}, "invalid MCP configuration")

    require(plugin["icon"] == "./assets/zynd-logo.png", "missing icon reference")
    image = (root / "assets/zynd-logo.png").read_bytes()
    width, height = int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big")
    require(image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) <= 5 * 1024 * 1024 and
            width == height and 48 <= width <= 4096, "icon must be a valid-size square PNG")
    require(len((root / "README.md").read_text().split()) >= 40, "README needs at least 40 words")

    for skill in SKILLS:
        body = (root / f"skills/{skill}/SKILL.md").read_text()
        meta = front_matter(body)
        require(set(meta) == {"name", "description"} and meta["name"] == skill and meta["description"],
                f"invalid skill header: {skill}")
        referenced = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", body))
        require(referenced == SKILL_TOOLS[skill],
                f"unavailable tool or missing expected tool in {skill}: {referenced ^ SKILL_TOOLS[skill]}")

    text = "\n".join((root / name).read_text() for name in names if name.endswith(TEXT_SUFFIXES))
    require(not re.search(r"(?i)(authorization\s*[:=]|bearer\s+\S+|client_?secret|api[_-]?key\s*[:=]|"
                          r"-----BEGIN .*PRIVATE KEY-----)", text), "possible credential in package")
    allowed_hosts = {urlsplit(REVIEW_ORIGIN).hostname, urlsplit(MCP_URL).hostname, urlsplit(REPOSITORY).hostname}
    for url in re.findall(r"https?://[^\s)>\"'`]+", text):
        url = url.rstrip(".,;:")  # sentence punctuation is not part of the URL
        require(urlsplit(url).hostname in allowed_hosts, f"URL outside Zynd and its repository: {url}")
    require(MCP_URL in text, "missing endpoint")
    return names


def check_targets(mcp_url, review_origin):
    require(safe_url(mcp_url) and urlsplit(mcp_url).path == "/claude/mcp", "MCP URL must be HTTPS with path /claude/mcp")
    require(safe_url(review_origin) and urlsplit(review_origin).path == "", "review origin must be an HTTPS origin without a path")


def render(root, name, mcp_url, review_origin):
    """One package file's bytes, aimed at the given environment."""
    if name.endswith(TEXT_SUFFIXES) or name == "LICENSE":
        return (root / name).read_text().replace(MCP_URL, mcp_url).replace(REVIEW_ORIGIN, review_origin).encode()
    return (root / name).read_bytes()


def stage(output, root=ROOT, mcp_url=MCP_URL, review_origin=REVIEW_ORIGIN):
    """Write a copy of the package aimed at another environment, for `claude --plugin-dir`.

    Never edits package/. The copy is for testing only, so it is not re-validated against the
    production URLs it deliberately replaces."""
    check_targets(mcp_url, review_origin)
    names = validate(root)
    output = Path(output).resolve()
    require(not output.is_relative_to(root.resolve()) and not root.resolve().is_relative_to(output),
            "stage outside the package folder")
    require(not output.exists() or not any(output.iterdir()), "stage into an empty directory")
    for name in names:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render(root, name, mcp_url, review_origin))
    return output


def build(output, root=ROOT, mcp_url=MCP_URL, review_origin=REVIEW_ORIGIN):
    """Zip the package for claude.ai's "Upload a plugin" (Customize > Plugins), manifest at the zip root.

    Reproducible: fixed timestamps and modes, files in sorted order. Nothing is written if validation fails."""
    check_targets(mcp_url, review_origin)
    names = validate(root)
    output = Path(output).resolve()
    require(not output.is_relative_to(root.resolve()), "write the ZIP outside the package folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, render(root, name, mcp_url, review_origin), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", help="ZIP file to write (outside package/), for claude.ai's Upload a plugin")
    parser.add_argument("--stage", help="empty directory to write a test copy into")
    parser.add_argument("--mcp-url", default=MCP_URL, help="HTTPS /claude/mcp URL for the test copy or ZIP")
    parser.add_argument("--review-origin", default=REVIEW_ORIGIN, help="HTTPS review origin for the test copy or ZIP")
    args = parser.parse_args()
    try:
        require(not (args.output and args.stage), "choose --output or --stage, not both")
        if args.output:
            print(build(args.output, mcp_url=args.mcp_url, review_origin=args.review_origin))
        elif args.stage:
            print(stage(args.stage, mcp_url=args.mcp_url, review_origin=args.review_origin))
        else:
            print(f"Validated {len(validate())} package files")
    except ValueError as exc:
        parser.exit(1, f"Package invalid: {exc}\n")
