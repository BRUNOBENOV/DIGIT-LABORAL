"""Distribute the local Chrome assistant with the salary export screen."""
from __future__ import annotations

import io
import json
import re
import zipfile
from base64 import b64decode
from hashlib import sha256
from pathlib import Path

EXTENSION_DIR = Path(__file__).with_name("reop_browser_extension")
_MANIFEST = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
REOP_ASSISTANT_ID = sha256(b64decode(_MANIFEST["key"])).hexdigest()[:32].translate(
    str.maketrans("0123456789abcdef", "abcdefghijklmnop")
)
REOP_ASSISTANT_MAX_BYTES = 5 * 1024 * 1024


def reop_assistant_patronal(rows: list[list]) -> str:
    patronales = {str(row[0]) for row in rows}
    if len(patronales) == 1:
        patronal = next(iter(patronales))
        if re.fullmatch(r"[0-9]{1,20}", patronal):
            return patronal
    return ""


def reop_assistant_review(rows: list[list], exclusions: list[dict], source_type: str) -> str:
    """Identify the reviewed data independently of workbook ZIP timestamps."""
    excluded = sorted((item["calculation_id"], item["status"]) for item in exclusions)
    content = json.dumps([source_type, rows, excluded], ensure_ascii=False, default=str, separators=(",", ":"))
    return sha256(content.encode("utf-8")).hexdigest()


def build_reop_assistant_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "worker.js", "portal.js"):
            archive.write(EXTENSION_DIR / name, f"digit-laboral-reop/{name}")
    return output.getvalue()
