from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DEMO_ADMIN_PASSWORD", "demo123")
os.environ.setdefault("DEMO_SUPERADMIN_PASSWORD", "Digit2026!")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
