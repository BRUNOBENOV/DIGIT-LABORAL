"""La procedencia técnica no debe contaminar la presentación habitual de liquidaciones."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_settlement_workbench_has_no_recurring_migration_panel():
    view = (ROOT / "app/templates/labor_workbench.html").read_text(encoding="utf-8")
    assert "Incorporar liquidaciones del sistema anterior" not in view
    assert "/app/import/legacy-liquidations/preview" not in view
    assert "antecedentes LIQ del mismo historial" not in view
    assert "Las liquidaciones LIQ ya migradas" not in view
    assert 'id="labor-history"' in view


def test_settlement_projection_displays_canonical_label_and_preserves_audit_metadata():
    module = (ROOT / "app/unified_labor_history.py").read_text(encoding="utf-8")
    assert 'label="Liquidación final",' in module
    assert 'label="Liquidación final · LIQ"' not in module
    assert '". Motivo de egreso: " +' in module
    # El origen conserva identificadores técnicos para auditoría, sin exponer sufijos al usuario.
    assert 'origin="imported", id=event.id' in module
    assert 'source=source, days=None' in module
    assert 'can_use_document=False' in module
