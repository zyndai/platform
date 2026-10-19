"""Canonical names for technologies, so one thing is stored (and shown) once.

"JS", "javascript" and "JavaScript" are one skill; "Python 3.12" is "Python"; Docker
is a product you use while React is a framework you know. Pure helpers, no DB.

The alias map is only meant for tech-flavoured predicates (see
``taxonomy.TECH_NAME_PREDICATES``). It needs an *exact* hit on the whole name, never a
substring: "Taylor Swift" stays "Taylor Swift" and a project called "Next" is left
alone because callers only canonicalize tech predicates.
"""
from __future__ import annotations

import re
from typing import Literal

TechKind = Literal["language", "framework", "product"]

LANGUAGES: frozenset[str] = frozenset({
    "JavaScript", "TypeScript", "Python", "Go", "Rust", "Java", "Kotlin", "Swift",
    "C", "C++", "C#", "Ruby", "PHP", "Scala", "Elixir", "Erlang", "Haskell", "Clojure",
    "Dart", "R", "Julia", "Lua", "Perl", "Objective-C", "Solidity", "SQL", "Zig",
    "OCaml", "F#", "Groovy", "MATLAB", "Fortran", "COBOL", "Assembly", "WebAssembly",
    "Nim", "Crystal", "Elm", "Vyper", "Move", "HTML", "CSS", "Bash", "GraphQL",
})

FRAMEWORKS: frozenset[str] = frozenset({
    "React", "Next.js", "Vue", "Nuxt", "Angular", "AngularJS", "Svelte", "SvelteKit",
    "SolidJS", "Astro", "Remix", "Node.js", "Deno", "Bun", "Express", "NestJS", "Fastify",
    "Django", "Django REST Framework", "Flask", "FastAPI", "Ruby on Rails", "Laravel",
    "Spring", "Spring Boot", "ASP.NET", ".NET", "TensorFlow", "PyTorch", "Keras",
    "scikit-learn", "Pandas", "NumPy", "LangChain", "LlamaIndex", "Tailwind CSS",
    "Bootstrap", "jQuery", "Redux", "React Native", "Flutter", "Expo", "Electron",
    "Tauri", "SwiftUI", "Jetpack Compose", "Hugging Face", "tRPC", "Prisma", "Drizzle",
    "SQLAlchemy", "Pydantic", "Gin", "Phoenix", "Hono", "Three.js", "D3.js",
})

PRODUCTS: frozenset[str] = frozenset({
    "Docker", "Docker Compose", "Kubernetes", "Terraform", "Ansible", "AWS", "Google Cloud",
    "Azure", "Vercel", "Netlify", "Supabase", "Firebase", "PostgreSQL", "MySQL", "MongoDB",
    "Redis", "SQLite", "Elasticsearch", "Kafka", "RabbitMQ", "Git", "GitHub", "GitLab",
    "Figma", "Notion", "Slack", "Linear", "Jira", "Cursor", "VS Code", "Windsurf",
    "Claude Code", "Claude", "Codex", "GitHub Copilot", "ChatGPT", "Gemini", "OpenAI",
    "Postman", "Jenkins", "GitHub Actions", "CircleCI", "Datadog", "Grafana", "Prometheus",
    "Sentry", "Stripe", "Cloudflare", "Nginx", "Linux", "Webflow", "Shopify", "WordPress",
    "Airtable", "Zapier", "Playwright", "Selenium", "Jest", "Pytest", "Vite", "Webpack",
    "npm", "pnpm", "Yarn", "pip", "uv", "Poetry", "Cargo", "Homebrew", "Neovim", "Vim",
    "Xcode", "Visual Studio", "Android Studio", "IntelliJ", "PyCharm", "Composio", "Opencode", "Cline",
})

