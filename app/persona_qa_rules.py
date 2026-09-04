from __future__ import annotations

import io
from datetime import date

from PIL import Image

from .document_export import DOCUMENT_LABELS, build_document_body, number_to_words_es
from .labor_rules import aguinaldo_amount, completed_years, months_of_service, notice_amount, preaviso_days, vacation_amount, vacation_entitlement_days
from .main import smart_normalize_logo


def _image_bytes(fmt: str, size: tuple[int, int], index: int) -> bytes:
    mode = 'RGBA' if fmt == 'PNG' else 'RGB'
    fill = (30 + index % 170, 70, 150, 255) if mode == 'RGBA' else (30 + index % 170, 70, 150)
    image = Image.new(mode, size, fill)
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def run_rule_stress(check) -> None:  # noqa: ANN001
    as_of = date(2026, 12, 31)
    for year in range(1985, 2027):
        for month in range(1, 13):
            for day in (1, 14, 28):
                admission = date(year, month, day)
                years = completed_years(admission, as_of)
                expected_years = max(0, 2026 - year)
                check(years == expected_years, f'antigüedad {admission}: {years}/{expected_years}')
                months = months_of_service(admission, as_of)
                check(months >= years * 12, f'meses inconsistentes {admission}')
                vacation = vacation_entitlement_days(admission, as_of)
                expected_vacation = 0 if years < 1 else (12 if years <= 5 else (18 if years <= 10 else 30))
                check(vacation.value == expected_vacation, f'vacaciones art.218 {admission}: {vacation.value}/{expected_vacation}')
                if admission <= as_of:
                    notice = preaviso_days(admission, as_of)
                    expected_notice = 30 if months <= 12 else (45 if months <= 60 else (60 if months <= 120 else 90))
                    check(notice.value == expected_notice, f'preaviso art.87 {admission}: {notice.value}/{expected_notice}')

    for total in range(0, 120_000_001, 113_777):
        result = aguinaldo_amount(total)
        check(result.value == round(total / 12), f'aguinaldo 1/12 {total}')
        check(result.value >= 0, f'aguinaldo negativo {total}')

    for salary in (0, 1_500_000, 3_044_000, 3_500_000, 7_250_000, 15_000_000):
        for minimum in (0, 3_044_000):
            for days in (0, 1, 6, 12, 18, 30):
                result = vacation_amount(salary, minimum, days)
                expected = round(max(salary, minimum) / 30 * days)
                check(result.value == expected, f'vacaciones importe {salary}/{minimum}/{days}')
                check(result.value >= 0, 'vacaciones importe negativo')

    for average in range(0, 20_000_001, 137_000):
        for days in (0, 30, 45, 60, 90):
            result = notice_amount(average, days)
            check(result.value == round(average / 30 * days), f'preaviso importe {average}/{days}')

    for number in range(0, 3000):
        check(bool(number_to_words_es(number)), f'número a letras vacío {number}')

    index = 0
    for fmt in ('PNG', 'JPEG', 'WEBP'):
        for size in ((48, 48), (300, 80), (80, 300), (1200, 400), (2400, 600), (640, 640)):
            for _ in range(4):
                normalized, content_type = smart_normalize_logo(_image_bytes(fmt, size, index))
                with Image.open(io.BytesIO(normalized)) as output:
                    check(output.size == (1100, 360), f'logo tamaño {fmt}/{size}: {output.size}')
                    check(output.format == 'PNG', f'logo formato {output.format}')
                check(content_type == 'image/png', f'logo MIME {content_type}')
                index += 1

    metadata = {'period_start': '2026-01-01', 'period_end': '2026-12-31', 'effective_date': '2026-09-30', 'leave_start': '2026-10-01', 'leave_end': '2026-10-12', 'amount': 3_500_000, 'recipient': 'Recursos Humanos', 'nationality': 'paraguaya', 'civil_status': 'soltero', 'notes': 'QA'}
    for repeat in range(8):
        for document_type in DOCUMENT_LABELS:
            title, body = build_document_body(document_type, company_name='Empresa QA S.A.', employee_name='Persona QA', employee_document='1234567', position='Analista', admission_date=date(2022, 1, 10), salary=3_500_000 + repeat, issue_date=date(2026, 9, 4), city='Ciudad del Este', metadata=metadata)
            check(bool(title), f'documento sin título {document_type}')
            check(len(body) > 30, f'documento corto {document_type}')
