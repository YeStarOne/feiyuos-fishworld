@echo off
rem nanny_beat launcher -- pythonw, no console window (team rule)
set PY=pythonw.exe
set DIR=%~dp0..
start "" "%PY%" "%DIR%\nanny_beat.py"