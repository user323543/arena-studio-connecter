#!/usr/bin/env python3
"""
build_zip.py - baut das fertige Release-ZIP fuer den Arena Studio Connector.
===========================================================================
Statt einer EXE (PyInstaller, Virenscanner-Aerger, 10 MB Ballast) liefern wir
ein ZIP: entpacken, ArenaStudioConnector.bat doppelklicken - fertig.

Das ZIP ist reproduzierbar (feste Zeitstempel, sortierte Reihenfolge): gleicher
Quellstand -> gleiche Datei, gleicher SHA256-Hash.

Aufruf:
    python build_zip.py            # ZIP nach dist/ bauen
    python build_zip.py --fix      # .bat-Dateien vorher auf CRLF umstellen
    python build_zip.py --output dist/mein.zip
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "dist"
ZIP_STAMP = (1980, 1, 1, 0, 0, 0)  # feste Zeitstempel => reproduzierbares ZIP

# Dateien im ZIP: (Pfad im Projekt, Name im ZIP)
PAYLOAD: list[tuple[str, str]] = [
    ("ArenaStudioConnector.bat", "ArenaStudioConnector.bat"),
    ("ArenaStudioConnector-Konsole.bat", "ArenaStudioConnector-Konsole.bat"),
    ("arena_studio_connector.py", "arena_studio_connector.py"),
    ("plugin/ArenaBridgePlugin.lua", "plugin/ArenaBridgePlugin.lua"),
    (".env.example", ".env.example"),
    ("config.example.json", "config.example.json"),
    ("SO_GEHTS.txt", "SO_GEHTS.txt"),
    ("prompt_beispiel.txt", "prompt_beispiel.txt"),
    ("README.md", "README.md"),
]

# Diese .bat-Dateien werden geprueft/fixiert: die ausgelieferten plus das
# Build-Skript selbst (auch das muss unter Windows laufen).
BAT_FILES = sorted({src for src, _ in PAYLOAD if src.lower().endswith(".bat")} | {"build_zip.bat"})


def app_version() -> str:
    source = (ROOT / "arena_studio_connector.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, re.M)
    if not match:
        raise SystemExit("APP_VERSION wurde in arena_studio_connector.py nicht gefunden.")
    return match.group(1)


def check_zip_names() -> list[str]:
    errors = []
    for src, name in PAYLOAD:
        if not (ROOT / src).exists():
            errors.append(f"fehlt: {src}")
    return errors


def fix_line_endings(verbose: bool = True) -> list[str]:
    """.bat-Dateien auf CRLF bringen - ein .bat mit LF bricht bei goto/for."""
    changed = []
    for name in BAT_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        raw = path.read_bytes()
        fixed = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if fixed != raw:
            path.write_bytes(fixed)
            changed.append(name)
            if verbose:
                print(f"[fix] {name}: Zeilenenden auf CRLF umgestellt")
    return changed


def check_line_endings() -> list[str]:
    problems = []
    for name in BAT_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        raw = path.read_bytes()
        if b"\r\n" not in raw:
            problems.append(f"{name}: keine CRLF-Zeilenenden (Windows .bat braucht CRLF)")
            continue
        if re.search(rb"(?<!\r)\n", raw):
            problems.append(f"{name}: einzelne LF-Zeilen gefunden (CRLF noetig)")
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{name}: UTF-8-BOM am Dateianfang entfernen (stoert cmd)")
    return problems


def _strip_expansions(line: str) -> str:
    """!VAR! entfernen - darin sind " und ( ) nur Text, kein Code.

    %VAR% bleibt absichtlich stehen: die Ersetzung waere zu gierig und wuerde
    %~dp0%APP% bzw. %%V falsch zusammenfassen.
    """
    return re.sub(r"![^!]*!", "", line)


def _scan_line(line: str) -> tuple[int, list[str]]:
    """Liefert Klammer-Delta einer .bat-Zeile und gefundene Probleme.

    Klammern ausserhalb von Quotes zaehlen - Bloecke gehen ueber mehrere
    Zeilen, deshalb nur das Delta. In %VAR% und !VAR! ist alles nur Text.
    """
    text = _strip_expansions(line)
    issues: list[str] = []
    depth = 0
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "^" and i + 1 < len(text):  # maskiertes Zeichen (^) ueberspringen
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        i += 1
    if in_quotes:
        issues.append("ungerade Anzahl doppelter Anfuehrungszeichen")
    return depth, issues


def check_bat_structure() -> list[str]:
    """Findet typische .bat-Killer: doppelte Labels, tote goto-Ziele, Klammern."""
    problems: list[str] = []
    for name in BAT_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        raw = path.read_bytes()
        if any(byte > 127 for byte in raw):
            problems.append(f"{name}: enthaelt Nicht-ASCII-Zeichen (cmd liest .bat "
                            f"in der Konsolen-Codepage - Umlaute vermeiden)")
        lines = raw.decode("ascii", errors="replace").replace("\r\n", "\n").split("\n")
        labels: set[str] = set()
        targets: list[tuple[int, str]] = []
        depth = 0
        for no, line in enumerate(lines, 1):
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("rem") or stripped.startswith("::"):
                continue
            label = re.fullmatch(r":([A-Za-z0-9_.\-]+)", stripped)
            if label:
                if label.group(1).lower() in labels:
                    problems.append(f"{name}:{no}: Label :{label.group(1)} kommt doppelt vor")
                labels.add(label.group(1).lower())
                continue
            for match in re.finditer(r"\b(?:goto|call)\s+:?([A-Za-z0-9_.\-]+)", line, re.I):
                targets.append((no, match.group(1)))
            delta, issues = _scan_line(line)
            for issue in issues:
                problems.append(f"{name}:{no}: {issue}")
            depth += delta
            if depth < 0:
                problems.append(f"{name}:{no}: schliessende Klammer ohne passende oeffnende")
                depth = 0
        if depth > 0:
            problems.append(f"{name}: {depth} Klammer(n) wurden nie geschlossen")
        for no, target in targets:
            if target.lower() not in labels:
                problems.append(f"{name}:{no}: Ziel :{target} existiert nicht (goto/call)")
    return problems


def build(output: Path) -> Path:
    version = app_version()
    missing = check_zip_names()
    if missing:
        raise SystemExit("Abbruch - diese Dateien fehlen:\n  " + "\n  ".join(missing))
    problems = check_line_endings()
    if problems:
        raise SystemExit("Abbruch - Zeilenenden pruefen (oder --fix benutzen):\n  "
                         + "\n  ".join(problems))
    structure = check_bat_structure()
    if structure:
        raise SystemExit("Abbruch - die .bat-Dateien haben Fehler:\n  "
                         + "\n  ".join(structure))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, name in payload_sorted():
            info = zipfile.ZipInfo(name, date_time=ZIP_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (ROOT / src).read_bytes())

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    size_kb = output.stat().st_size / 1024
    print(f"[OK] ZIP gebaut: {output}")
    print(f"     Version: {version}")
    print(f"     Inhalt:  {len(PAYLOAD)} Dateien, {size_kb:.1f} KB")
    print(f"     SHA256:  {digest}")

    sums = output.parent / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"[OK] Pruefsumme: {sums}")
    return output


def payload_sorted() -> list[tuple[str, str]]:
    """Sortiert, damit das ZIP bei gleichem Quellstand byte-identisch bleibt."""
    return sorted(PAYLOAD, key=lambda item: item[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-ZIP des Arena Studio Connectors bauen")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Zieldatei (Standard: dist/ArenaStudioConnector-v<Version>.zip)")
    parser.add_argument("--fix", action="store_true",
                        help=".bat-Dateien vorher auf CRLF umstellen")
    args = parser.parse_args(argv)

    if args.fix:
        fixed = fix_line_endings()
        if not fixed:
            print("[i] Zeilenenden waren schon in Ordnung.")

    version = app_version()
    output = args.output or (DEFAULT_OUTPUT_DIR / f"ArenaStudioConnector-v{version}.zip")
    build(output)

    print()
    print("Weitergeben: ZIP verschicken/hochladen - Empfaenger entpackt es und")
    print("doppelklickt ArenaStudioConnector.bat. Python installiert der Starter")
    print("bei Bedarf selbst (winget) oder verlinkt die Download-Seite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
