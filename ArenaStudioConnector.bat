@echo off
rem ===========================================================================
rem  WICHTIG - Sicherheitsnetz gegen "Fenster blitzt auf und ist sofort weg":
rem  Bei Doppelklick (ohne Argumente) startet sich diese Datei selbst in einem
rem  Fenster neu, das AUCH BEI FEHLERN offen bleibt (cmd /k). Dadurch ist jede
rem  Fehlermeldung sichtbar - auch ein Tippfehler weiter unten in der Datei.
rem  Beim erfolgreichen Start schliesst sich das Fenster selbst (siehe :end_ok).
if "%~1"=="" (
    start "Arena Studio Connector" cmd /k ""%~f0" --in-window"
    exit /b
)
rem ===========================================================================
rem  Arena Studio Connector - Starter fuer Windows
rem  Doppelklick genuegt: Bridge + Tunnel starten, Token/URL anzeigen und den
rem  Prompt fuer Arena AI in die Zwischenablage kopieren. Es oeffnet sich KEIN
rem  App-Fenster (das gibt es optional mit /gui).
rem  Optionen: /gui  /check  /places  /plugin  /newtoken  /unblock  /version  /help
rem ===========================================================================
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion
title Arena Studio Connector >nul 2>&1
cd /d "%~dp0"

rem Wichtig: alle Pfade hier einmal festhalten. Die Options-Schleife unten
rem benutzt "shift", und shift verschiebt AUCH %0 - danach zeigt %~dp0 nicht
rem mehr auf diesen Ordner.
set "APPDIR=%~dp0"
set "APP=arena_studio_connector.py"
set "APPPATH=%APPDIR%%APP%"
set "PLUGIN=plugin\ArenaBridgePlugin.lua"
set "PLUGINPATH=%APPDIR%%PLUGIN%"
set "ERRLOG=last_error.log"
set "ERRLOGPATH=%APPDIR%%ERRLOG%"
set "VERSIONFILE=%APPDIR%VERSION"
set "STARTLOG=%APPDIR%start_log.txt"
set "GUIFLAG=%APPDIR%gui_gestartet.tmp"
rem Standard = Konsole + Zwischenablage, KEIN App-Fenster (optional /gui)
set "MODE=serve"
set "PY_CMD="
set "PY_ARGS="
set "PY_EXE="
set "PYW_EXE="

rem --------------------------------------------------------------------------
rem  Startlog mitschreiben: zeigt auch dann, wie weit es kam, wenn sich das
rem  Fenster doch einmal schliesst. (Beim Fehlersuchen bitte mitschicken.)
rem --------------------------------------------------------------------------
>"%STARTLOG%" echo %DATE% %TIME%  Arena Studio Connector Starter
>>"%STARTLOG%" echo Ordner:  %APPDIR%
>>"%STARTLOG%" echo Aufruf:  %0 %*
>>"%STARTLOG%" echo Windows: %OS% / %PROCESSOR_ARCHITECTURE%
>>"%STARTLOG%" echo.

rem --------------------------------------------------------------------------
rem  Optionen auswerten
rem --------------------------------------------------------------------------
:argloop
if "%~1"=="" goto args_done
set "A=%~1"
if /i "!A!"=="/gui"      goto opt_gui
if /i "!A!"=="/console"  goto opt_console
if /i "!A!"=="/headless" goto opt_headless
if /i "!A!"=="/headless" goto opt_headless
if /i "!A!"=="/check"    goto opt_check
if /i "!A!"=="/plugin"   goto opt_plugin
if /i "!A!"=="/newtoken" goto opt_newtoken
if /i "!A!"=="/places"   goto run_places
if /i "!A!"=="/unblock"  goto opt_unblock
if /i "!A!"=="/version"  goto opt_version
if /i "!A!"=="/help"     goto help
if /i "!A!"=="-h"        goto help
if /i "!A!"=="--help"    goto help
if /i "!A!"=="--in-window" goto opt_inwindow
echo.
echo [!] Unbekannte Option: !A!
echo     Erlaubt sind: /gui  /check  /places  /plugin  /newtoken  /unblock  /help
goto help

:opt_inwindow
set "IN_WINDOW=1"
shift
goto argloop

:opt_gui
set "MODE=gui"
shift
goto argloop

:opt_console
set "MODE=serve"
shift
goto argloop

:opt_headless
rem Alias: /headless = Konsole + Zwischenablage (wie der Standard)
set "MODE=serve"
shift
goto argloop

:opt_check
set "MODE=check"
shift
goto argloop

:opt_plugin
set "MODE=plugin"
shift
goto argloop

