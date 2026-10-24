from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

EMPLOYEE_HEADERS = [
    "nombre_completo",
    "cedula",
    "cargo",
    "fecha_ingreso",
    "salario_base",
    "fecha_nacimiento",
    "tipo_contrato",
    "frecuencia_pago",
    "aporta_ips",
    "correo",
    "telefono",
    "direccion",
    "observaciones",
]

REQUIRED_HEADERS = {"nombre_completo", "cedula", "cargo", "fecha_ingreso", "salario_base"}


@dataclass
class ImportRow:
    row_number: int
    data: dict[str, Any]
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class ImportPreview:
    company_id: int
    studio_id: int
    user_id: int
    created_at: str
    filename: str
    rows: list[ImportRow]

    @property
    def valid_count(self) -> int:
        return sum(item.valid for item in self.rows)

    @property
    def invalid_count(self) -> int:
        return len(self.rows) - self.valid_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "studio_id": self.studio_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "filename": self.filename,
            "rows": [asdict(row) for row in self.rows],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImportPreview":
        return cls(
            company_id=int(payload["company_id"]),
            studio_id=int(payload["studio_id"]),
            user_id=int(payload["user_id"]),
            created_at=str(payload["created_at"]),
            filename=str(payload.get("filename", "archivo")),
            rows=[ImportRow(**row) for row in payload.get("rows", [])],
        )


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[áàäâ]", "a", text)
    text = re.sub(r"[éèëê]", "e", text)
    text = re.sub(r"[íìïî]", "i", text)
    text = re.sub(r"[óòöô]", "o", text)
    text = re.sub(r"[úùüû]", "u", text)
    text = text.replace("ñ", "n")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_document_number(value: Any) -> str:
    """Normalize cédula formatting without removing meaningful hyphens."""
    return re.sub(r"[.\s]+", "", str(value or "").strip())


