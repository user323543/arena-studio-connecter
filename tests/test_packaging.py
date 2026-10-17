"""Tests fuer den .bat-Starter und die ZIP-Verteilung.

Diese Tests laufen ueberall (auch ohne Windows), pruefen aber genau die Dinge,
die unter Windows sonst still kaputtgehen: Zeilenenden (CRLF), ASCII, Labels,
goto-Ziele, Klammer-Bloecke und der Inhalt des Release-ZIPs.
"""
import json
import os
import re
import time
import urllib.request
from unittest import mock
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_zip  # noqa: E402
import arena_studio_connector as arena  # noqa: E402
from arena_studio_connector import APP_VERSION  # noqa: E402

LAUNCHER = "ArenaStudioConnector.bat"


class BatDateienTest(unittest.TestCase):
    def test_bat_dateien_haben_crlf_und_sind_ascii(self):
        self.assertIn(LAUNCHER, build_zip.BAT_FILES)
        self.assertGreaterEqual(len(build_zip.BAT_FILES), 3)  # Starter, Konsole, Build
        for name in build_zip.BAT_FILES:
            raw = (ROOT / name).read_bytes()
            with self.subTest(datei=name):
                self.assertIn(b"\r\n", raw, f"{name}: keine CRLF-Zeilenenden")
                self.assertIsNone(
                    __import__("re").search(rb"(?<!\r)\n", raw),
                    f"{name}: einzelne LF-Zeilen (cmd braucht CRLF)")
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"),
                                 f"{name}: UTF-8-BOM stoert cmd")
                raw.decode("ascii")  # wirft UnicodeDecodeError bei Umlauten

    def test_bat_struktur_ist_konsistent(self):
        self.assertEqual(build_zip.check_bat_structure(), [])
        self.assertEqual(build_zip.check_line_endings(), [])
        self.assertEqual(build_zip.check_shift_paths(), [])

    def test_pfade_stehen_vor_der_options_schleife(self):
        # Regression: "shift" verschiebt auch %0 - danach zeigte %~dp0VERSION
        # auf D:\VERSION und /version meldete "unbekannt".
        text = (ROOT / "ArenaStudioConnector.bat").read_text(encoding="ascii")
        grenze = text.index(":args_done")
        vorher, nachher = text[:grenze], text[grenze:]
        self.assertIsNone(re.search(r"%~dp0|(?<!%)%0(?!\d)", nachher),
                          "%~dp0/%0 nach der Options-Schleife (shift verschiebt %0)")
        self.assertTrue('set "APPDIR=%~dp0"' in vorher)
        for definition in ('set "APPPATH=', 'set "PLUGINPATH=', 'set "ERRLOGPATH=',
                           'set "VERSIONFILE='):
            self.assertTrue(definition in vorher,
                            f"{definition}... muss vor der Options-Schleife stehen "
                            f"(sonst zeigt %~dp0 nach dem shift woanders hin)")


class SicherheitsnetzTest(unittest.TestCase):
    """Regression: "Fenster blitzt nur kurz auf, dann ist es weg".

    Bei Doppelklick (ohne Argumente) muss sich der Starter in einem cmd /k
    Fenster neu starten, damit jede Fehlermeldung sichtbar bleibt. Mit
    Argumenten (CI, /version, /check ...) darf er das NICHT tun, sonst waere
    die Ausgabe weg.
    """

    def setUp(self):
        self.text = (ROOT / "ArenaStudioConnector.bat").read_text(encoding="ascii")

    def test_neustart_in_offenem_fenster_bei_doppelklick(self):
        self.assertIn('if "%~1"=="" (', self.text)
        self.assertIn('cmd /k ""%~f0" --in-window"', self.text)
        self.assertIn("--in-window", self.text)

    def test_argumente_starten_kein_zweites_fenster(self):
        # Der Neustart haengt an %~1 == "" - mit Argumenten laeuft alles direkt.
        guard = self.text[self.text.index('if "%~1"=="" ('):]
        guard = guard[:guard.index(")") + 1]
        self.assertIn("--in-window", guard)
        self.assertIn("exit /b", guard)
        self.assertIn(":opt_inwindow", self.text)

    def test_fenster_schliesst_sich_nur_bei_erfolg(self):
        self.assertIn(":close_window", self.text)
        self.assertIn("if defined IN_WINDOW goto close_window", self.text)

    def test_wartet_auf_lebenszeichen_der_app(self):
        # Nicht blind "gestartet" melden, sondern warten, bis die GUI wirklich da ist
        self.assertIn("gui_gestartet.tmp", self.text)
        self.assertIn(":wait_gui", self.text)
        self.assertIn("goto launch_failed", self.text)

    def test_schreibt_startlog(self):
        self.assertIn("start_log.txt", self.text)

    def test_erkennt_start_aus_der_zip_vorschau(self):
        self.assertIn(":warn_temp", self.text)
        self.assertIn("Alle extrahieren", self.text)

    def test_windows_smoke_skript_prueft_den_ablauf(self):
        smoke = (ROOT / "tests" / "windows_smoke.py").read_text(encoding="utf-8")
        for needle in ("VERBINDUNGSDATEN", "prompt.txt", "MEINE AUFGABE",
                       "/api/status", "Get-Clipboard", "ARENA_APP_DIR"):
            self.assertIn(needle, smoke)

    def test_diagnose_bat_ist_dabei(self):
        diag = (ROOT / "Diagnose.bat").read_bytes()
        self.assertIn(b"diagnose_log.txt", diag)
        self.assertIn(b"pause", diag)
        self.assertIn(b"\r\n", diag)
        self.assertIn("Diagnose.bat", [n for _, n in build_zip.PAYLOAD])
        self.assertIn("Diagnose.bat", build_zip.BAT_FILES)


class StarterTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / LAUNCHER).read_text(encoding="ascii")

    def test_startet_die_python_app(self):
        self.assertIn("arena_studio_connector.py", self.text)  # noqa: SLF001

    def test_installiert_python_bei_bedarf(self):
        self.assertIn("winget install --id Python.Python.3.12", self.text)
        self.assertIn("python.org/downloads/windows", self.text)

    def test_bietet_diagnose_und_optionen(self):
        for option in ("/console", "/headless", "/check", "/unblock", "/version", "/help"):
            self.assertIn(option, self.text)

    def test_ohne_pyinstaller_und_exe_denke(self):
        low = self.text.lower()
        self.assertNotIn("pyinstaller", low)
        self.assertNotIn("dist\\", low)
        self.assertIn("--serve", low)  # Standard: Konsole + Zwischenablage

    def test_version_wird_aus_version_datei_gelesen(self):
        # Bewusst kein Parsen der Python-Datei in for-Optionen (Anfuehrungszeichen
        # und Leerzeichen dort sind zu fehleranfaellig) - deshalb VERSION-Datei.
        self.assertTrue('set "VERSIONFILE=%APPDIR%VERSION"' in self.text)
        self.assertTrue('type "%VERSIONFILE%"' in self.text)
        self.assertTrue("!VER:" not in self.text)
        self.assertTrue('findstr /b /c:"APP_VERSION"' not in self.text)

    def test_start_ohne_python_wird_abgefangen(self):
        for needle in ("kein Python 3.9", "python.org/downloads/windows", "choice /c JN"):
            self.assertIn(needle, self.text)

    def test_startet_gui_konsolenlos(self):
        self.assertIn("pythonw.exe", self.text)
        self.assertIn("start \"\"", self.text)

    def test_app_schreibt_lebenszeichen(self):
        # Die .bat wartet auf diese Datei - deshalb muss die App sie anlegen.
        source = (ROOT / "arena_studio_connector.py").read_text(encoding="utf-8")
        self.assertIn("GUI_FLAG", source)
        self.assertIn("gui_flag_path().write_text", source)
        self.assertIn("gui_flag_path().unlink()", source)


