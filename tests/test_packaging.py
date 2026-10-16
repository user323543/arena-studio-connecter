"""Tests fuer den .bat-Starter und die ZIP-Verteilung.

Diese Tests laufen ueberall (auch ohne Windows), pruefen aber genau die Dinge,
die unter Windows sonst still kaputtgehen: Zeilenenden (CRLF), ASCII, Labels,
goto-Ziele, Klammer-Bloecke und der Inhalt des Release-ZIPs.
"""
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_zip  # noqa: E402
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
        self.assertIn("--headless", low)  # laeuft auch ohne Fenster

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
