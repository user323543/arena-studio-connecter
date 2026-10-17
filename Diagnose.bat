@echo off
rem ===========================================================================
rem  Diagnose - Arena Studio Connector
rem  Schreibt alles Wichtige in diagnose_log.txt und bleibt offen.
rem  Erste Anlaufstelle, wenn sich beim Start nur ein Fenster kurz zeigt.
rem  Einfach doppelklicken. Es wird nichts installiert und nichts geaendert.
rem ===========================================================================
setlocal EnableExtensions
set "DIR=%~dp0"
set "LOG=%DIR%diagnose_log.txt"
set "APP=%DIR%arena_studio_connector.py"

> "%LOG%" echo Arena Studio Connector - Diagnose
>>"%LOG%" echo ==========================================================
>>"%LOG%" echo Datum:    %DATE% %TIME%
>>"%LOG%" echo Ordner:   %DIR%
>>"%LOG%" echo Aufruf:   %0 %*
>>"%LOG%" echo Windows:  %OS% / %PROCESSOR_ARCHITECTURE%
>>"%LOG%" echo Benutzer: %USERNAME% auf %COMPUTERNAME%
>>"%LOG%" echo.

>>"%LOG%" echo --- Dateien in diesem Ordner ---
if exist "%APP%" echo OK    arena_studio_connector.py>>"%LOG%"
if not exist "%APP%" echo FEHLT arena_studio_connector.py>>"%LOG%"
if exist "%DIR%plugin\ArenaBridgePlugin.lua" echo OK    plugin\ArenaBridgePlugin.lua>>"%LOG%"
if not exist "%DIR%plugin\ArenaBridgePlugin.lua" echo FEHLT plugin\ArenaBridgePlugin.lua>>"%LOG%"
if exist "%DIR%VERSION" echo OK    VERSION>>"%LOG%"
if exist "%DIR%config.json" echo OK    config.json liegt lokal>>"%LOG%"
if exist "%DIR%.env" echo OK    .env liegt lokal>>"%LOG%"
>>"%LOG%" echo.

>>"%LOG%" echo --- Python im PATH ---
where python >>"%LOG%" 2>&1
where py >>"%LOG%" 2>&1
where pythonw >>"%LOG%" 2>&1
>>"%LOG%" echo.

>>"%LOG%" echo --- Python-Version ---
py -3 --version >>"%LOG%" 2>&1
>>"%LOG%" echo.

rem Erstes echtes python.exe aus dem PATH nehmen. Wichtig: "where python" kann
rem MEHRERE Treffer liefern - z. B. das echte Python und zusaetzlich den
rem Microsoft-Store-Platzhalter (WindowsApps). Zeilenweise filtern, sonst wird
rem ein vorhandenes Python faelschlich uebersprungen.
set "PYEXE="
for /f "delims=" %%P in ('where python 2^>nul ^| findstr /i /v /l /c:"WindowsApps"') do if not defined PYEXE set "PYEXE=%%P"
if defined PYEXE goto have_python

where python >nul 2>&1
if errorlevel 1 goto no_python
>>"%LOG%" echo Nur der Microsoft-Store-Platzhalter gefunden - uebersprungen.
>>"%LOG%" echo Tipp: Python von python.org installieren oder "py -3" nutzen.
goto show

:have_python
>>"%LOG%" echo --- python.exe direkt ---
>>"%LOG%" echo Datei: %PYEXE%
"%PYEXE%" --version >>"%LOG%" 2>&1
"%PYEXE%" -c "import sys;print('Version',sys.version.split()[0]);print('Pfad',sys.executable)" >>"%LOG%" 2>&1
"%PYEXE%" -c "import tkinter;print('tkinter OK',tkinter.TkVersion)" >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- App-Systemcheck (arena_studio_connector.py --check) ---
"%PYEXE%" "%APP%" --check >>"%LOG%" 2>&1
goto show

:no_python
>>"%LOG%" echo Kein python.exe im PATH gefunden.

:show
>>"%LOG%" echo.
>>"%LOG%" echo --- Ende der Diagnose ---

echo.
echo ===========================================================================
echo   Arena Studio Connector - Diagnose
echo ===========================================================================
echo.
type "%LOG%"
echo ===========================================================================
echo.
echo Diese Datei bitte mitschicken oder den Inhalt oben kopieren:
echo   %LOG%
echo.
pause
endlocal
exit /b 0