:opt_newtoken
set "MODE=newtoken"
shift
goto argloop

:opt_unblock
set "MODE=unblock"
shift
goto argloop

:opt_version
set "MODE=version"
shift
goto argloop

:args_done
if /i "!MODE!"=="help"    goto help
if /i "!MODE!"=="version" goto show_version
if /i "!MODE!"=="unblock" goto do_unblock

echo.
echo ===========================================================================
echo   Arena Studio Connector
echo   Verbindet Roblox Studio mit Arena AI   -   Bridge + Cloudflare-Tunnel
echo ===========================================================================
echo.

if not exist "%APPPATH%" (
    echo [X] Die Datei "%APP%" fehlt in diesem Ordner:
    echo     %CD%
    echo.
    echo     Bitte das ZIP komplett entpacken: Rechtsklick auf die ZIP-Datei,
    echo     dann "Alle extrahieren ..." waehlen und diese Datei neu starten.
    goto fail
)

if not exist "%PLUGINPATH%" (
    echo [!] Hinweis: "%PLUGINPATH%" wurde nicht gefunden.
    echo     Die App startet, aber die automatische Plugin-Installation funktioniert
    echo     dann nicht. Meist wurde das ZIP nur teilweise entpackt.
    echo.
)

rem --------------------------------------------------------------------------
rem  Laeuft die Datei noch direkt aus der ZIP-Vorschau (temporaerer Ordner)?
rem --------------------------------------------------------------------------
echo "%APPDIR%" | findstr /i /l /c:"\Temp\" >nul 2>&1
if not errorlevel 1 goto warn_temp

rem --------------------------------------------------------------------------
rem  Python 3.9+ suchen
rem --------------------------------------------------------------------------
:find_python
call :probe py -3
if defined PY_CMD goto python_ok

if defined LOCALAPPDATA for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined PY_CMD call :probe "%%~fD\python.exe" ""
)
if defined ProgramFiles for /d %%D in ("%ProgramFiles%\Python3*") do (
    if not defined PY_CMD call :probe "%%~fD\python.exe" ""
)
set "PF86=%ProgramFiles(x86)%"
if defined PF86 for /d %%D in ("%PF86%\Python3*") do (
    if not defined PY_CMD call :probe "%%~fD\python.exe" ""
)
if defined SystemDrive for /d %%D in ("%SystemDrive%\Python3*") do (
    if not defined PY_CMD call :probe "%%~fD\python.exe" ""
)
if defined PY_CMD goto python_ok

rem python.exe aus dem PATH. Normale Installationen zuerst, der Microsoft-Store-
rem Alias danach - damit bei installiertem Python nichts Unnoetiges aufpoppt.
set "STORE_CAND="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY_CMD call :probe_path "%%P"
)
if defined PY_CMD goto python_ok

if defined STORE_CAND (
    echo [i] Pruefe Python aus dem Microsoft Store ...
    echo     Ist dort kein Python installiert, oeffnet sich jetzt kurz der Store -
    echo     in dem Fall einfach schliessen und unten bei "kein Python" weitermachen.
    call :probe "!STORE_CAND!" ""
)
if defined PY_CMD goto python_ok

goto no_python

rem --------------------------------------------------------------------------
rem  Python gefunden -> vorbereiten
rem --------------------------------------------------------------------------
:python_ok
set "PYDIR="
for %%F in ("!PY_EXE!") do (
    set "PYDIR=%%~dpF"
    if /i "%%~nxF"=="py.exe" (
        set "PYW_EXE=%%~dpFpyw.exe"
    ) else (
        set "PYW_EXE=%%~dpFpythonw.exe"
    )
)
if not exist "!PYW_EXE!" set "PYW_EXE="

>>"%STARTLOG%" echo Python:  !PY_EXE! %PY_ARGS%
echo [OK] Python gefunden: !PY_EXE!
"%PY_CMD%" %PY_ARGS% -c "import sys;print('     Version '+sys.version.split()[0])"
echo.

rem GUI pruefen - nur noetig, wenn ein Fenster geoeffnet werden soll.
rem Bei /check und /headless ueberspringen: die Diagnose soll auch dann laufen,
rem wenn tkinter fehlt (genau dann braucht man sie naemlich).
if /i "!MODE!"=="serve"   goto skip_tk
if /i "!MODE!"=="check"    goto skip_tk
if /i "!MODE!"=="plugin"   goto skip_tk
if /i "!MODE!"=="newtoken" goto skip_tk
"%PY_CMD%" %PY_ARGS% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto no_tk
:skip_tk

