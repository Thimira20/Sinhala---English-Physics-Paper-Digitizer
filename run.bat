@echo off
chcp 65001 >nul
title Sinhala & English Physics Paper Digitizer

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Running setup.bat first...
    call "%~dp0setup.bat"
)

echo Starting Sinhala ^& English Physics Paper Digitizer...
call "%~dp0.venv\Scripts\activate.bat"
python "%~dp0main.py"
pause