class PaketTest(unittest.TestCase):
    def test_version_stimmt_mit_app_ueberein(self):
        self.assertEqual(build_zip.app_version(), APP_VERSION)
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), APP_VERSION)
        self.assertEqual(build_zip.check_version_file(), [])

    def test_zip_enthaelt_alle_dateien(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "test.zip"
            build_zip.build(output)
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as zf:
                namen = set(zf.namelist())
                self.assertEqual(zf.testzip(), None, "ZIP ist beschaedigt")
                for src, name in build_zip.PAYLOAD:
                    self.assertIn(name, namen, f"{name} fehlt im ZIP")
                launcher = zf.read(LAUNCHER)
                self.assertIn(b"\r\n", launcher, "im ZIP muss die .bat CRLF haben")
                self.assertIn(b"arena_studio_connector.py", launcher)
                # Pfade im ZIP immer mit /, nie mit Backslash
                for name in namen:
                    self.assertNotIn("\\", name)
            sums = Path(tmp) / "SHA256SUMS.txt"
            self.assertTrue(sums.exists(), "Pruefsumme fehlt")
            self.assertIn(output.name, sums.read_text(encoding="utf-8"))

    def test_keine_exe_reste_im_projekt(self):
        self.assertFalse((ROOT / "ArenaStudioConnector.spec").exists(),
                         "PyInstaller-Spec wurde nicht entfernt")
        self.assertFalse((ROOT / "build_exe.bat").exists(),
                         "build_exe.bat wurde nicht entfernt")
        workflows = list((ROOT / ".github" / "workflows").glob("*"))
        for wf in workflows:
            text = wf.read_text(encoding="utf-8", errors="ignore").lower()
            with self.subTest(workflow=wf.name):
                self.assertNotIn("pyinstaller", text)
        self.assertTrue((ROOT / "build_zip.py").exists())


class PluginInstallationTest(unittest.TestCase):
    """Das Studio-Plugin muss automatisch (ohne Klick) installiert werden."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "plugin").mkdir()
        (self.root / "plugin" / "ArenaBridgePlugin.lua").write_text(
            (ROOT / "plugin" / "ArenaBridgePlugin.lua").read_text(encoding="utf-8"),
            encoding="utf-8")
        self.plugins = self.root / "plugins"
        self.env = {
            **os.environ,
            "ARENA_APP_DIR": str(self.root),
            "ARENA_PLUGIN_DIR": str(self.plugins),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "arena_studio_connector.py"), *args],
                              capture_output=True, text=True, env=self.env, cwd=str(self.root),
                              timeout=120)

    def test_token_wird_lokal_gemerkt_und_bleibt_stabil(self):
        cfg_path = self.root / "config.json"
        self.assertFalse(cfg_path.exists())
        with mock.patch.dict(os.environ, self.env):
            first = arena.ensure_bridge_token({})
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["bridge_token"], first)
            self.assertNotIn("roblox_api_key", saved)
            # zweiter Start: gleicher Token, sonst muesste das Plugin neu installiert werden
            self.assertEqual(arena.ensure_bridge_token(arena.load_config()), first)
            # eine zweite App-Instanz darf den Token nicht neu wuerfeln
            self.assertEqual(arena.ensure_bridge_token({}), first)

    def test_plugin_wird_in_den_plugin_ordner_geschrieben(self):
        result = self._run("--install-plugin")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dest = self.plugins / "ArenaBridgePlugin.lua"
        self.assertTrue(dest.exists(), "Plugin wurde nicht installiert")
        source = dest.read_text(encoding="utf-8")
        cfg = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("__BRIDGE_TOKEN__", source, "Token-Platzhalter nicht ersetzt")
        self.assertNotIn("__BRIDGE_URL__", source, "URL-Platzhalter nicht ersetzt")
        self.assertIn(cfg["bridge_token"], source)
        self.assertIn("http://127.0.0.1:8765", source)

    def test_zweiter_lauf_laesst_die_datei_unveraendert(self):
        self._run("--install-plugin")
        dest = self.plugins / "ArenaBridgePlugin.lua"
        stamp = dest.stat().st_mtime_ns
        result = self._run("--install-plugin")
        self.assertEqual(result.returncode, 0)
        self.assertIn("aktuell", result.stdout)
        self.assertEqual(dest.stat().st_mtime_ns, stamp, "Datei wurde unnoetig neu geschrieben")

    def test_new_token_rotiert_und_schreibt_das_plugin_neu(self):
        self._run("--install-plugin")
        alt = json.loads((self.root / "config.json").read_text(encoding="utf-8"))["bridge_token"]
        result = self._run("--new-token")
        self.assertEqual(result.returncode, 0, result.stdout)
        neu = json.loads((self.root / "config.json").read_text(encoding="utf-8"))["bridge_token"]
        self.assertNotEqual(alt, neu, "Token wurde nicht rotiert")
        source = (self.plugins / "ArenaBridgePlugin.lua").read_text(encoding="utf-8")
        self.assertIn(neu, source)
        self.assertNotIn(alt, source)

    def test_ohne_plugin_vorlage_kommt_klare_meldung(self):
        # App ohne plugin/-Ordner (kaputt entpacktes ZIP): darf nicht abstuerzen,
        # sondern muss sagen, was los ist.
        (self.root / "plugin" / "ArenaBridgePlugin.lua").unlink()
        app_copy = self.root / "arena_studio_connector.py"
        app_copy.write_text((ROOT / "arena_studio_connector.py").read_text(encoding="utf-8"),
                            encoding="utf-8")
        result = subprocess.run([sys.executable, str(app_copy), "--install-plugin"],
                                capture_output=True, text=True, env=self.env,
                                cwd=str(self.root), timeout=120)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("ZIP", result.stdout)
        self.assertFalse((self.plugins / "ArenaBridgePlugin.lua").exists())


class ServeModusTest(unittest.TestCase):
    """Neuer Ablauf: keine App, Token + URL in der Konsole, Prompt in der
    Zwischenablage, URL + Token im Studio-Plugin eintragen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "plugin").mkdir()
        (self.root / "plugin" / "ArenaBridgePlugin.lua").write_text(
            (ROOT / "plugin" / "ArenaBridgePlugin.lua").read_text(encoding="utf-8"),
            encoding="utf-8")
        self.plugins = self.root / "plugins"
        self.env = {**os.environ,
                    "ARENA_APP_DIR": str(self.root),
                    "ARENA_PLUGIN_DIR": str(self.plugins),
                    "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_tunnel_schreibt_prompt_und_zeigt_token(self):
        log = self.root / "serve.log"
        with open(log, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "arena_studio_connector.py"),
                 "--no-tunnel", "--keine-zwischenablage"],
                stdout=out, stderr=subprocess.STDOUT, env=self.env, cwd=str(self.root))
            try:
                deadline = time.time() + 45
                while time.time() < deadline:
                    time.sleep(0.5)
                    text = log.read_text(encoding="utf-8", errors="replace")
                    if "Laeuft" in text or "Läuft" in text:
                        break
            finally:
                proc.kill()
                proc.wait(timeout=10)

        out_text = log.read_text(encoding="utf-8", errors="replace")
        cfg = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        token = cfg["bridge_token"]
        prompt_file = self.root / "prompt.txt"

        self.assertIn("VERBINDUNGSDATEN", out_text)
        self.assertIn(token, out_text, "Token fehlt in der Konsolenausgabe")
        self.assertIn("Studio-Plugin", out_text)
        self.assertTrue(prompt_file.exists(), "prompt.txt wurde nicht geschrieben")
        prompt = prompt_file.read_text(encoding="utf-8")
        self.assertIn(token, prompt)
        self.assertIn("http://127.0.0.1:8765", prompt)
        self.assertIn("MEINE AUFGABE", prompt)
        self.assertIn("/api/status", prompt)

    def test_installiert_das_plugin_mit_token_vorbelegung(self):
        log = self.root / "serve.log"
        with open(log, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "arena_studio_connector.py"),
                 "--no-tunnel", "--keine-zwischenablage"],
                stdout=out, stderr=subprocess.STDOUT, env=self.env, cwd=str(self.root))
            try:
                deadline = time.time() + 45
                while time.time() < deadline:
                    time.sleep(0.5)
                    if "Laeuft" in log.read_text(encoding="utf-8", errors="replace"):
                        break
            finally:
                proc.kill()
                proc.wait(timeout=10)
        dest = self.plugins / "ArenaBridgePlugin.lua"
        self.assertTrue(dest.exists())
        lua = dest.read_text(encoding="utf-8")
        token = json.loads((self.root / "config.json").read_text(encoding="utf-8"))["bridge_token"]
        self.assertIn(token, lua, "Token nicht als Vorbelegung im Plugin")

    def test_zwischenablage_liefert_ergebnis(self):
        ok, tool = arena.copy_to_clipboard("Test")
        self.assertIsInstance(ok, bool)
        self.assertTrue(tool)

    def test_prompt_hat_aufgaben_platz(self):
        p = arena.build_prompt("https://x.trycloudflare.com", "TOK")
        self.assertIn("MEINE AUFGABE", p)
        self.assertIn("<HIER EINTRAGEN", p)
        self.assertLess(p.index("MEINE AUFGABE"), p.index("SO NUTZT DU"), 
                        "Aufgabe muss vor der Anleitung stehen")
        self.assertIn("Plugin", p)


