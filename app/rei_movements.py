"""Prepare a REI movement CSV using the layout supplied by the employer."""
from __future__ import annotations

import csv
import io
from codecs import BOM_UTF8
from dataclasses import dataclass
from datetime import date

from .models import Company, ComplianceEvent

MANUAL_REI_MOVEMENTS = "https://portal.ips.gov.py/sistemas/ipsportal/archivos/archivos/1535374763.pdf#page=54"
MOVEMENT_BATCH_TYPE = "Movimientos REI (CSV)"
MOVEMENT_TYPES = ("Entrada", "Salida")
MAX_TEMPLATE_BYTES = 32_768
MAX_MOVEMENTS = 100
DELIMITERS = {"semicolon": ";", "comma": ",", "tab": "\t"}
DATE_FORMATS = {"dma": "%d/%m/%Y", "amd": "%Y-%m-%d", "dma-guion": "%d-%m-%Y", "compacta": "%Y%m%d"}
MOVEMENT_FIELDS = {
    "document": "Documento del funcionario",
    "document_compact": "Documento sin puntos, espacios ni guiones",
    "event_date": "Fecha del movimiento",
    "patronal": "Número patronal IPS",
    "ruc": "RUC de la empresa",
    "name": "Nombre completo",
    "admission_date": "Fecha de ingreso del legajo",
    "birth_date": "Fecha de nacimiento",
    "fixed": "Valor común indicado por el IPS",
    "empty": "Dejar vacío si el modelo lo admite",
}


@dataclass(frozen=True)
class ReiCsvLayout:
    columns: list[str]
    header: str
    delimiter: str
    encoding: str
    newline: str

    @property
    def media_type(self) -> str:
        return "text/csv; charset=windows-1252" if self.encoding == "cp1252" else "text/csv; charset=utf-8"


def _valid_cell(value: str) -> bool:
    return not any(ord(char) < 32 or ord(char) == 127 for char in value) and not value.lstrip().startswith(
        ("=", "+", "-", "@")
    )


def read_rei_csv_layout(content: bytes, separator: str, encoding: str, first_row: str) -> ReiCsvLayout:
    if separator not in DELIMITERS or encoding not in {"utf-8", "cp1252"} or first_row not in {"header", "sample"}:
        raise ValueError("Elegí el separador, la codificación y el tipo de primera fila del modelo.")
    if not content or len(content) > MAX_TEMPLATE_BYTES:
        raise ValueError("El modelo CSV debe contener una fila y pesar como máximo 32 KB.")
    if content.startswith(BOM_UTF8):
        if encoding != "utf-8":
            raise ValueError("El modelo está identificado como UTF-8. Seleccioná esa codificación.")
        encoding = "utf-8-sig"
    delimiter = DELIMITERS[separator]
    try:
        text = content.decode(encoding)
        raw_line = io.StringIO(text, newline="").readline()
        header = raw_line.rstrip("\r\n")
        values = next(csv.reader([header], delimiter=delimiter, strict=True))
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise ValueError("No se pudo leer la primera fila. Revisá el separador y la codificación del CSV.") from exc
    if not 2 <= len(values) <= 64:
        raise ValueError("La primera fila debe tener de 2 a 64 columnas. Revisá el separador seleccionado.")
    if first_row == "sample":
        # The sample supplies structure only. Its values never enter the export or the session.
        columns = [f"Columna {index}" for index in range(1, len(values) + 1)]
        header = ""
    else:
        if any(len(value) > 120 or not _valid_cell(value) for value in values):
            raise ValueError("La cabecera contiene campos inválidos. Usá un CSV con solo los encabezados del modelo.")
        columns = [value.strip() or f"Columna {index}" for index, value in enumerate(values, 1)]
    line_end = raw_line[len(raw_line.rstrip("\r\n")):] or "\r\n"
    return ReiCsvLayout(columns=columns, header=header, delimiter=delimiter, encoding=encoding, newline=line_end)


def build_rei_movement_csv(
    company: Company,
    events: list[ComplianceEvent],
    layout: ReiCsvLayout,
    fields: list[str],
    constants: list[str],
    patronal: str,
    date_format: str,
) -> tuple[bytes, list[list[str]]]:
    if len(fields) != len(layout.columns) or len(constants) != len(fields) or any(
        field not in MOVEMENT_FIELDS for field in fields
    ):
        raise ValueError("Indicá qué dato va en cada columna del modelo.")
    if fields.count("document") + fields.count("document_compact") != 1 or fields.count("event_date") != 1:
        raise ValueError("Asigná exactamente una columna al documento y una a la fecha del movimiento.")
    if date_format not in DATE_FORMATS:
        raise ValueError("Seleccioná el formato de fecha que indica el modelo del IPS.")

    def format_date(value: date | None) -> str:
        return value.strftime(DATE_FORMATS[date_format]) if value else ""

    rows = []
    for event in events:
        employee = event.employee
        document = (employee.document_number or "").strip()
        values = {
            "document": document,
            "document_compact": document.translate(str.maketrans("", "", ". -")),
            "event_date": format_date(event.event_date),
            "patronal": patronal,
            "ruc": company.ruc,
            "name": employee.full_name,
            "admission_date": format_date(employee.admission_date),
            "birth_date": format_date(employee.birth_date),
        }
        row = []
        for index, (field, constant) in enumerate(zip(fields, constants, strict=True)):
            value = constant if field == "fixed" else (values.get(field) or "").strip()
            if field != "empty" and (not value or len(value) > 220 or not _valid_cell(value)):
                raise ValueError(f"Comunicación #{event.id}, columna {index + 1}. Revisá el dato asignado.")
            row.append(value)
        rows.append(row)

    output = io.StringIO(newline="")
    if layout.header:
        output.write(layout.header + layout.newline)
    csv.writer(output, delimiter=layout.delimiter, lineterminator=layout.newline).writerows(rows)
    try:
        return output.getvalue().encode(layout.encoding), rows
    except UnicodeEncodeError as exc:
        raise ValueError("Hay caracteres que la codificación del modelo no admite. Revisá la codificación y los datos.") from exc
