import pytest

from app.services.canonical import (
    ALIASES, FRAMEWORKS, LANGUAGES, PRODUCTS, canonical_name, dedupe_key, is_known_tech, tech_kind,
)


@pytest.mark.parametrize("raw,expected", [
    ("js", "JavaScript"), ("JS", "JavaScript"), ("javascript", "JavaScript"),
    ("ts", "TypeScript"), ("py", "Python"), ("python3", "Python"), ("golang", "Go"),
    ("postgres", "PostgreSQL"), ("psql", "PostgreSQL"), ("PostgreSQL", "PostgreSQL"),
    ("nextjs", "Next.js"), ("next.js", "Next.js"), ("next", "Next.js"),
    ("node", "Node.js"), ("nodejs", "Node.js"), ("node.js", "Node.js"),
    ("reactjs", "React"), ("react.js", "React"), ("k8s", "Kubernetes"), ("gcp", "Google Cloud"),
    ("c++", "C++"), ("cpp", "C++"), ("csharp", "C#"), ("vscode", "VS Code"),
    ("tailwind", "Tailwind CSS"), ("sklearn", "scikit-learn"),
])
def test_aliases_resolve_to_one_display_name(raw, expected):
    assert canonical_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Python 3.12", "Python"), ("python3.11", "Python"), ("React 18", "React"),
    ("Node.js v20.11", "Node.js"), ("Go 1.22", "Go"), ("Java 17", "Java"),
    ("Vue 3", "Vue"), ("Angular 17.x", "Angular"), ("C++17", "C++"), (".NET 8", ".NET"),
    ("Next.js 14", "Next.js"), ("PostgreSQL 16", "PostgreSQL"),
    ("Python programming language", "Python"), ("Rust language", "Rust"),
])
def test_versions_and_descriptors_are_stripped_for_known_tech(raw, expected):
    assert canonical_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "Phase 2", "Web3", "Taylor Swift", "go to market", "machine learning", "Q4 2026 plan",
    "Series A", "Project Apollo 11", "S3", "EC2",
])
def test_unknown_names_are_left_alone(raw):
    assert canonical_name(raw) == raw


def test_unknown_names_keep_the_users_casing_and_get_trimmed():
    assert canonical_name("  'Acme   Billing' ") == "Acme Billing"
    assert canonical_name("") == ""
    assert canonical_name(None) == ""


def test_tech_kind_classifies_language_framework_product():
    assert tech_kind("js") == "language"
    assert tech_kind("Rust") == "language"
    assert tech_kind("react") == "framework"
    assert tech_kind("Next.js 14") == "framework"
    assert tech_kind("Docker") == "product"
    assert tech_kind("docker compose") == "product"
    assert tech_kind("Supabase") == "product"
    assert tech_kind("Figma") == "product"


def test_tech_kind_needs_an_exact_hit_not_a_substring():
    # The risk called out in the plan: "Go" the game, "Swift" vs "Taylor Swift".
    assert tech_kind("Taylor Swift") is None
    assert tech_kind("Rustic bakery") is None
    assert tech_kind("go to market strategy") is None
    assert tech_kind("Reactor design") is None
    assert tech_kind("") is None


def test_is_known_tech_and_dedupe_key():
    assert is_known_tech("k8s") and not is_known_tech("sourdough")
    assert dedupe_key("JS") == dedupe_key("javascript") == dedupe_key("JavaScript 6")  # noqa: PLR2004
    assert dedupe_key("Docker") != dedupe_key("Kubernetes")


def test_every_alias_target_and_set_member_is_its_own_canonical_form():
    # canonical_name must be idempotent on everything it can produce.
    for target in set(ALIASES.values()) | LANGUAGES | FRAMEWORKS | PRODUCTS:
        assert canonical_name(target) == target, target


def test_the_three_kind_sets_do_not_overlap():
    assert not (LANGUAGES & FRAMEWORKS) and not (LANGUAGES & PRODUCTS) and not (FRAMEWORKS & PRODUCTS)
