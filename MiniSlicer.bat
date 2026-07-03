@echo off
rem Lanzador de MiniSlicer (Phrozen Sonic Mini)
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" -m minislicer
