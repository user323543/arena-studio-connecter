# 🎮 Arena Studio Connector

Verbinde **Arena AI mit deinem Roblox Studio**: Eine kleine Windows-App startet
eine lokale Bridge + Cloudflare-Tunnel, zeigt deine Roblox-Places an und kopiert
per Button einen fertigen Prompt. Den schickst du an Arena AI – Arena kann dann
in deiner geöffneten Studio-Place arbeiten (Scripts lesen/schreiben, Objekte
erstellen, Eigenschaften ändern, Luau ausführen) und über deine lokale Bridge
sogar Creator-Dashboard-Aktionen anstoßen (GamePässe, Developer-Produkte,
Badges, DataStores …), **ohne dass dein Roblox-API-Key deinen PC je verlässt.**

> **Verteilung: ZIP + `.bat` – keine EXE.**
> Es wird nichts kompiliert und nichts installiert: ZIP entpacken,
> `ArenaStudioConnector.bat` doppelklicken. Fehlt Python, installiert der
> Starter es auf Wunsch selbst (winget) oder öffnet die Download-Seite.
> Vorteil gegenüber einer PyInstaller-EXE: keine 10 MB, keine
> Virenscanner-Falschmeldungen, Code bleibt lesbar.

---

## 🚀 Schnellstart

### 1. ZIP holen und **entpacken**
GitHub → **Actions** → letzter Lauf von „Build ZIP" → Artifact
**ArenaStudioConnector-zip** herunterladen. Bei einem Release einfach
`ArenaStudioConnector-v<Version>.zip` laden.

Dann: **Rechtsklick auf die ZIP → „Alle extrahieren …"**. Bitte nicht direkt
aus dem ZIP-Fenster starten – sonst fehlen Dateien wie
`plugin\ArenaBridgePlugin.lua`.

### 2. `ArenaStudioConnector.bat` doppelklicken
Der Starter erledigt alles Nötige:

| Was der Starter macht | Warum |
|---|---|
| Sucht Python 3.9+ (`py`, `python`, typische Installationsordner, Store) | kein manuelles Suchen |
| Bietet bei Bedarf die Installation über `winget` an | „Add to PATH"/„tcl/tk" wird automatisch richtig gesetzt |
| Prüft `tkinter`, Plugin-Datei und lädt den Code vorab | Fehler erscheinen im Klartext statt still |
| Startet die App über `pythonw.exe` | Fenster-App, ohne schwarzes Konsolenfenster |
| Schreibt `last_error.log` + zeigt bei Startfehlern die Ursache | nichts scheitert lautlos |

### 3. (Optional, nur für Dashboard-Aktionen) Roblox API-Key eintragen
Für reines Arbeiten **in Studio** brauchst du **keinen** Key.
Nur wenn Arena z. B. GamePässe/Developer-Produkte erstellen soll:

1. `.env.example` als **`.env`** kopieren (liegt neben der `.bat`).
2. Das ausführliche Tutorial **in der `.env.example`** befolgen
   (Key auf <https://create.roblox.com/dashboard/credentials> erstellen,
   dort steht auch exakt, **welche Berechtigungen wofür** nötig sind).
3. Key in die `.env` eintragen. Die App liest ihn auch direkt aus dem
   Key-Feld in der GUI. Alternativ `config.example.json` → `config.json`
   für Username/Port.

⚠️ **Der Key ist wie ein Passwort.** Niemals an Arena schicken, niemals
öffentlich posten. `.env` und `config.json` stehen in `.gitignore`.

### 4. App benutzen
1. Roblox-Username eintragen → **„Places laden"**.
2. **„Bridge + Tunnel starten"** → kurz warten, bis die Tunnel-URL erscheint
   (die App lädt `cloudflared` bei Bedarf selbst von GitHub herunter).
3. **„Studio-Plugin installieren"** → Roblox Studio neu starten, die
   gewünschte Place öffnen, im Plugin-Toolbar-Button **„ArenaBridge"**
   klicken und beim ersten Mal den Zugriff auf `127.0.0.1` erlauben.
