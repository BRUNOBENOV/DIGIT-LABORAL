from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(parents=True, exist_ok=True)
STAMP = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db")


def zip_supporting_files(archive: zipfile.ZipFile) -> None:
    uploads = DATA / "uploads"
    if uploads.exists():
        for path in uploads.rglob("*"):
            if path.is_file():
                archive.write(path, f"uploads/{path.relative_to(uploads)}")


def backup_sqlite() -> Path:
    raw = DATABASE_URL.removeprefix("sqlite:///")
    source = Path(raw)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        raise FileNotFoundError(f"No se encontró la base SQLite: {source}")
    destination = BACKUPS / f"digit-laboral-{STAMP}.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "database/digit_laboral.db")
        zip_supporting_files(archive)
    return destination


def backup_postgres() -> Path:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump no está instalado en este entorno.")
    dump_path = BACKUPS / f"digit-laboral-{STAMP}.dump"
    subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--file", str(dump_path), DATABASE_URL],
        check=True,
        timeout=60 * 30,
    )
    destination = BACKUPS / f"digit-laboral-{STAMP}.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(dump_path, f"database/{dump_path.name}")
        manifest = (
            f"created_at={datetime.now(UTC).isoformat()}\n"
            f"database=postgresql\n"
            "restore=pg_restore --clean --if-exists --no-owner --dbname=$DATABASE_URL archivo.dump\n"
        )
        archive.writestr("manifest.txt", manifest)
        zip_supporting_files(archive)
    dump_path.unlink(missing_ok=True)
    return destination


def upload_backup(path: Path) -> str:
    from app.storage_service import storage

    key = f"system-backups/{path.name}"
    storage.put(key, path.read_bytes(), "application/zip")
    return key


def prune_local_backups(keep: int) -> None:
    files = sorted(BACKUPS.glob("digit-laboral-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in files[max(keep, 1):]:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera un respaldo verificable de Digit Laboral.")
    parser.add_argument("--upload", action="store_true", help="Sube el ZIP al almacenamiento configurado.")
    parser.add_argument("--keep-local", type=int, default=7, help="Cantidad de respaldos locales a conservar.")
    args = parser.parse_args()
    try:
        path = backup_sqlite() if DATABASE_URL.startswith("sqlite") else backup_postgres()
        uploaded = upload_backup(path) if args.upload else ""
        prune_local_backups(args.keep_local)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(path)
    if uploaded:
        print(f"uploaded={uploaded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
