@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Oni Thermal LCD Control - Rebuild EXE
echo ============================================
echo.

tasklist /FI "IMAGENAME eq Oni Thermal LCD Control.exe" 2>NUL | find /I "Oni Thermal LCD Control.exe" >NUL
if not errorlevel 1 (
    echo ERROR: Oni Thermal LCD Control.exe is still running.
    echo Exit the app completely from the tray, then run this file again.
    echo.
    pause
    exit /b 1
)

if not exist "packaging\build-portable.ps1" (
    echo ERROR: packaging\build-portable.ps1 was not found.
    echo Keep this BAT in the repository root.
    echo.
    pause
    exit /b 1
)

echo Building the portable EXE...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\packaging\build-portable.ps1"
if errorlevel 1 (
    echo.
    echo BUILD FAILED. Scroll up for the error.
    pause
    exit /b 1
)

echo.
echo BUILD COMPLETE.
echo EXE:
echo "%CD%\dist\Oni Thermal LCD Control.exe"
echo.

if exist ".\dist\Oni Thermal LCD Control.exe" (
    start "" ".\dist\Oni Thermal LCD Control.exe"
) else (
    echo ERROR: Build finished but the EXE was not found in dist.
)

pause
endlocal
