@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
    py servidor.py
) else (
    python servidor.py
)
pause
