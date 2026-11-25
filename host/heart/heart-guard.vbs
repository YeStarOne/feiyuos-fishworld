' heart-guard.vbs - keep Alan's heartbeat alive, windowless.
' Starts node DIRECTLY (no cmd.exe, no .bat): going through `cmd /c start-heart.bat`
' leaves a resident cmd.exe supervisor holding the child for the whole lifetime,
' which is both a console-subsystem carrier (window-flash risk) and a process that
' instantly respawns node when killed. Env vars are set here instead.
' Liveness is judged by the process itself, NOT by heart.lock mtime (written once,
' so an age check would wrongly conclude "stale" and spawn a second instance).
Option Explicit

Dim sh, wmi, procs, p, alive, fso
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'node.exe'")

alive = False
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), "heart.js") > 0 Then alive = True
  End If
Next

If alive Then WScript.Quit 0

' No heartbeat running: drop any stale lock so heart.js can take it cleanly.
here = fso.GetParentFolderName(WScript.ScriptFullName)
If fso.FileExists(here & "\state\heart.lock") Then
  On Error Resume Next
  fso.DeleteFile here & "\state\heart.lock", True
  On Error Goto 0
End If

' Set env for this process, then launch node detached and windowless.
Dim env
Set env = sh.Environment("PROCESS")
env("FISH_HEART_HOME") = here & "\state"
env("FISH_HEART_KEEPALIVE_MS") = "480000"
env("FISH_HEART_WAKE_MIN") = "45"
env("FISH_HEART_MAX_WAKE") = "-1"

sh.CurrentDirectory = here
sh.Run "node heart.js", 0, False