rem Code laden - zeigt Syntax-/Importfehler sofort im Klartext
"%PY_CMD%" %PY_ARGS% -c "import arena_studio_connector" >nul 2>&1
if errorlevel 1 goto code_fail

echo [OK] App-Code geladen.

if /i "!MODE!"=="check"    goto run_check
if /i "!MODE!"=="serve"    goto run_serve
if /i "!MODE!"=="plugin"   goto run_plugin
if /i "!MODE!"=="newtoken" goto run_newtoken

rem --------------------------------------------------------------------------
rem  Nur bei /gui: App-Fenster ohne Konsole starten
rem --------------------------------------------------------------------------
if not defined PYW_EXE goto run_console_note

rem Alte Signal-/Fehlerdateien weg - sonst ist die Pruefung unten wertlos
del "%GUIFLAG%" >nul 2>&1
del "%ERRLOGPATH%" >nul 2>&1

>>"%STARTLOG%" echo [%TIME%] starte: "!PYW_EXE!" !PY_ARGS! "%APPPATH%"
start "" "!PYW_EXE!" !PY_ARGS! "%APPPATH%"
echo [OK] App gestartet - warte, bis das Fenster wirklich da ist ...
set /a WAIT=0

:wait_gui
timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul
if exist "%GUIFLAG%" goto all_good
if exist "%ERRLOGPATH%" goto launch_failed
set /a WAIT+=1
if !WAIT! LSS 20 goto wait_gui
echo [!] Die App hat nach 20 Sekunden kein Lebenszeichen geschickt.
goto launch_failed

:all_good
>>"%STARTLOG%" echo [%TIME%] GUI-Signal erhalten - Fenster ist offen
echo [OK] Fenster ist offen.
echo.
echo [i] Fertig. Wenn kein Fenster erscheint:
echo     ArenaStudioConnector-Konsole.bat doppelklicken - dort siehst du die
echo     genaue Fehlermeldung.
echo.
echo [i] Das App-Fenster ist offen (optionaler Modus /gui).
echo     Normalerweise reicht ein Doppelklick auf diese Datei - dann laeuft
echo     alles in diesem Fenster, mit Token + URL und Prompt in der Zwischenablage.
echo.
goto end_ok

:run_console_note
echo [i] pythonw.exe wurde nicht gefunden - starte mit Konsolenfenster.
goto run_console

rem --------------------------------------------------------------------------
rem  Modi
rem --------------------------------------------------------------------------
:run_console
echo [i] Start mit Konsolenfenster - hier siehst du alle Meldungen.
echo     Beenden: Fenster schliessen.
echo.
"%PY_CMD%" %PY_ARGS% "%APPPATH%"
set "RC=!errorlevel!"
echo.
echo [i] Die App wurde beendet.  Code: !RC!
echo.
pause
if not "!RC!"=="0" goto fail_no_pause
goto end_ok

:run_serve
echo.
echo [i] Starte Bridge + Cloudflare-Tunnel.
echo     Danach stehen hier Tunnel-URL und Token - der Prompt fuer Arena AI
echo     landet automatisch in der Zwischenablage.
echo     Fenster offen lassen! Beenden mit Strg+C.
echo.
"%PY_CMD%" %PY_ARGS% "%APPPATH%" --serve
echo.
echo [i] Bridge + Tunnel wurden beendet.
pause
goto end_ok

:run_check
"%PY_CMD%" %PY_ARGS% "%APPPATH%" --check
set "RC=!errorlevel!"
echo.
pause
if not "!RC!"=="0" goto fail_no_pause
goto end_ok

:run_places
rem Places eines Users anzeigen: /places <Username>
"%PY_CMD%" %PY_ARGS% "%APPPATH%" --places %2
set "RC=!errorlevel!"
echo.
pause
if not "!RC!"=="0" goto fail_no_pause
goto end_ok

:run_plugin
rem Plugin ohne GUI in den Roblox-Plugin-Ordner schreiben
"%PY_CMD%" %PY_ARGS% "%APPPATH%" --install-plugin
set "RC=!errorlevel!"
echo.
pause
if not "!RC!"=="0" goto fail_no_pause
goto end_ok

:run_newtoken
rem Neuen Bridge-Token erzeugen (der alte wird ungueltig) + Plugin neu schreiben
"%PY_CMD%" %PY_ARGS% "%APPPATH%" --new-token
set "RC=!errorlevel!"
echo.
pause
if not "!RC!"=="0" goto fail_no_pause
goto end_ok