class PluginUiTest(unittest.TestCase):
    def setUp(self):
        self.lua = (ROOT / "plugin" / "ArenaBridgePlugin.lua").read_text(encoding="utf-8")

    def test_plugin_hat_eingabefelder_fuer_url_und_token(self):
        self.assertIn("CreateDockWidgetPluginGui", self.lua)
        self.assertIn("TextBox", self.lua)
        self.assertIn("Bridge-URL", self.lua)
        self.assertIn("Token", self.lua)
        self.assertIn('SETTING_URL', self.lua)
        self.assertIn('SETTING_TOKEN', self.lua)

    def test_plugin_merkt_sich_die_eingaben(self):
        self.assertIn("plugin:SetSetting", self.lua)
        self.assertIn("plugin:GetSetting", self.lua)

    def test_plugin_prueft_url_und_token(self):
        self.assertIn("^https?://", self.lua)
        self.assertIn("401", self.lua)

    def test_plugin_hat_weiter_alle_kommandos(self):
        for cmd in ("place_info", "list_children", "get_tree", "get_script",
                    "set_script", "create_instance", "set_property",
                    "delete_instance", "execute_luau"):
            self.assertIn(f"handlers.{cmd}", self.lua)


class CliTest(unittest.TestCase):
    def run_app(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "arena_studio_connector.py"), *args],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=120)

    def test_version_ausgabe(self):
        result = self.run_app("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(APP_VERSION, result.stdout)

    def test_check_laeuft_durch(self):
        result = self.run_app("--check")
        self.assertIn("Systemcheck", result.stdout)
        self.assertIn("[OK] Python", result.stdout)
        self.assertIn("App-Ordner", result.stdout)


if __name__ == "__main__":
    unittest.main()
