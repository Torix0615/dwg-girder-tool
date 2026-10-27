@echo off
rem Drag and drop DWG/DXF files onto this bat. Output appears next to each input file.
rem Checks for updates first (needs internet; skipped when offline).
setlocal
set PYTHONUTF8=1
set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python.exe"
if not exist "%PY%" (
    echo [ERROR] runtime folder is missing: %ROOT%runtime
    pause
    exit /b 1
)
"%PY%" "%ROOT%app\updater.py"
if exist "%ROOT%runtime_new\python.exe" (
    echo [update] replacing runtime...
    if exist "%ROOT%runtime_old" rd /s /q "%ROOT%runtime_old"
    move "%ROOT%runtime" "%ROOT%runtime_old" >nul
    move "%ROOT%runtime_new" "%ROOT%runtime" >nul
    rd /s /q "%ROOT%runtime_old"
)
if "%~1"=="" (
    echo.
    echo [USAGE] Drag a DWG or DXF file onto this bat file ^(several at once is fine^).
    echo         Results are created next to the input file.
    pause
    exit /b 1
)
:loop
if "%~1"=="" goto done
echo.
echo ==== %~nx1
"%PY%" "%ROOT%app\run_pipeline.py" "%~1" --html --config "%ROOT%config.json"
if errorlevel 1 (
    echo [FAILED] see the _report.txt next to the input file, or run feedback bat.
) else (
    echo [OK] done.
)
shift
goto loop
:done
echo.
echo ==== finished. Output files are next to the input file.
pause