:launch_failed
>>"%STARTLOG%" echo [%TIME%] FEHLER: GUI-Signal blieb aus
echo.
echo [X] Die App hat sich nicht geoeffnet (oder ist sofort wieder zugegangen).
echo.
if exist "%ERRLOGPATH%" (
    echo Fehlerlog ^(%ERRLOGPATH%^):
    echo -----------------------------------------------------------------------
    type "%ERRLOGPATH%"
    echo -----------------------------------------------------------------------
) else (
    echo     Es gibt kein Fehlerlog - dann steckt der Fehler schon davor.
    echo     Bitte die Meldungen in diesem Fenster oben pruefen.
)
echo.
echo     So finden wir den Fehler:
echo       1. Dieses Fenster NICHT schliessen - die Meldung oben ist wichtig.
echo       2. Alternativ: ArenaStudioConnector-Konsole.bat starten.
echo       3. Diagnose.bat starten - schreibt diagnose_log.txt in diesen Ordner.
echo     Der Startverlauf steht hier: %STARTLOG%
goto fail_wait

:warn_temp
echo.
echo [X] Diese Datei laeuft aus einem TEMPORAEREN Ordner:
echo     %APPDIR%
echo.
echo     Das passiert, wenn man die .bat direkt aus der ZIP-Vorschau startet
echo     oder das ZIP nur doppelklickt, ohne es zu entpacken.
echo.
echo     Bitte: Rechtsklick auf die ZIP-Datei -^> "Alle extrahieren ...",
echo     danach im entpackten Ordner ArenaStudioConnector.bat starten.
echo.
goto fail_wait

rem --------------------------------------------------------------------------
rem  Sonderfaelle
rem --------------------------------------------------------------------------
:no_tk
echo [X] In deinem Python fehlt "tkinter" - damit kann kein Fenster geoeffnet
echo     werden. Python einfach neu installieren und dabei die Option
echo     "tcl/tk and IDLE" angehakt lassen.
echo.
echo     Alternativ ohne Fenster starten:  ArenaStudioConnector.bat
echo     (Standardmodus braucht kein tkinter)
goto fail_wait

:code_fail
echo [X] Der Python-Code konnte nicht geladen werden. Meldung:
echo ---------------------------------------------------------------------------
"%PY_CMD%" %PY_ARGS% -c "import arena_studio_connector"
echo ---------------------------------------------------------------------------
echo     Bitte diese Meldung notieren bzw. kopieren - damit laesst sich das
echo     Problem genau eingrenzen.
goto fail_wait

rem --------------------------------------------------------------------------
rem  Kein Python gefunden
rem --------------------------------------------------------------------------
:no_python
if defined TRIED_INSTALL goto no_python_manual
echo [X] Es wurde kein Python 3.9 oder neuer gefunden.
echo.
echo     Der Arena Studio Connector ist eine .bat-Datei, die die Python-App
echo     startet - Python muss also einmal installiert sein.
echo.
where winget >nul 2>&1
if errorlevel 1 goto no_winget

echo [i] Ich kann Python 3 jetzt automatisch installieren.
choice /c JN /n /t 60 /d N /m "Python jetzt automatisch installieren? [J/N] "
if errorlevel 2 goto no_python_manual
if errorlevel 1 goto install_python

:no_winget
echo [i] Automatische Installation ist hier nicht verfuegbar.
goto no_python_manual

:install_python
set "TRIED_INSTALL=1"
echo.
echo [i] Installiere Python 3.12 ueber winget. Falls Windows nach
echo     Administratorrechten fragt, bitte bestaetigen. Das dauert 1-2 Minuten.
echo.
winget install --id Python.Python.3.12 -e --source winget --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo [i] Erneuter Versuch ohne Benutzer-Installation ...
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
)
echo.
echo [i] Pruefe die Installation ...
set "PY_CMD="
set "PY_ARGS="
set "PY_EXE="
set "PYW_EXE="
goto find_python

:no_python_manual
echo.
echo     Manuell installieren:  https://www.python.org/downloads/windows/
echo     oder im Microsoft Store: "Python 3.12" suchen und installieren.
echo     Wichtig beim python.org-Installer: Haken bei "Add python.exe to PATH"
echo     setzen und "tcl/tk and IDLE" angehakt lassen.
echo.
choice /c JN /n /t 60 /d N /m "Download-Seite jetzt im Browser oeffnen? [J/N] "
if errorlevel 2 goto no_python_end
start "" "https://www.python.org/downloads/windows/"
:no_python_end
echo.
echo     Danach diese Datei einfach erneut doppelklicken.
goto fail_wait

