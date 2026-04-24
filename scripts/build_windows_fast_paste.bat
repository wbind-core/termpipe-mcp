@echo off
setlocal

echo [Windows Fast Paste] Initiating compilation using MSVC...

:: Ensure we are working locally from the directory this script resides in
cd /D "%~dp0"

:: Look for the Cl C Compiler
where cl >nul 2>nul
if %errorlevel% neq 0 (
    echo MSVC Compiler ('cl.exe') not found! Please open this script from a "Developer Command Prompt for VS".
    exit /b 1
)

:: Build the target
cl /O2 ..\termpipe_mcp\resources\windows-fast-paste.c /Fe:..\binaries\windows-fast-paste.exe user32.lib

if %errorlevel% neq 0 (
    echo Compilation failed.
    exit /b %errorlevel%
)

echo [Success] compiled windows-fast-paste.exe to \binaries\
del windows-fast-paste.obj >nul 2>nul
exit /b 0
