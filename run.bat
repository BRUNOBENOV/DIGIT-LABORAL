@echo off
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist data mkdir data
uvicorn app.main:app --reload
