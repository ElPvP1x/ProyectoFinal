@echo off
title Sistema Contable - Auditor CFDI 4.0
cd /d "%~dp0"
if not exist ".venv" (
    echo Creando entorno virtual...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
start "" http://127.0.0.1:5000
python app.py
pause
