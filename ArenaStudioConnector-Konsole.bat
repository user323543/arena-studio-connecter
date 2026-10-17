@echo off
rem ===========================================================================
rem  Arena Studio Connector MIT Konsolenfenster starten.
rem  Zeigt alle Meldungen an - praktisch, wenn sich kein Fenster oeffnet oder
rem  um zu sehen, was Bridge und Cloudflare-Tunnel gerade machen.
rem  Das Fenster bleibt auch bei Fehlern offen.
rem ===========================================================================
if "%~1"=="" (
    start "Arena Studio Connector - Konsole" cmd /k ""%~f0" --bleib-offen"
    exit /b
)
call "%~dp0ArenaStudioConnector.bat" /console
if errorlevel 1 pause