4. In der App beim gewünschten Spiel auf **„📋 Prompt kopieren"** klicken.
5. Prompt bei **Arena AI einfügen**, danach einfach sagen, was Arena in
   Studio machen soll (z. B. „Baue ein Spawn-Gebäude" oder „Erstelle einen
   GamePass für 100 Robux").

Token & Tunnel-URL gelten nur, solange die App läuft. Zum Trennen einfach
die App schließen / „Stoppen" klicken.

---

## 🧰 Starter-Optionen (für den Fall der Fälle)

```powershell
ArenaStudioConnector.bat              # normale App (Fenster, ohne Konsole)
ArenaStudioConnector-Konsole.bat      # gleiches, aber mit allen Meldungen
ArenaStudioConnector.bat /check       # Systemcheck: Python, tkinter, Plugin, Port, cloudflared
ArenaStudioConnector.bat /headless    # nur Bridge + Tunnel, ohne Fenster
ArenaStudioConnector.bat /unblock     # Windows-Sperre „Datei aus dem Internet" entfernen
ArenaStudioConnector.bat /help        # Hilfe anzeigen
ArenaStudioConnector.bat /version     # Version anzeigen
```

Bei Problemen: **`ArenaStudioConnector-Konsole.bat`** starten – dort steht,
was schiefgeht. Zusätzlich schreibt die App Startfehler nach
`last_error.log` (liegt neben der `.bat`).

---

## 🔁 So funktioniert es

```
Arena AI ──HTTPS──► Cloudflare Tunnel ──► Bridge (dein PC, 127.0.0.1:8765)
                                              │  ▲
                          Open Cloud (lokal,  │  │ pollt lokal
                          Key bleibt hier)    ▼  │
                                     Roblox Studio Plugin ──► deine Place
```

- **Bridge** (`arena_studio_connector.py`): token-geschützte HTTP-API.
- **Studio-Plugin** (`plugin/ArenaBridgePlugin.lua`): fragt die Bridge lokal
  nach Kommandos und führt sie in Studio aus. Spricht nie direkt mit dem
  Internet – nur mit `127.0.0.1`.
- **Prompt**: enthält Tunnel-URL, Bridge-Token, **PlaceId + UniverseId** und
  eine komplette Anleitung für Arena (Verbindungsprüfung, alle Kommandos mit
  Curl-Beispielen, Open-Cloud-Proxy, Sicherheitsregeln). Beispiel:
  `prompt_beispiel.txt`.

### Was Arena über die Bridge kann
| Endpunkt | Zweck |
|---|---|
| `GET /api/status` | Verbindung + geöffnete Place prüfen |
| `POST /api/command` | `place_info`, `list_children`, `get_tree`, `get_script`, `set_script`, `create_instance`, `set_property`, `delete_instance`, `execute_luau` |
| `POST /api/execute` | Beliebiges Luau im Studio ausführen |
| `POST /api/roblox/open-cloud` | Beliebiger Roblox-Open-Cloud-Call – Bridge hängt deinen Key **lokal** an |
| `POST /api/roblox/game-pass` / `/developer-product` | GamePass / Dev-Produkt anlegen (UniverseId, Name, Preis …) |
| `GET /api/docs` | Komplette API-Doku für Arena |

Alle Anfragen brauchen `Authorization: Bearer <Token>` aus dem Prompt.

### Ehrliche Einschränkung
Nicht jede Dashboard-Aktion gibt Roblox per API-Key frei. GamePässe und
Developer-Produkte funktionieren per Open Cloud nur, wenn der Key die
passenden Rechte hat (siehe Tutorial in `.env.example`). Sonst antwortet
Roblox mit 401/403 – die Bridge reicht die Meldung unverändert an Arena
weiter, damit Arena dir exakt sagen kann, welche Berechtigung fehlt, statt
so zu tun, als hätte es geklappt.

---

## 🆘 Häufige Fragen / Probleme

**„Es öffnet sich nichts."**
`ArenaStudioConnector-Konsole.bat` doppelklicken (Meldungen sichtbar) oder
`/check` laufen lassen. Ein Startfehler landet zusätzlich in `last_error.log`.

**„Windows hat die Datei blockiert" / SmartScreen.**
Bei einem selbst heruntergeladenen ZIP kann Windows die Dateien sperren.
Dann `ArenaStudioConnector.bat /unblock` ausführen (entfernt die
„Datei aus dem Internet"-Markierung für den ganzen Ordner).

**„Windows hat kein Python gefunden."**
Der Starter kann Python selbst installieren (Nachfrage: „Python jetzt
automatisch installieren?"). Manuell: <https://www.python.org/downloads/windows/>
– beim Installer **„Add python.exe to PATH"** ankreuzen und
**„tcl/tk and IDLE"** angehakt lassen (ohne tkinter gibt es kein Fenster).

**„`python` öffnet nur den Microsoft Store."**
Das ist der Store-Platzhalter, kein Python. Der Starter erkennt ihn, nutzt
kein echtes Python daraus und bietet stattdessen die Installation an.

**„Port 8765 ist belegt."**
Meist läuft die App schon in einem anderen Fenster. Sonst in `config.json`
einen anderen Port eintragen (z. B. `8766`).

**„Studio-Plugin installieren" sagt, die Datei fehle.**
Das ZIP wurde nicht komplett entpackt. Komplett entpacken und die App neu
starten – es muss `plugin\ArenaBridgePlugin.lua` neben der `.bat` liegen.

**Reicht eine `.bat`, die nur den Prompt in die Zwischenablage kopiert?**
Technisch ja (genau das war der ursprüngliche Plan). Mit der Places-Liste
weiß Arena aber immer exakt, welche Place gemeint ist – das verhindert, dass
in der falschen Experience gearbeitet wird. Deshalb startet die `.bat` die
kleine GUI und nicht nur einen Copy-Befehl.

---

## 🗂️ Dateien

| Datei | Zweck |
|---|---|
| `ArenaStudioConnector.bat` | **Starter** – doppelklicken (Python-Suche, Prüfungen, App-Start) |
| `ArenaStudioConnector-Konsole.bat` | gleicher Start, aber mit Konsolenfenster (Diagnose) |
| `arena_studio_connector.py` | Komplette App (GUI + Bridge + Tunnel + Prompt-Generator) |
| `VERSION` | Version für `/version` – `build_zip.py` prüft, dass sie zu `APP_VERSION` passt |
| `plugin/ArenaBridgePlugin.lua` | Roblox-Studio-Plugin (wird von der App installiert) |
| `.env.example` | **Tutorial + Rechte-Liste für den Roblox API-Key** – als `.env` kopieren |
| `config.example.json` | Vorlage für `config.json` (Username, Port) |
| `SO_GEHTS.txt` | Kurzanleitung, die im ZIP mitgeliefert wird |
| `prompt_beispiel.txt` | So sieht der kopierte Prompt aus |
| `build_zip.py` + `build_zip.bat` | Release-ZIP bauen (`dist/ArenaStudioConnector-v<Version>.zip` + SHA256) |
| `.github/workflows/build-zip.yml` | ZIP automatisch bauen, Tests + `.bat`-Test auf Windows |
| `tests/test_bridge.py` | Tests: Auth, Kommando-Roundtrip, Prompt-Inhalt |
| `tests/test_packaging.py` | Tests: `.bat`-Struktur (CRLF, ASCII, Labels, Klammern), ZIP-Inhalt |

## 📦 ZIP selbst bauen
```powershell
build_zip.bat                 # oder:  python build_zip.py
```
Ergebnis: `dist\ArenaStudioConnector-v<Version>.zip` + `dist\SHA256SUMS.txt`.
Der Build prüft automatisch, dass die `.bat`-Dateien CRLF, ASCII, gültige
Labels/Ziele und geschlossene Klammer-Blöcke haben (`--fix` repariert die
Zeilenenden).

## 🧪 Entwickeln / Testen
```powershell
python arena_studio_connector.py             # GUI starten
python arena_studio_connector.py --headless  # nur Bridge+Tunnel (Konsole)
python arena_studio_connector.py --check     # Systemcheck
python -m unittest discover -s tests -v      # Tests
```
