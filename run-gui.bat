@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import PySide6, PIL, cv2" >nul 2>&1
if errorlevel 1 (
  echo Oni Thermal LCD Control requires Python 3.12 and the GUI dependencies.
  echo Install them with: py -3.12 -m pip install -e ".[gui]"
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
if /I "%~1"=="--smoke-test" (
  set "ONI_LCD_GUI_SMOKE_TEST=1"
  py -3.12 -m thermalright_lcd.gui
  exit /b %errorlevel%
)
start "" pyw -3.12 -m thermalright_lcd.gui
endlocal
