@echo off
REM Alan's heartbeat launcher. Windowless start is handled by the VBS wrapper.
REM The key is NOT here: heart.js reads the single copy from the ZCode MCP config.
cd /d "%~dp0"
if not defined FISH_HEART_HOME set FISH_HEART_HOME=%~dp0state
set FISH_HEART_KEEPALIVE_MS=480000
set FISH_HEART_WAKE_MIN=45
set FISH_HEART_MAX_WAKE=-1
node heart.js