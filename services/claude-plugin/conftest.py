import os
import sys
from pathlib import Path

os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("DATABASE_URL", "postgresql://zynd:zynd@localhost:5433/zynd_test")
os.environ.setdefault("ENABLE_DEV_BEARER", "true")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789-0123456789")

ROOT = Path(__file__).resolve().parent
MEMORY = ROOT.parent / "memory"
for path in (str(ROOT), str(ROOT.parent / "chatgpt-plugin"), str(MEMORY), str(MEMORY / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)
os.chdir(MEMORY)
