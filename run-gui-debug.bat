@echo off
setlocal
cd /d "%~dp0"

echo === Oni Thermal LCD Control SOURCE DEBUG ===
echo Project: %CD%
echo.

py -3.12 -c "import PySide6, PIL, cv2"
if errorlevel 1 (
  echo.
  echo ERROR: Python 3.12 or GUI dependencies are missing.
  echo Install with:
  echo   py -3.12 -m pip install -e ".[gui]"
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"

echo PYTHONPATH=%PYTHONPATH%
echo Launching source module:
echo   py -3.12 -m thermalright_lcd.gui
echo.

py -3.12 -X faulthandler -m thermalright_lcd.gui
set "ONI_EXIT_CODE=%ERRORLEVEL%"

echo.
echo Oni exited with errorlevel %ONI_EXIT_CODE%.
if not "%ONI_EXIT_CODE%"=="0" (
  echo Startup failed. The Python traceback is shown above.
  echo The persistent log is under: %LOCALAPPDATA%\OniThermalLcd\logs
)
pause
endlocal & exit /b %ONI_EXIT_CODE%
