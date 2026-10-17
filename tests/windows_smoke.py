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
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def fail(message: str, log: str = "") -> None:
    print(f"[X] {message}", flush=True)
    if log:
        print("-" * 70)
        print(log[-4000:])
        print("-" * 70)
    sys.exit(1)


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
    print("[i] Smoketest startet", flush=True)
    tmp = tempfile.TemporaryDirectory()
    app_dir = Path(tmp.name)
    env = {**os.environ,
           "ARENA_APP_DIR": str(app_dir),
           "ARENA_PLUGIN_DIR": str(app_dir / "plugins"),
           "PYTHONIOENCODING": "utf-8"}

    print(f"[i] Starte {APP.name} --no-tunnel (App-Ordner: {app_dir})")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(APP), "--no-tunnel"],
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
            print(line, end="", flush=True)
            if "VERBINDUNGSDATEN" in log and "SO GEHT'S" in log:
                break

        print("[i] Leseschleife beendet", flush=True)
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
        print("[OK] Konsole zeigt Verbindungsdaten inkl. Token")

        prompt_path = app_dir / "prompt.txt"
        deadline = time.time() + 20
        while time.time() < deadline and not prompt_path.exists():
            time.sleep(0.3)
        if not prompt_path.exists():
            fail("prompt.txt wurde nicht geschrieben", log)
        prompt = prompt_path.read_text(encoding="utf-8")
        for needle in (token, f"http://127.0.0.1:{PORT}", "MEINE AUFGABE", "/api/status"):
            if needle not in prompt:
                fail(f"prompt.txt unvollstaendig - fehlt: {needle}", prompt)
        print("[OK] prompt.txt enthaelt Token, URL und die Aufgabe")

        # Plugin wurde mit Vorbelegung installiert
        plugin = app_dir / "plugins" / "ArenaBridgePlugin.lua"
        if not plugin.exists():
            fail(f"Studio-Plugin fehlt: {plugin}", log)
        if token not in plugin.read_text(encoding="utf-8"):
            fail("Token steht nicht als Vorbelegung im Plugin")
        print("[OK] Studio-Plugin installiert (URL + Token vorbelegt)")

        # Bridge antwortet
        request = urllib.request.Request(f"{BASE}/api/status",
                                         headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data.get("ok"):
            fail(f"/api/status antwortet nicht ok: {data}", log)
        print("[OK] /api/status antwortet mit dem Token")

        # Zwischenablage (nur Windows aussagekraeftig)
        print("[i] Pruefe Zwischenablage ...", flush=True)
        if os.name == "nt":
            clip = read_clipboard()
            if token not in clip:
                fail(f"Prompt ist nicht in der Zwischenablage (Laenge {len(clip)})", log)
            print("[OK] Prompt liegt in der Zwischenablage")
        else:
            print("[i] Zwischenablage-Pruefung nur unter Windows")
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

    print()
    print("[OK] Smoketest erfolgreich.")
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