rem --------------------------------------------------------------------------
rem  Hilfe / Version / Sperre entfernen
rem --------------------------------------------------------------------------
:help
echo.
echo ===========================================================================
echo   Arena Studio Connector - Starter
echo ===========================================================================
echo.
echo   Einfach doppelklicken:
echo     - Bridge + Tunnel starten (dieses Fenster bleibt offen)
echo     - Tunnel-URL + Token werden hier angezeigt
echo     - der Prompt fuer Arena AI wird in die Zwischenablage kopiert
echo     - im Studio-Plugin werden URL + Token eingetragen
echo.
echo   Optionen:
echo     /gui        Alte App mit Fenster starten (optional, braucht tkinter)
echo     /places X   Places von Roblox-User X anzeigen (PlaceId/UniverseId)
echo     /check      Systemcheck: Python, tkinter, Plugin, Port, cloudflared
echo     /plugin     Studio-Plugin neu installieren (automatisch in den
echo                 Roblox-Plugin-Ordner, ohne GUI)
echo     /newtoken   Neuen Bridge-Token erzeugen und Plugin neu installieren
echo     /unblock    Windows-Sperre "Datei aus dem Internet" entfernen
echo     /version    Version dieser App anzeigen
echo     /help       Diese Hilfe
echo.
echo   App-Ordner:  %CD%
echo ===========================================================================
echo.
pause
goto end_ok

:show_version
rem Version kommt aus der Datei VERSION (liegt im ZIP). Bewusst kein Parsen der
rem Python-Datei: in for-/delims-Optionen sind Anfuehrungszeichen und
rem Leerzeichen zu fehleranfaellig. build_zip.py prueft, dass VERSION und
rem APP_VERSION in arena_studio_connector.py identisch sind.
set "VER="
if exist "%VERSIONFILE%" for /f "delims=" %%V in ('type "%VERSIONFILE%"') do if not defined VER set "VER=%%V"
if not defined VER set "VER=unbekannt"
echo.
echo Arena Studio Connector !VER!
echo Ordner: %CD%
echo.
goto end_ok

:do_unblock
echo.
echo [i] Entferne die Windows-Sperre fuer alle Dateien in diesem Ordner ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '.' -Recurse -File | Unblock-File; Write-Host '[OK] Sperre entfernt - diese Datei kann jetzt normal gestartet werden.'"
echo.
goto end_ok

rem --------------------------------------------------------------------------
rem  Ende
rem --------------------------------------------------------------------------
:end_ok
rem Wurde das Fenster vom Sicherheitsnetz geoeffnet (cmd /k), schliessen wir es
rem hier bei Erfolg - sonst haengt nach jedem Start eine Konsole herum.
if defined IN_WINDOW goto close_window
endlocal
exit /b 0

:close_window
endlocal
exit

:fail_wait
echo.
pause
endlocal
exit /b 1

:fail_no_pause
endlocal
exit /b 1

:fail
echo.
echo Abgebrochen.
goto fail_wait

rem --------------------------------------------------------------------------
rem  Hilfsroutinen
rem --------------------------------------------------------------------------

rem :probe <Interpreter oder Launcher> <feste Argumente, z. B. -3>
rem Setzt PY_CMD / PY_ARGS / PY_EXE, wenn Python 3.9+ gefunden wurde.
:probe
set "CAND=%~1"
set "CARGS=%~2"
set "CANDPATH="
if exist "%~1" (
    set "CANDPATH=%~1"
) else (
    for /f "delims=" %%P in ('where "%~1" 2^>nul') do (
        if not defined CANDPATH set "CANDPATH=%%P"
    )
)
if not defined CANDPATH exit /b 0
"%CAND%" %CARGS% -c "import sys;raise SystemExit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY_CMD=%CAND%"
set "PY_ARGS=%CARGS%"
set "PY_EXE=!CANDPATH!"
exit /b 0

rem :probe_path <voller Pfad zu python.exe>
rem Normale Installationen werden sofort geprueft. Der Windows-Store-Alias
rem (WindowsApps) wird nur gemerkt und erst als Notnagel probiert - ist Python
rem dort naemlich nicht installiert, oeffnet der Aufruf den Microsoft Store.
:probe_path
if not "%~1"=="" (
    set "PN=%~1"
    set "PN2=!PN:WindowsApps=!"
    set "PN3=!PN:windowsapps=!"
    if not "!PN!"=="!PN2!" (
        if not defined STORE_CAND set "STORE_CAND=%~1"
    ) else (
        if not "!PN!"=="!PN3!" (
            if not defined STORE_CAND set "STORE_CAND=%~1"
        ) else (
            call :probe "%~1" ""
        )
    )
)
exit /b 0
