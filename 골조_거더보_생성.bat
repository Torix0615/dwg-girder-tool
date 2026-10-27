@echo off
rem Drag and drop a DWG or DXF file onto this bat.
rem Output (next to the input file): <name>_report.txt, <name>.dxf, 2 HTML files.
rem Rules: C:\Users\taeju\Tools\DwgRework\config.json
setlocal
set PYTHONUTF8=1
set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"
set "SCRIPT=C:\Users\taeju\Tools\DwgRework\run_pipeline.py"
if not exist "%SCRIPT%" (
    echo [ERROR] script not found: %SCRIPT%
    pause
    exit /b 1
)
if "%~1"=="" (
    echo [ERROR] Drag a DWG or DXF file onto this bat file.
    pause
    exit /b 1
)
:loop
if "%~1"=="" goto done
echo ==== %~nx1
"%PY%" "%SCRIPT%" "%~1" --html
if errorlevel 1 (
    echo.
    echo [FAILED] exit code %errorlevel% - see the _report.txt next to the input file.
) else (
    echo [OK] done.
)
shift
goto loop
:done
echo.
echo ==== finished. Output files are next to the input file.
pause
