#!/usr/bin/env python3
"""Windows-Smoketest fuer den neuen Ablauf (laeuft auch lokal).

Prueft genau das, was der Nutzer sieht:
  1. .bat-Standard startet Bridge + Tunnel (hier mit --no-tunnel)
  2. In der Konsole stehen VERBINDUNGSDATEN, Token und die lokale URL
  3. prompt.txt wird geschrieben und enthaelt Token, URL und die Aufgabe
  4. Der Prompt liegt in der Zwischenablage (nur Windows)
  5. /api/status antwortet mit dem Token

Aufruf (Windows-CI):  python tests/windows_smoke.py
Exit-Code 0 = alles gut, sonst Fehlermeldung + Exit 1.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# Auf Windows ist stdout sonst cp1252 - "fuer"/Umlaute wuerden den Test mit
# UnicodeEncodeError abbrechen, bevor irgendetwas zu sehen ist.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "arena_studio_connector.py"
def free_port() -> int:
    """Freien Port suchen - so kollidiert der Test weder mit einer laufenden
    .bat noch mit Resten eines frueheren Testlaufs (TIME_WAIT)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = free_port()  # wird in main() noch einmal frisch bestimmt
BASE = f"http://127.0.0.1:{PORT}"


STEPS_FILE = Path(__file__).resolve().parent.parent / "windows_smoke_steps.txt"


