@echo off
rem Write feedback -> zip on the desktop (send it by KakaoTalk or e-mail).
setlocal
set PYTHONUTF8=1
set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python.exe"
if not exist "%PY%" (
    echo [ERROR] runtime folder is missing: %ROOT%runtime
    pause
    exit /b 1
)
"%PY%" "%ROOT%app\feedback.py"
pause
