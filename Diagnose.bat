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
if exist "%APP%" >>"%LOG%" echo OK    arena_studio_connector.py
if not exist "%APP%" >>"%LOG%" echo FEHLT arena_studio_connector.py
if exist "%DIR%plugin\ArenaBridgePlugin.lua" >>"%LOG%" echo OK    plugin\ArenaBridgePlugin.lua
if not exist "%DIR%plugin\ArenaBridgePlugin.lua" >>"%LOG%" echo FEHLT plugin\ArenaBridgePlugin.lua
if exist "%DIR%VERSION" >>"%LOG%" echo OK    VERSION
if exist "%DIR%config.json" >>"%LOG%" echo OK    config.json (liegt lokal)
if exist "%DIR%.env" >>"%LOG%" echo OK    .env (liegt lokal)
>>"%LOG%" echo.

>>"%LOG%" echo --- Python im PATH ---
where python >>"%LOG%" 2>&1
where py >>"%LOG%" 2>&1
where pythonw >>"%LOG%" 2>&1
>>"%LOG%" echo.

>>"%LOG%" echo --- Python-Version ---
py -3 --version >>"%LOG%" 2>&1
>>"%LOG%" echo.

rem python.exe aus dem PATH nur starten, wenn es kein Microsoft-Store-Platzhalter
rem ist - sonst oeffnet sich unnoetig der Store.
where python >nul 2>&1
if errorlevel 1 goto no_python
where python | findstr /i /l /c:"WindowsApps" >nul 2>&1
if not errorlevel 1 goto store_alias

>>"%LOG%" echo --- python.exe direkt ---
python --version >>"%LOG%" 2>&1
python -c "import sys;print('Version',sys.version.split()[0]);print('Pfad',sys.executable)" >>"%LOG%" 2>&1
python -c "import tkinter;print('tkinter OK',tkinter.TkVersion)" >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- App-Systemcheck (python arena_studio_connector.py --check) ---
python "%APP%" --check >>"%LOG%" 2>&1
goto show

:store_alias
>>"%LOG%" echo python.exe ist nur der Microsoft-Store-Platzhalter - uebersprungen.
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