def step(message: str) -> None:
    """Schreibt jeden Schritt sofort in eine Datei - auch wenn die Konsole
    (aus welchem Grund auch immer) keine Ausgabe mehr liefert."""
    try:
        with open(STEPS_FILE, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(safe(message) + "\n")
            fh.flush()
    except Exception:
        pass
    print(safe(message), flush=True)


def safe(text: str) -> str:
    """Nur ASCII auf die Konsole - unabhaengig von der Windows-Codepage."""
    return text.encode("ascii", "replace").decode("ascii")


def fail(message: str, log: str = "") -> None:
    print(f"[X] {message}", flush=True)
    if log:
        print("-" * 70)
        print(safe(log[-4000:]))
        print("-" * 70)
    sys.exit(1)


def clipboard_works() -> bool:
    """Set/Get-Clipboard ausprobieren.

    Auf Build-Runnern (Session 0) gibt es keine echte Zwischenablage - dort
    liefert Set-Clipboard stillschweigend nichts. Dann darf der Test nicht
    fehlschlagen, denn auf einem normalen Desktop funktioniert es.
    """
    if os.name != "nt":
        return False
    probe = "arena-clipboard-probe-42"
    try:
        cmd = f"Set-Clipboard -Value '{probe}'; Get-Clipboard -Raw"
        result = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                                capture_output=True, text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return probe in (result.stdout or "")
    except Exception:
        return False


def read_clipboard() -> str:
    """Liest die Windows-Zwischenablage (auf anderen Systemen: leer)."""
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout or ""
    except Exception as exc:
        print(f"[!] Zwischenablage nicht lesbar: {exc}")
        return ""


def main() -> int:
    try:
        STEPS_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass
    step("[i] Smoketest startet")
    tmp = tempfile.TemporaryDirectory()
    app_dir = Path(tmp.name)
    env = {**os.environ,
           "ARENA_APP_DIR": str(app_dir),
           "ARENA_PLUGIN_DIR": str(app_dir / "plugins"),
           "PYTHONIOENCODING": "utf-8",
           "PYTHONUTF8": "1"}

    # frischer Port direkt vor dem Start (kein TIME_WAIT-Rest, keine .bat)
    global PORT, BASE
    PORT = free_port()
    BASE = f"http://127.0.0.1:{PORT}"
    (app_dir / "config.json").write_text(json.dumps({"port": PORT}), encoding="utf-8")

    print(f"[i] Starte {APP.name} --no-tunnel (App-Ordner: {app_dir}, Port {PORT})")
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-u", str(APP), "--no-tunnel"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(app_dir))

    log = ""
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            log += line
            print(safe(line), end="", flush=True)
            if "VERBINDUNGSDATEN" in log and "SO GEHT'S" in log:
                break

        step("[i] Leseschleife beendet")
        if "VERBINDUNGSDATEN" not in log:
            fail("Konsole zeigt keine Verbindungsdaten", log)

        cfg_path = app_dir / "config.json"
        if not cfg_path.exists():
            fail("config.json wurde nicht geschrieben", log)
        token = json.loads(cfg_path.read_text(encoding="utf-8")).get("bridge_token")
        if not token:
            fail("Kein Bridge-Token in config.json", log)
        if token not in log:
            fail("Token fehlt in der Konsolenausgabe", log)
        step("[OK] Konsole zeigt Verbindungsdaten inkl. Token")

        prompt_path = app_dir / "prompt.txt"
        deadline = time.time() + 20
        while time.time() < deadline and not prompt_path.exists():
            time.sleep(0.3)
        if not prompt_path.exists():
            fail("prompt.txt wurde nicht geschrieben", log)
        prompt = prompt_path.read_text(encoding="utf-8")
        for needle in (token, f"http://127.0.0.1:{PORT}", "MEINE AUFGABE", "/api/status"):
            if needle not in prompt:
                # Rest eines abgebrochenen Laufs? Kurz warten und erneut lesen.
                time.sleep(1.0)
                prompt = prompt_path.read_text(encoding="utf-8")
            if needle not in prompt:
                fail(f"prompt.txt unvollstaendig - fehlt: {needle}", safe(prompt))
        step("[OK] prompt.txt enthaelt Token, URL und die Aufgabe")

        # Plugin wurde mit Vorbelegung installiert
        plugin = app_dir / "plugins" / "ArenaBridgePlugin.lua"
        if not plugin.exists():
            fail(f"Studio-Plugin fehlt: {plugin}", log)
        if token not in plugin.read_text(encoding="utf-8"):
            fail("Token steht nicht als Vorbelegung im Plugin")
        step("[OK] Studio-Plugin installiert (URL + Token vorbelegt)")

        # Bridge antwortet
        request = urllib.request.Request(f"{BASE}/api/status",
                                         headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data.get("ok"):
            fail(f"/api/status antwortet nicht ok: {data}", log)
        step("[OK] /api/status antwortet mit dem Token")

        # Zwischenablage: unter Windows pruefen. Auf CI-Runnern (Session 0)
        # ist sie nicht sitzungsuebergreifend - dort genuegt die Bestaetigung
        # der App, sonst waere der Test dort nie gruen.
        if os.name == "nt":
            clip = read_clipboard() if clipboard_works() else ""
            if token in clip:
                step("[OK] Prompt liegt in der Zwischenablage")
            elif "Prompt liegt in der Zwischenablage" in log:
                step("[i] Zwischenablage: App meldet Erfolg, dieser Prozess sieht "
                     "sie nicht (typisch fuer CI-Runner) - kein Fehler")
            elif not os.environ.get("SESSIONNAME"):
                step("[!] Zwischenablage ohne Desktop-Session nicht verfuegbar "
                     "(CI-Runner) - App weist auf prompt.txt hin")
            else:
                fail(f"Prompt ist nicht in der Zwischenablage (Laenge {len(clip)})", log)
        else:
            step("[i] Zwischenablage-Pruefung nur unter Windows")
    except BaseException:
        import traceback
        step("[X] Ausnahme: " + traceback.format_exc()[-1500:])
        raise
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        # Windows gibt Dateien des Kindprozesses manchmal erst verzoegert frei -
        # ein nicht loeschbarer Temp-Ordner darf den Test nicht kippen.
        try:
            time.sleep(0.5)
            tmp.cleanup()
        except Exception as exc:
            print(f"[i] Temp-Ordner bleibt liegen ({exc})")

    step("[OK] Smoketest erfolgreich.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # nie ohne Meldung sterben
        import traceback
        traceback.print_exc()
        sys.exit(1)
