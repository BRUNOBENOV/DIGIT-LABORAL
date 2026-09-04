from __future__ import annotations

import os
from pathlib import Path

QA_DB = Path('/tmp/digit_laboral_persona_qa.db')
QA_PASSWORD = 'Persona-QA-Only-2026!'
try:
    QA_DB.unlink()
except FileNotFoundError:
    pass

os.environ['ENVIRONMENT'] = 'development'
os.environ['DATABASE_URL'] = f'sqlite:///{QA_DB}'
os.environ['MIGRATION_DATABASE_URL'] = f'sqlite:///{QA_DB}'
os.environ['DEMO_ADMIN_PASSWORD'] = QA_PASSWORD
os.environ['SECURE_COOKIES'] = 'false'
os.environ['CSRF_ENABLED'] = 'false'
os.environ['RLS_ENABLED'] = 'false'
os.environ['AI_ENABLED'] = 'false'
os.environ['STORAGE_BACKEND'] = 'local'
os.environ['LOCAL_STORAGE_PATH'] = '/tmp/digit_laboral_persona_uploads'

CHECKS = 0
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)
        if len(FAILURES) >= 20:
            raise RuntimeError('QA abortado: ' + ' | '.join(FAILURES))


def run() -> None:
    from .persona_qa_rules import run_rule_stress
    from .persona_qa_http import run_http_personas
    run_rule_stress(check)
    run_http_personas(check, QA_PASSWORD)
    if FAILURES:
        raise RuntimeError(f'PERSONA_QA_FAILED checks={CHECKS} failures={len(FAILURES)} :: ' + ' | '.join(FAILURES))
    print(f'PERSONA_QA_OK checks={CHECKS} personas=4')


if __name__ == '__main__':
    try:
        run()
    finally:
        try:
            QA_DB.unlink()
        except FileNotFoundError:
            pass
