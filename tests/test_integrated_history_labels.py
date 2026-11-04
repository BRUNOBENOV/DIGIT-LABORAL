"""Los historiales se presentan como registros DIGIT sin perder procedencia técnica."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VIEWS = [
    "vacations.html",
    "vacation_detail.html",
    "legacy_vacation_detail.html",
    "legacy_vacation_import.html",
    "legacy_notice_list.html",
    "legacy_notice_detail.html",
    "legacy_notice_import.html",
    "legacy_notice_exceptions.html",
]


def test_no_software_anterior_in_user_facing_vacaciones_and_preavisos():
    for filename in VIEWS:
        html = (ROOT / "app/templates" / filename).read_text(encoding="utf-8")
        assert not re.search(r"\bDOS\b", html), filename
        assert "sistema anterior" not in html.lower(), filename
        assert "LSVAC" not in html, filename
        assert "LSPRE" not in html, filename


def test_vacation_history_is_integrated_but_unreconciled_balances_are_explicit():
    page = (ROOT / "app/templates/vacations.html").read_text(encoding="utf-8")
    detail = (ROOT / "app/templates/legacy_vacation_detail.html").read_text(encoding="utf-8")
    operational = (ROOT / "app/templates/vacation_detail.html").read_text(encoding="utf-8")
    assert "Registros históricos" in page
    assert "Registro histórico" in page
    assert "DIGIT-LABORAL" in page
    assert "Sin conciliar" in page
    assert "Exportar historial · CSV" in page
    assert "no incluye movimientos operativos recientes" in page
    assert "Movimiento conservado en el historial de DIGIT-LABORAL" in detail
    assert "no modifican automáticamente los saldos ni las liquidaciones" in detail
    assert "Sin conciliar" in operational
    # No se eliminó ni transformó el origen técnico del expediente.
    assert "source.source_hash" in detail
    assert "source.source_filename" in detail
    assert "source.legacy_key" in detail


def test_notice_history_remains_auditable_without_old_system_branding():
    page = (ROOT / "app/templates/legacy_notice_detail.html").read_text(encoding="utf-8")
    assert "DIGIT-LABORAL · HISTORIAL DE PREAVISOS" in page
    assert "Sin conciliación documental" in page
    assert "source.source_hash" in page
    assert "BORRAD=S" in page
