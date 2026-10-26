@echo off
setlocal
echo ===================================================
echo  Sinhala ^& English Physics Paper Digitizer
echo  Building Desktop Executable Package...
echo ===================================================

cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Error: Virtual environment .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe tools\build_desktop.py
if %ERRORLEVEL% NEQ 0 (
    echo Build failed. Check errors above.
    pause
    exit /b 1
)

echo.
echo Build succeeded! You can launch PhysicsDigitizer.exe from dist\PhysicsDigitizer\
pause
