@echo off
rem Manual Windows entry point for hook installation (cmd / double-click).
setlocal
set "SCRIPT_DIR=%~dp0"

where bash >nul 2>nul
if %errorlevel% equ 0 (
    bash "%SCRIPT_DIR%install-git-hooks.sh"
    goto :eof
)

if exist "%ProgramFiles%\Git\bin\bash.exe" (
    "%ProgramFiles%\Git\bin\bash.exe" "%SCRIPT_DIR%install-git-hooks.sh"
    goto :eof
)

echo Git Bash not found. Install Git for Windows, then re-run.
exit /b 1
