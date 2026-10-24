from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app import backup_service
from app.database import SessionLocal
from app.models import Company, ComplianceEvent, IntegrationBatch, IntegrationBatchItem, Studio


class MemoryStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def exists(self, key: str) -> bool:
        return key in self.objects

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream"):
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def test_study_backup_includes_rei_reop_records_and_stored_artifacts(monkeypatch, tmp_path):
    marker = uuid.uuid4().hex[:12]
    batch_bytes = b"workbook-bytes-for-backup-test"
    receipt_bytes = b"%PDF-1.4\nbackup receipt test\n"
    batch_key = f"integrations/backup-test/{marker}.xlsx"
    receipt_key = f"integrations/backup-test/{marker}.pdf"
    fake_storage = MemoryStorage({batch_key: batch_bytes, receipt_key: receipt_bytes})
    monkeypatch.setattr(backup_service, "storage", fake_storage)

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        studio = db.get(Studio, company.studio_id)
        assert studio is not None

        batch = IntegrationBatch(
            studio_id=studio.id,
            company_id=company.id,
            authority="REOP",
            batch_type="Prueba anual",
            period="2098",
            status="Presentado",
            file_name="../unsafe-export.xlsx",
            storage_key=batch_key,
            file_sha256="a" * 64,
            item_count=1,
            external_reference=f"QA-{marker}",
            created_by="backup-test",
        )
        db.add(batch)
        db.flush()

        event = ComplianceEvent(
            company_id=company.id,
            batch_id=batch.id,
            authority="REOP",
            event_type="Entrada",
            event_date=__import__("datetime").date.today(),
            status="Presentado",
            source_key=f"backup-test-{marker}",
            payload_json="{}",
            external_reference=f"QA-{marker}",
            receipt_storage_key=receipt_key,
            notes="=1+1",
            created_by="backup-test",
        )
        db.add(event)
        db.flush()
        item = IntegrationBatchItem(
            batch_id=batch.id,
            compliance_event_id=event.id,
            status="Incluido",
            response_message="=1+1",
        )
        db.add(item)
        db.commit()
        batch_id, event_id, item_id, studio_id = batch.id, event.id, item.id, studio.id

        try:
            payload = backup_service.build_studio_export(db, studio, tmp_path)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["schema"] == "studio-export-v2"
                assert manifest["counts"]["compliance_events"] >= 1
                assert manifest["counts"]["integration_batches"] >= 1
                assert manifest["counts"]["integration_batch_items"] >= 1
                assert f"archivos/integraciones/{company.id}/lotes/{batch_id}_unsafe-export.xlsx" in names
                assert f"archivos/integraciones/{company.id}/comprobantes/comprobante-lote-{batch_id}_{marker}.pdf" in names
                assert archive.read(f"archivos/integraciones/{company.id}/lotes/{batch_id}_unsafe-export.xlsx") == batch_bytes
                assert archive.read(f"archivos/integraciones/{company.id}/comprobantes/comprobante-lote-{batch_id}_{marker}.pdf") == receipt_bytes
                assert not any(name.startswith("/") or "../" in name or "\\\\" in name for name in names)

                compliance_rows = list(csv.reader(io.StringIO(
                    archive.read("datos/comunicaciones_cumplimiento.csv").decode("utf-8-sig")
                )))
                exported_event = next(row for row in compliance_rows[1:] if row[0] == str(event_id))
                assert exported_event[14] == "'=1+1"

                batch_items_rows = list(csv.reader(io.StringIO(
                    archive.read("datos/lotes_integracion_items.csv").decode("utf-8-sig")
                )))
                exported_item = next(row for row in batch_items_rows[1:] if row[0] == str(item_id))
                assert exported_item[4] == "'=1+1"
        finally:
            item_db = db.get(IntegrationBatchItem, item_id)
            event_db = db.get(ComplianceEvent, event_id)
            batch_db = db.get(IntegrationBatch, batch_id)
            if item_db is not None:
                db.delete(item_db)
            if event_db is not None:
                db.delete(event_db)
            if batch_db is not None:
                db.delete(batch_db)
            db.commit()
