#!/usr/bin/env sh
set -e
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
uvicorn app.main:app --reload
