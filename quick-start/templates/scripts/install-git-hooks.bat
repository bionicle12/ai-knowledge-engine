@echo off
rem Manual Windows entry point for hook installation (cmd / double-click).
setlocal
set "SCRIPT_DIR=%~dp0"

call :find_git_bash
if defined GIT_BASH (
    "%GIT_BASH%" "%SCRIPT_DIR%install-git-hooks.sh"
    goto :eof
)

echo Git Bash not found. Install Git for Windows, then re-run.
exit /b 1

:find_git_bash
rem Git for Windows' bash first. A bare `where bash` can find the WSL
rem launcher (System32\bash.exe or WindowsApps\bash.exe), which would install
rem the hooks from inside Linux.
set "GIT_BASH="
for %%P in ("%ProgramFiles%\Git\bin\bash.exe" "%ProgramFiles(x86)%\Git\bin\bash.exe" "%LocalAppData%\Programs\Git\bin\bash.exe") do (
    if not defined GIT_BASH if exist "%%~P" set "GIT_BASH=%%~P"
)
if defined GIT_BASH goto :eof
for /f "delims=" %%G in ('where git 2^>nul') do (
    if not defined GIT_BASH if exist "%%~dpG..\bin\bash.exe" set "GIT_BASH=%%~dpG..\bin\bash.exe"
)
if defined GIT_BASH goto :eof
for /f "delims=" %%B in ('where bash 2^>nul') do (
    if not defined GIT_BASH (
        echo %%~B| findstr /i /c:"System32" /c:"WindowsApps" >nul || set "GIT_BASH=%%~B"
    )
)
goto :eof
