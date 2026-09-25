"""
Pytest config — adds `backend/` to sys.path so the tests can import
modules like `mcp.tools.brief` and `api.telegram` exactly the way the
running backend does, and silences a couple of noisy loggers.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Set a placeholder token so any code path that checks for emptiness
# (e.g. `if not TELEGRAM_BOT_TOKEN: log warning`) doesn't spam.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "TEST_TOKEN")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
