' watch-guard.vbs - keep watch-her.js alive, windowless.
' Same rule as heart-guard: launch node directly, never through cmd.exe
' (cmd /c would hold the child for its whole lifetime = resident console carrier).
' Liveness by process, not by file mtime.
Option Explicit

Dim sh, wmi, procs, p, alive, fso
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'node.exe'")

alive = False
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), "watch-her.js") > 0 Then alive = True
  End If
Next

If alive Then WScript.Quit 0

sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "node watch-her.js", 0, False