def parse_money(value: Any) -> int | None:
    """Parse integer Guaraní amounts without silently converting invalid values to zero."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return None
        return int(value)
    text = str(value).strip()
    if not text or text.startswith("-") or "(" in text or ")" in text:
        return None
    text = re.sub(r"(?i)^gs\.?\s*", "", text).replace("₲", "").replace("$", "")
    text = re.sub(r"\s+", "", text)
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:[.,]\d{3})+)", text):
        return None
    return int(re.sub(r"[.,]", "", text))


def parse_bool(value: Any, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    normalized = normalize_header(value)
    if normalized in {"si", "s", "1", "true", "verdadero", "x", "aporta", "si_aporta"}:
        return True
    if normalized in {"no", "n", "0", "false", "falso", "no_aporta", "no_aporta_ips"}:
        return False
    return default


def _rows_from_xlsx(content: bytes) -> tuple[list[str], list[list[Any]]]:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    try:
        headers = [normalize_header(value) for value in next(iterator)]
    except StopIteration:
        return [], []
    return headers, [list(row) for row in iterator]


def _rows_from_csv(content: bytes) -> tuple[list[str], list[list[Any]]]:
    decoded = content.decode("utf-8-sig", errors="replace")
    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.reader(io.StringIO(decoded), dialect)
    try:
        headers = [normalize_header(value) for value in next(reader)]
    except StopIteration:
        return [], []
    return headers, [list(row) for row in reader]


def parse_employee_import(content: bytes, filename: str, max_rows: int = 2000) -> list[ImportRow]:
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        headers, raw_rows = _rows_from_xlsx(content)
    elif lower.endswith(".csv"):
        headers, raw_rows = _rows_from_csv(content)
    else:
        raise ValueError("El archivo debe ser .xlsx o .csv")

    header_counts: dict[str, int] = {}
    for header in headers:
        if header:
            header_counts[header] = header_counts.get(header, 0) + 1
    duplicate_headers = sorted(header for header, count in header_counts.items() if count > 1)
    if duplicate_headers:
        raise ValueError("Hay columnas repetidas en la plantilla: " + ", ".join(duplicate_headers))
    missing = REQUIRED_HEADERS.difference(headers)
    if missing:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(sorted(missing)))
    if len(raw_rows) > max_rows:
        raise ValueError(f"El archivo supera el máximo permitido de {max_rows} filas.")

    parsed: list[ImportRow] = []
    seen_documents: dict[str, int] = {}
    true_ips_values = {"si", "s", "1", "true", "verdadero", "x", "aporta", "si_aporta"}
    false_ips_values = {"no", "n", "0", "false", "falso", "no_aporta", "no_aporta_ips"}
    for index, values in enumerate(raw_rows, start=2):
        mapping = {headers[pos]: values[pos] if pos < len(values) else None for pos in range(len(headers))}
        if not any(value not in (None, "") for value in mapping.values()):
            continue
        errors: list[str] = []
        warnings: list[str] = []
        name = str(mapping.get("nombre_completo") or "").strip()
        document = normalize_document_number(mapping.get("cedula"))
        position = str(mapping.get("cargo") or "").strip()
        admission = parse_date(mapping.get("fecha_ingreso"))
        salary = parse_money(mapping.get("salario_base"))
        raw_birth = mapping.get("fecha_nacimiento")
        birth = parse_date(raw_birth)
        email = str(mapping.get("correo") or "").strip().lower()
        raw_ips = str(mapping.get("aporta_ips") or "").strip()
        normalized_ips = normalize_header(raw_ips)

        if not name:
            errors.append("Falta el nombre completo.")
        if not document:
            errors.append("Falta la cédula.")
        elif document in seen_documents:
            errors.append(f"La cédula ya aparece en la fila {seen_documents[document]} del archivo.")
        else:
            seen_documents[document] = index
        if len(document) > 40:
            errors.append("La cédula supera el máximo de 40 caracteres.")
        if not position:
            errors.append("Falta el cargo.")
        if len(position) > 140:
            errors.append("El cargo supera el máximo de 140 caracteres.")
        if not admission:
            errors.append("La fecha de ingreso no es válida.")
        if salary is None:
            errors.append("El salario base no es válido.")
        if raw_birth not in (None, "") and birth is None:
            errors.append("La fecha de nacimiento no es válida.")
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            warnings.append("El correo parece incompleto.")
        if raw_ips and normalized_ips not in true_ips_values | false_ips_values:
            warnings.append("El valor de aporta_ips no se reconoce; se usará Sí por defecto.")
        if birth and admission and birth >= admission:
            errors.append("La fecha de nacimiento debe ser anterior a la fecha de ingreso.")

        data = {
            "full_name": name,
            "document_number": document,
            "position": position,
            "admission_date": admission.isoformat() if admission else "",
            "base_salary": salary or 0,
            "birth_date": birth.isoformat() if birth else "",
            "contract_type": str(mapping.get("tipo_contrato") or "Tiempo indefinido").strip(),
            "payment_frequency": str(mapping.get("frecuencia_pago") or "Mensual").strip(),
            "ips_contributor": parse_bool(raw_ips, default=True),
            "email": email,
            "phone": str(mapping.get("telefono") or "").strip(),
            "address": str(mapping.get("direccion") or "").strip(),
            "notes": str(mapping.get("observaciones") or "").strip(),
        }
        parsed.append(ImportRow(index, data, errors, warnings))
    return parsed

def build_employee_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Funcionarios"
    sheet.append(EMPLOYEE_HEADERS)
    sheet.append([
        "Juan Pérez",
        "4567890",
        "Auxiliar administrativo",
        "2026-08-01",
        3044000,
        "2000-05-15",
        "Tiempo indefinido",
        "Mensual",
        "Sí",
        "juan@empresa.com.py",
        "0981000000",
        "Ciudad del Este",
        "Fila de ejemplo: eliminá o reemplazá antes de importar",
    ])
    header_fill = PatternFill("solid", fgColor="173B86")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    widths = [28, 16, 24, 17, 17, 18, 23, 20, 14, 28, 18, 32, 42]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    guide = workbook.create_sheet("Guía")
    guide.append(["Columna", "Obligatoria", "Ejemplo / regla"])
    guide_rows = [
        ("nombre_completo", "Sí", "Nombre y apellido"),
        ("cedula", "Sí", "Sin puntos; el sistema conserva guiones"),
        ("cargo", "Sí", "Cargo actual"),
        ("fecha_ingreso", "Sí", "AAAA-MM-DD o DD/MM/AAAA"),
        ("salario_base", "Sí", "Solo número; sin Gs."),
        ("fecha_nacimiento", "No", "AAAA-MM-DD o DD/MM/AAAA"),
        ("aporta_ips", "No", "Sí/No; por defecto Sí"),
    ]
    for row in guide_rows:
        guide.append(row)
    for cell in guide[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
    guide.column_dimensions["A"].width = 26
    guide.column_dimensions["B"].width = 16
    guide.column_dimensions["C"].width = 48
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def save_preview(directory: Path, token: str, preview: ImportPreview) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{token}.json"
    path.write_text(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_preview(directory: Path, token: str, max_age_hours: int = 4) -> ImportPreview:
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("Token de importación inválido.")
    path = directory / f"{token}.json"
    if not path.exists():
        raise FileNotFoundError("La vista previa ya no está disponible.")
    preview = ImportPreview.from_dict(json.loads(path.read_text(encoding="utf-8")))
    created = datetime.fromisoformat(preview.created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if created < datetime.now(UTC) - timedelta(hours=max_age_hours):
        path.unlink(missing_ok=True)
        raise ValueError("La vista previa expiró. Volvé a subir el archivo.")
    return preview
