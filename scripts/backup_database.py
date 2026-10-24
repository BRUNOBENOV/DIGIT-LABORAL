from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
BACKUPS = ROOT / "backups"
BACKUPS.mkdir(parents=True, exist_ok=True)
STAMP = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/digit_laboral.db")
STORAGE_PREFIXES = ("documents/", "requests/", "integrations/")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_storage_key(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if normalized.startswith("system-backups/"):
        return None
    if not any(normalized.startswith(prefix) for prefix in STORAGE_PREFIXES):
        return None
    return normalized


def zip_supporting_files(archive: zipfile.ZipFile) -> list[dict[str, object]]:
    uploads = DATA / "uploads"
    metadata: list[dict[str, object]] = []
    if not uploads.exists():
        return metadata
    root = uploads.resolve()
    for path in uploads.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            raise RuntimeError(f"Archivo de carga apunta fuera del directorio permitido: {path}")
        relative = path.relative_to(uploads).as_posix()
        archive_name = f"uploads/{relative}"
        content = path.read_bytes()
        archive.writestr(archive_name, content)
        metadata.append({
            "archive_path": archive_name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    return metadata


def zip_storage_objects(archive: zipfile.ZipFile) -> tuple[list[dict[str, object]], list[str]]:
    from app.storage_service import storage

    objects: list[dict[str, object]] = []
    skipped_unsafe: list[str] = []
    seen: set[str] = set()
    for prefix in STORAGE_PREFIXES:
        for raw_key in storage.list_keys(prefix):
            key = _safe_storage_key(raw_key)
            if key is None:
                skipped_unsafe.append(str(raw_key))
                continue
            if key in seen:
                continue
            content = storage.get(key)
            archive_path = f"objects/{key}"
            archive.writestr(archive_path, content)
            objects.append({
                "key": key,
                "archive_path": archive_path,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })
            seen.add(key)
    return objects, skipped_unsafe


def write_manifest(
    archive: zipfile.ZipFile,
    *,
    database_type: str,
    database_archive_path: str,
    database_size: int,
    database_sha256: str,
    local_uploads: list[dict[str, object]],
    storage_objects: list[dict[str, object]],
    skipped_unsafe_storage_keys: list[str],
    restore_command: str,
) -> None:
    archive.writestr(
        "manifest.json",
        json.dumps(
            {
                "product": "Digit Laboral",
                "schema": "system-backup-v2",
                "created_at": datetime.now(UTC).isoformat(),
                "database": {
                    "type": database_type,
                    "archive_path": database_archive_path,
                    "size": database_size,
                    "sha256": database_sha256,
                    "restore_command": restore_command,
                },
                "legacy_uploads": {
                    "count": len(local_uploads),
                    "files": local_uploads,
                },
                "application_storage": {
                    "prefixes": list(STORAGE_PREFIXES),
                    "count": len(storage_objects),
                    "objects": storage_objects,
                    "unsafe_keys_skipped": skipped_unsafe_storage_keys,
                },
                "note": (
                    "Los objetos bajo documents/, requests/ e integrations/ se incluyen en el ZIP. "
                    "El prefijo system-backups/ se excluye intencionalmente para evitar respaldar "
                    "recursivamente los ZIP de respaldo."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"El ZIP generado no superó la comprobación CRC: {corrupt}")


def backup_sqlite() -> Path:
    raw = DATABASE_URL.removeprefix("sqlite:///")
    source = Path(raw)
    if not source.is_absolute():
        source = ROOT / source
    if not source.is_file():
        raise FileNotFoundError(f"No se encontró la base SQLite: {source}")
    destination = BACKUPS / f"digit-laboral-{STAMP}.zip"
    database_archive_path = "database/digit_laboral.db"
    try:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, database_archive_path)
            local_uploads = zip_supporting_files(archive)
            storage_objects, skipped_unsafe = zip_storage_objects(archive)
            write_manifest(
                archive,
                database_type="sqlite",
                database_archive_path=database_archive_path,
                database_size=source.stat().st_size,
                database_sha256=_file_sha256(source),
                local_uploads=local_uploads,
                storage_objects=storage_objects,
                skipped_unsafe_storage_keys=skipped_unsafe,
                restore_command="Detené la aplicación y reemplazá la base SQLite por database/digit_laboral.db después de verificar el respaldo.",
            )
        _verify_zip(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def pg_dump_database_url(url: str) -> str:
    """Convert common provider/SQLAlchemy PostgreSQL URLs to a libpq-compatible URL."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+") and "://" in url:
        return "postgresql://" + url.split("://", 1)[1]
    return url


def backup_postgres() -> Path:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump no está instalado en este entorno.")
    dump_path = BACKUPS / f"digit-laboral-{STAMP}.dump"
    destination = BACKUPS / f"digit-laboral-{STAMP}.zip"
    try:
        subprocess.run(
            [pg_dump, "--format=custom", "--no-owner", "--file", str(dump_path), pg_dump_database_url(DATABASE_URL)],
            check=True,
            timeout=60 * 30,
        )
        database_archive_path = f"database/{dump_path.name}"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(dump_path, database_archive_path)
            local_uploads = zip_supporting_files(archive)
            storage_objects, skipped_unsafe = zip_storage_objects(archive)
            write_manifest(
                archive,
                database_type="postgresql",
                database_archive_path=database_archive_path,
                database_size=dump_path.stat().st_size,
                database_sha256=_file_sha256(dump_path),
                local_uploads=local_uploads,
                storage_objects=storage_objects,
                skipped_unsafe_storage_keys=skipped_unsafe,
                restore_command=f"pg_restore --clean --if-exists --no-owner --dbname=$DATABASE_URL {dump_path.name}",
            )
        _verify_zip(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
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
