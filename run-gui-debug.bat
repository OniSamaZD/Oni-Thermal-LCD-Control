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

py -3.12 -m thermalright_lcd.gui

echo.
echo Oni exited with errorlevel %errorlevel%.
pause
endlocal
