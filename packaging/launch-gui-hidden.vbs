Option Explicit
Dim shell, root, environment, checkCode
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then
  MsgBox "Oni project path was not supplied.", 16, "Oni Thermal LCD Control"
  WScript.Quit 2
End If
root = WScript.Arguments(0)
Set environment = shell.Environment("PROCESS")
environment("PYTHONPATH") = root & "\src"
checkCode = shell.Run("pyw.exe -3.12 -c ""import PySide6, PIL, cv2""", 0, True)
If checkCode <> 0 Then
  MsgBox "Oni requires Python 3.12 and its GUI dependencies." & vbCrLf & vbCrLf & "Run: py -3.12 -m pip install -r requirements.txt", 16, "Oni startup failed"
  WScript.Quit checkCode
End If
shell.CurrentDirectory = root
' pythonw/pyw has no console of its own.  SW_HIDE (0) also hides the Qt main
' window, so launch the GUI process with a normal show state while keeping the
' dependency probe above hidden.
shell.Run "pyw.exe -3.12 -m thermalright_lcd.gui", 1, False