# lowercase surface form -> canonical display name. Display names themselves are folded
# in below, so only genuine variants need listing here.
ALIASES: dict[str, str] = {
    # languages
    "js": "JavaScript", "ecmascript": "JavaScript", "es6": "JavaScript",
    "es2015": "JavaScript", "es2020": "JavaScript", "vanilla js": "JavaScript",
    "ts": "TypeScript",
    "py": "Python", "python3": "Python", "python 3": "Python",
    "golang": "Go", "go lang": "Go",
    "rustlang": "Rust",
    "cpp": "C++", "c plus plus": "C++", "cplusplus": "C++",
    "csharp": "C#", "c sharp": "C#",
    "objective c": "Objective-C", "objc": "Objective-C", "obj-c": "Objective-C",
    "fsharp": "F#", "f sharp": "F#",
    "wasm": "WebAssembly",
    "shell scripting": "Bash", "bash scripting": "Bash",
    "html5": "HTML", "css3": "CSS",
    "structured query language": "SQL",
    # frameworks / runtimes
    "node": "Node.js", "nodejs": "Node.js", "node js": "Node.js",
    "nextjs": "Next.js", "next": "Next.js", "next js": "Next.js",
    "react.js": "React", "reactjs": "React", "react js": "React",
    "vue.js": "Vue", "vuejs": "Vue", "vue js": "Vue",
    "nuxt.js": "Nuxt", "nuxtjs": "Nuxt",
    "angular.js": "AngularJS", "angularjs": "AngularJS",
    "svelte kit": "SvelteKit",
    "solid.js": "SolidJS", "solidjs": "SolidJS",
    "express.js": "Express", "expressjs": "Express",
    "nest.js": "NestJS",
    "fast api": "FastAPI",
    "drf": "Django REST Framework", "django rest": "Django REST Framework",
    "rails": "Ruby on Rails", "ror": "Ruby on Rails", "ruby on rails": "Ruby on Rails",
    "springboot": "Spring Boot", "spring framework": "Spring",
    "dotnet": ".NET", "dot net": ".NET", "net core": ".NET", ".net core": ".NET",
    "aspnet": "ASP.NET", "asp.net core": "ASP.NET",
    "tensor flow": "TensorFlow",
    "torch": "PyTorch", "py torch": "PyTorch",
    "sklearn": "scikit-learn", "scikit learn": "scikit-learn", "scikitlearn": "scikit-learn",
    "lang chain": "LangChain", "llama index": "LlamaIndex", "llama-index": "LlamaIndex",
    "tailwind": "Tailwind CSS", "tailwindcss": "Tailwind CSS", "tailwind css": "Tailwind CSS",
    "threejs": "Three.js", "d3js": "D3.js",
    "swift ui": "SwiftUI",
    "hf": "Hugging Face", "huggingface": "Hugging Face", "hugging face": "Hugging Face",
    "huggingface transformers": "Hugging Face",
    # products
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "psql": "PostgreSQL",
    "pg": "PostgreSQL", "postgre": "PostgreSQL",
    "mongo": "MongoDB", "mongo db": "MongoDB",
    "sqlite3": "SQLite", "sql lite": "SQLite",
    "elastic search": "Elasticsearch",
    "k8s": "Kubernetes", "kube": "Kubernetes",
    "gcp": "Google Cloud", "google cloud platform": "Google Cloud",
    "gcloud": "Google Cloud",
    "git hub": "GitHub", "git lab": "GitLab", "circle ci": "CircleCI",
    "open code": "Opencode", "word press": "WordPress", "web pack": "Webpack",
    "py.test": "Pytest",
    "react-native": "React Native",
    "amazon web services": "AWS", "amazon aws": "AWS",
    "microsoft azure": "Azure",
    "docker-compose": "Docker Compose", "docker compose": "Docker Compose",
    "vscode": "VS Code", "vs code": "VS Code", "visual studio code": "VS Code",
    "claude-code": "Claude Code", "claudecode": "Claude Code",
    "claude in chrome": "Claude in Chrome",
    "copilot": "GitHub Copilot", "github copilot": "GitHub Copilot",
    "gh actions": "GitHub Actions", "github action": "GitHub Actions",
    "open ai": "OpenAI", "open-ai": "OpenAI",
    "chat gpt": "ChatGPT", "chat-gpt": "ChatGPT",
}

_KIND_BY_NAME: dict[str, TechKind] = {}
_DISPLAY_BY_KEY: dict[str, str] = {}

for _names, _kind in ((LANGUAGES, "language"), (FRAMEWORKS, "framework"), (PRODUCTS, "product")):
    for _name in _names:
        _KIND_BY_NAME[_name.lower()] = _kind  # type: ignore[assignment]
        _DISPLAY_BY_KEY[_name.lower()] = _name

for _alias, _display in ALIASES.items():
    _DISPLAY_BY_KEY[_alias] = _display

_WHITESPACE = re.compile(r"\s+")
# "Python 3.12", "React 18", "Node.js v20.11", "Python3.11", "Go 1.22", "Angular 17.x".
_VERSION_SUFFIX = re.compile(r"^(?P<base>.*?[a-z+#.\-])\s*v?\d+(?:\.\d+)*(?:\.x)?$", re.IGNORECASE)
# "Python programming language", "Rust language", "Django framework".
_DESCRIPTOR_SUFFIX = re.compile(
    r"\s+(?:programming language|language|lang|framework|library|runtime|sdk)$", re.IGNORECASE
)


def _fold(value: str) -> str:
    """Trim, drop wrapping quotes/backticks, collapse internal whitespace."""
    text = (value or "").strip().strip("\"'`")
    return _WHITESPACE.sub(" ", text).strip()


def _lookup(key: str) -> str | None:
    return _DISPLAY_BY_KEY.get(key.lower())


def canonical_name(value: str) -> str:
    """The one display name for a technology, or the cleaned input if we don't know it.

    Never invents: an unknown name keeps the user's own casing. Versions and trailing
    descriptors are only stripped when what remains is a known technology, so
    "Phase 2" and "Web3" are left alone.
    """
    text = _fold(value)
    if not text:
        return ""
    hit = _lookup(text)
    if hit:
        return hit

    stripped = _DESCRIPTOR_SUFFIX.sub("", text).strip()
    if stripped != text:
        hit = _lookup(stripped)
        if hit:
            return hit

    for candidate in (text, stripped):
        match = _VERSION_SUFFIX.match(candidate)
        if match:
            hit = _lookup(match.group("base").strip().rstrip("-").strip())
            if hit:
                return hit
    return text


def tech_kind(name: str) -> TechKind | None:
    """language | framework | product for a recognised technology, else None.

    Exact match on the canonical name only. A substring or fuzzy hit would make
    "Taylor Swift" a language.
    """
    text = _fold(name)
    if not text:
        return None
    display = canonical_name(text)
    return _KIND_BY_NAME.get(display.lower())


def is_known_tech(name: str) -> bool:
    return tech_kind(name) is not None


def dedupe_key(name: str) -> str:
    """Case- and alias-insensitive identity of a name, for collapsing duplicates."""
    return canonical_name(name).lower()
