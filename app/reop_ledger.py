"""Use the gross written to REOP's 32-column workbook and complete portal listings."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

MONTH = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])")
PATRONAL = re.compile(r"[0-9]{1,20}")
LABELS = {"multiple": "Revisar duplicados", "different": "Importe diferente", "awaiting": "Importada, falta verificar en el listado", "missing": "Falta cargar",
          "extra": "Solo en REOP", "unchecked": "Sin verificar", "same": "Ya coincide"}
STAGES = {"prepare": "Falta preparar", "ready": "Lista para importar",
          "imported": "Importada, falta verificar", "confirmed": "Confirmada en REOP"}


def doc_key(value):
    return re.sub(r"[.\s]", "", str(value or "")).upper()


def gross_income(row):
    amounts = row[9:24]
    if len(amounts) == 15 and all(type(x) is int and x >= 0 for x in amounts):
        return sum(amounts)
    return None


def checked_snapshot(value, patronal, period):
    if (not isinstance(value, dict) or value.get("source") != "REOP" or value.get("complete") is not True
            or value.get("patronal") != patronal or value.get("period") != period
            or not MONTH.fullmatch(period) or not PATRONAL.fullmatch(patronal)):
        raise ValueError("La consulta debe corresponder a la patronal y al período seleccionados.")
    total, inspected, records = value.get("total"), value.get("inspected"), value.get("records")
    if (type(total) is not int or type(inspected) is not int or inspected != total or not 0 <= total <= 100000
            or not isinstance(records, list) or len(records) > min(10000, total)):
        raise ValueError("Faltan páginas del listado de REOP.")
    seen, result = set(), []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Registro de REOP inválido.")
        if not isinstance(item.get("document"), str) or not isinstance(item.get("number"), str):
            raise ValueError("Falta identificar la cédula o el número de liquidación en REOP.")
        doc, number = doc_key(item["document"]), item["number"]
        income, status, receipt = item.get("income"), item.get("status"), item.get("receipt", "")
        if (item.get("patronal") != patronal or item.get("period") != period
                or not re.fullmatch(r"[A-Z0-9-]{2,40}", doc) or not re.fullmatch(r"[0-9]{1,24}", number)
                or number in seen or type(income) is not int or not 0 <= income <= 10**15
                or not isinstance(status, str) or not 0 < len(status.strip()) <= 80
                or not isinstance(receipt, str) or len(receipt) > 100):
            raise ValueError("La lectura contiene una liquidación incompleta, repetida o de otro período.")
        seen.add(number)
        result.append(dict(document=doc, number=number, income=income, status=status.strip(), receipt=receipt))
    result.sort(key=lambda r: r["number"])
    fingerprint = hashlib.sha256(json.dumps([patronal, period, result], sort_keys=True).encode()).hexdigest()
    return {"records": result, "digest": fingerprint, "checked_at": datetime.now(UTC).isoformat(), "total": total}


def compare_ledger(rows, snapshots, *, include_extras=True, submitted=()):
    local, remote = defaultdict(list), defaultdict(list)
    for row in rows:
        local[str(row[0] or ""), doc_key(row[1])].append(gross_income(row))
    for patronal, snapshot in snapshots.items():
        for item in snapshot["records"]:
            remote[patronal, item["document"]].append(item)
    output, counts = [], Counter()
    keys = local.keys() | remote.keys() if include_extras else local.keys()
    for patronal, document in keys:
        amounts, records = local.get((patronal, document), []), remote.get((patronal, document), [])
        digit = amounts[0] if len(amounts) == 1 else None
        official = records[0]["income"] if len(records) == 1 else None
        if len(amounts) > 1 or len(records) > 1:
            state = "multiple"
        elif not amounts:
            state = "extra"
        elif patronal not in snapshots or digit is None:
            state = "unchecked"
        elif not records and ((patronal, document) in submitted or ("*", document) in submitted or ("*", "*") in submitted):
            state = "awaiting"
        elif not records:
            state = "missing"
        else:
            state = "same" if digit == official else "different"
        confirmed = state == "same" and records[0]["status"].casefold() in {"confirmado", "confirmada"}
        counts[state] += 1
        counts["confirmed"] += int(confirmed)
        output.append(dict(patronal=patronal, document=document, digit=digit, official=official, records=records,
                           difference=official - digit if digit is not None and official is not None else None,
                           state=state, label=LABELS[state], confirmed=confirmed))
    output.sort(key=lambda r: (list(LABELS).index(r["state"]), r["confirmed"], r["document"]))
    by_patronal = Counter(r["patronal"] for r in output if r["state"] == "missing")
    return {"rows": output, "counts": counts, "missing_by_patronal": by_patronal,
            "all_confirmed": bool(output) and len(output) == counts["confirmed"]}


def select_delivery(rows, snapshots, only_missing, digest, *, submitted=(), missing_patronal=""):
    if missing_patronal:
        if not only_missing:
            raise ValueError("Elegí el lote de faltantes para preparar esta patronal.")
        rows = [row for row in rows if str(row[0]) == missing_patronal]
    patrons = {str(row[0]) for row in rows}
    snapshot = snapshots.get(next(iter(patrons))) if len(patrons) == 1 else None
    if not snapshot or digest != snapshot["digest"]:
        raise ValueError("Actualizá el control de duplicados antes de preparar la carga.")
    age = datetime.now(UTC) - datetime.fromisoformat(snapshot["checked_at"])
    if not timedelta(0) <= age <= timedelta(minutes=10):
        raise ValueError("El control de duplicados venció. Volvé a consultar REOP.")
    comparison = compare_ledger(rows, snapshots, include_extras=False, submitted=submitted)
    missing = {r["document"] for r in comparison["rows"] if r["state"] == "missing"}
    if not missing:
        raise ValueError("No hay filas faltantes para enviar. Revisá la conciliación.")
    if not only_missing and len(missing) != len(rows):
        raise ValueError("Hay registros existentes o diferencias. Revisá la conciliación y prepará solo los faltantes.")
    return [row for row in rows if doc_key(row[1]) in missing]
