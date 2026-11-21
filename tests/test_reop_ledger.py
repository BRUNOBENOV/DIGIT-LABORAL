from datetime import UTC, datetime, timedelta

import pytest

from app.reop_ledger import checked_snapshot, compare_ledger, select_delivery

PATRONAL, PERIOD = "123456", "2026-10"


def row(number):
    result = [0] * 32
    result[0:2] = [PATRONAL, str(10000 + number)]
    result[9], result[10], result[23], result[25] = 1000, 250, 30, 90
    return result


def communication(worker, **updates):
    return dict({"document": str(10000 + worker), "number": str(400 + worker), "income": 1280,
                 "status": "Confirmado", "receipt": "", "period": PERIOD, "patronal": PATRONAL}, **updates)


def observed(records):
    return {"source": "REOP", "period": PERIOD, "patronal": PATRONAL, "complete": True,
            "inspected": 20, "total": 20, "records": records}


def test_partial_workbook_only_includes_two_genuinely_missing_documents():
    rows = [row(i) for i in range(7)]
    records = [communication(i) for i in range(5)]
    snapshot = checked_snapshot(observed(records), PATRONAL, PERIOD)
    snapshots = {PATRONAL: snapshot}
    result = compare_ledger(rows, snapshots)
    assert result["counts"] == {"same": 5, "confirmed": 5, "missing": 2}
    assert not result["all_confirmed"]
    with pytest.raises(ValueError, match="solo los faltantes"):
        select_delivery(rows, snapshots, False, snapshot["digest"])
    assert select_delivery(rows, snapshots, True, snapshot["digest"]) == rows[5:]
    with pytest.raises(ValueError):
        select_delivery(rows, snapshots, True, "outdated")
    snapshot["checked_at"] = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    with pytest.raises(ValueError, match="venció"):
        select_delivery(rows, snapshots, True, snapshot["digest"])


def test_difference_pending_duplicates_extra_and_incomplete_are_never_confirmed():
    rows = [row(i) for i in range(4)]
    records = [communication(0, income=1000, receipt="015/01"), communication(1, status="Pendiente"),
               communication(2), communication(2, number="999"), communication(3), communication(9)]
    snapshots = {PATRONAL: checked_snapshot(observed(records), PATRONAL, PERIOD)}
    result = compare_ledger(rows, snapshots)
    by_ci = {r["document"]: r for r in result["rows"]}
    assert by_ci["10000"]["difference"] == -280 and by_ci["10000"]["records"][0]["receipt"] == "015/01"
    assert by_ci["10001"]["state"] == "same" and not by_ci["10001"]["confirmed"]
    assert by_ci["10002"]["state"] == "multiple" and by_ci["10002"]["difference"] is None
    assert by_ci["10009"]["state"] == "extra" and not result["all_confirmed"]
    assert compare_ledger([row(3)], snapshots, include_extras=False)["all_confirmed"]
    assert compare_ledger(rows, {})["counts"]["unchecked"] == 4
    with pytest.raises(ValueError, match="No hay filas"):
        select_delivery(rows, snapshots, True, snapshots[PATRONAL]["digest"])


def test_same_identity_in_two_patronales_keeps_separate_workbooks():
    first = row(1)
    other = ["000777", *first[1:]]
    known = checked_snapshot(observed([communication(1)]), PATRONAL, PERIOD)
    empty = checked_snapshot({**observed([]), "patronal": other[0]}, other[0], PERIOD)
    snapshots = {PATRONAL: known, other[0]: empty}
    assert compare_ledger([first, other], snapshots)["missing_by_patronal"] == {other[0]: 1}
    assert select_delivery([first, other], snapshots, True, empty["digest"], missing_patronal=other[0]) == [other]


@pytest.mark.parametrize("change", [
    {"complete": False}, {"inspected": 19}, {"patronal": "000001"}, {"period": "2026-09"},
    {"records": [communication(1), communication(2, number="401")]},
    {"records": [communication(1, patronal="000001")]}, {"records": [communication(1, income=None)]},
])
def test_partial_foreign_or_inconsistent_evidence_is_rejected(change):
    with pytest.raises(ValueError):
        checked_snapshot({**observed([]), **change}, PATRONAL, PERIOD)
