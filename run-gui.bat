@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if /I "%~1"=="--smoke-test" (
  py -3.12 -c "import PySide6, PIL, cv2" >nul 2>&1
  if errorlevel 1 exit /b 1
  set "ONI_LCD_GUI_SMOKE_TEST=1"
  py -3.12 -m thermalright_lcd.gui
  exit /b %errorlevel%
)
start "" /b wscript.exe "%CD%\packaging\launch-gui-hidden.vbs" "%CD%"
endlocal & exit /b 0
