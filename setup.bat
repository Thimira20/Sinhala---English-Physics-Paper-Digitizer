@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Sinhala & English Physics Paper Digitizer - Setup

echo ========================================================
echo Sinhala ^& English Physics Paper Digitizer - Setup
echo ========================================================
echo.

cd /d "%~dp0"

REM 1. Create virtual environment (.venv)
if not exist ".venv\Scripts\python.exe" (
    echo [1/7] Creating Python virtual environment in .venv...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 (
        py -3.11 -m venv .venv 2>nul
        if errorlevel 1 (
            py -3 -m venv .venv 2>nul
            if errorlevel 1 (
                python -m venv .venv
                if errorlevel 1 (
                    echo ERROR: Failed to create virtual environment. Ensure Python 3.11+ is installed.
                    pause
                    exit /b 1
                )
            )
        )
    )
    echo Virtual environment created successfully.
) else (
    echo [1/7] Existing virtual environment found in .venv.
)

REM 2. Install Python dependencies
echo.
echo [2/7] Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: Failed to install requirements.
    pause
    exit /b 1
)

REM 3. Fetch vendored JS & CSS libraries
echo.
echo [3/7] Fetching vendored frontend libraries...
".venv\Scripts\python.exe" "%~dp0tools\fetch_vendor.py"
if errorlevel 1 (
    echo Warning: Some vendor files could not be downloaded.
)

REM 4. Download and register Noto fonts
echo.
echo [4/7] Installing Noto Sans and Noto Sans Sinhala fonts...
".venv\Scripts\python.exe" "%~dp0tools\install_fonts.py"

REM 5. Verify Pandoc
echo.
echo [5/7] Verifying Pandoc availability...
".venv\Scripts\python.exe" -c "import pypandoc; print('Pandoc Version:', pypandoc.get_pandoc_version())"
if errorlevel 1 (
    echo Pandoc not found. Attempting automatic download via pypandoc...
    ".venv\Scripts\python.exe" -c "import pypandoc; pypandoc.download_pandoc(); print('Downloaded Pandoc:', pypandoc.get_pandoc_version())"
    if errorlevel 1 (
        echo ERROR: Pandoc verification failed.
        pause
        exit /b 1
    )
)

REM 6. Verify Word COM automation
echo.
echo [6/7] Checking Microsoft Word COM automation...
".venv\Scripts\python.exe" -c "import win32com.client as w; app = w.Dispatch('Word.Application'); app.Quit(); print('MS Word COM Automation: OK')" 2>nul
if errorlevel 1 (
    echo [WARN] Microsoft Word COM could not be initialized. Word automation may be unavailable.
) else (
    echo Word COM Automation verified.
)

REM 7. Build reference.docx
echo.
echo [7/7] Building reference.docx style template...
".venv\Scripts\python.exe" "%~dp0tools\build_reference_docx.py"
if errorlevel 1 (
    echo Warning: Could not generate reference.docx yet.
)

echo.
echo ========================================================
echo Setup finished successfully!
echo Run 'run.bat' to start the application.
echo ========================================================
echo.
pause
