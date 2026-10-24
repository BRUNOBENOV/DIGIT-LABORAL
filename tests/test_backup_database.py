from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile

from scripts import backup_database


class MemoryStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


def test_sqlite_backup_contains_storage_objects_hashes_and_manifest(monkeypatch, tmp_path):
    database = tmp_path / "digit_laboral.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE backup_smoke (value TEXT)")
        connection.execute("INSERT INTO backup_smoke(value) VALUES ('ok')")
        connection.commit()

    data = tmp_path / "data"
    uploads = data / "uploads" / "legacy"
    uploads.mkdir(parents=True)
    (uploads / "legacy.txt").write_text("legacy upload", encoding="utf-8")

    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(backup_database, "DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(backup_database, "DATA", data)
    monkeypatch.setattr(backup_database, "BACKUPS", backups)
    monkeypatch.setattr(backup_database, "STAMP", "20990101T000000Z")

    object_bytes = {
        "documents/1/contracts/contract.pdf": b"%PDF-test-contract",
        "requests/2/attachments/photo.png": b"\x89PNG\r\n\x1a\nbody",
        "integrations/3/batches/reop.xlsx": b"ooxml-test-batch",
        "system-backups/old.zip": b"do not include previous backup",
        "documents/../outside.secret": b"unsafe-key-must-not-be-written",
    }
    fake_storage = MemoryStorage(object_bytes)
    monkeypatch.setattr("app.storage_service.storage", fake_storage)

    result = backup_database.backup_sqlite()
    assert result.is_file()
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "database/digit_laboral.db" in names
        assert "uploads/legacy/legacy.txt" in names
        assert "objects/documents/1/contracts/contract.pdf" in names
        assert "objects/requests/2/attachments/photo.png" in names
        assert "objects/integrations/3/batches/reop.xlsx" in names
        assert "objects/system-backups/old.zip" not in names
        assert not any("../" in name or name.startswith("/") for name in names)
        assert archive.read("objects/documents/1/contracts/contract.pdf") == object_bytes["documents/1/contracts/contract.pdf"]

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "system-backup-v2"
        assert manifest["database"]["type"] == "sqlite"
        assert manifest["database"]["sha256"] == hashlib.sha256(database.read_bytes()).hexdigest()
        assert manifest["application_storage"]["count"] == 3
        assert manifest["application_storage"]["unsafe_keys_skipped"] == ["documents/../outside.secret"]
        stored = next(x for x in manifest["application_storage"]["objects"] if x["key"] == "documents/1/contracts/contract.pdf")
        assert stored["sha256"] == hashlib.sha256(object_bytes["documents/1/contracts/contract.pdf"]).hexdigest()
        assert manifest["legacy_uploads"]["count"] == 1


def test_system_backup_excludes_backup_prefix_to_prevent_recursive_growth():
    assert backup_database._safe_storage_key("system-backups/old.zip") is None
    assert backup_database._safe_storage_key("documents/../private.txt") is None
    assert backup_database._safe_storage_key("/documents/absolute.txt") is None
    assert backup_database._safe_storage_key("documents/valid/file.pdf") == "documents/valid/file.pdf"
