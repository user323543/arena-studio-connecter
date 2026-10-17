# 🎮 Arena Studio Connector

Verbinde **Arena AI mit deinem Roblox Studio**: Ein Doppelklick auf eine `.bat`
startet eine lokale Bridge + Cloudflare-Tunnel, **zeigt Tunnel-URL und Token im
Fenster** und kopiert einen fertigen Prompt in die Zwischenablage. Den fügst du
bei Arena AI ein, schreibst darunter, was gemacht werden soll – und trägst URL +
Token einmal im **Studio-Plugin** ein. Danach kann Arena in deiner geöffneten
Place arbeiten (Scripts lesen/schreiben, Objekte erstellen, Eigenschaften ändern,
Luau ausführen) und über die Bridge sogar Creator-Dashboard-Aktionen anstoßen
(GamePässe, Developer-Produkte, Badges, DataStores …), **ohne dass dein
Roblox-API-Key deinen PC je verlässt.**

> **Es öffnet sich kein App-Fenster (mehr).** Alles passiert im `.bat`-Fenster:
> Token + URL stehen dort, der Prompt landet in der Zwischenablage. Die alte
> GUI gibt es optional mit `ArenaStudioConnector.bat /gui`.

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
| Lädt den Code vorab und prüft die Plugin-Datei | Fehler erscheinen im Klartext statt still |
| Startet Bridge + Tunnel **im `.bat`-Fenster** | Token + URL stehen direkt da, kein extra App-Fenster |
| Kopiert den Prompt in die Zwischenablage und speichert `prompt.txt` | einfügen bei Arena AI ohne Suchen |
| Schreibt `start_log.txt` + zeigt bei Fehlern die Ursache | nichts scheitert lautlos |

### 3. So läuft es ab (der eigentliche Ablauf)

```
1. Doppelklick auf ArenaStudioConnector.bat
      -> Fenster zeigt:  Tunnel-URL  +  Token  +  lokale URL
      -> Prompt (mit URL, Token und Platz für deine Aufgabe) ist in der Zwischenablage
      -> Fenster OFFEN LASSEN (das ist die Bridge)

2. Roblox Studio öffnen -> Plugins-Tab -> ArenaBridge
      Bridge-URL = http://127.0.0.1:8765        (die "lokale URL" aus der .bat)
      Token      = ...                           (der Token aus der .bat)
      -> "Verbinden" klicken   (wird für das nächste Mal gespeichert)

3. Bei Arena AI einfügen (Strg+V) und darunter schreiben, was gemacht werden soll:
      "Baue ein Spawn-Gebäude mit 3 Etagen."
      "Erstelle einen GamePass 'VIP' für 100 Robux."
   Die Zeile "<HIER EINTRAGEN, was gemacht werden soll>" im Prompt ersetzt du
   einfach durch deine Aufgabe.

4. Fertig. Arena verbindet sich über den Tunnel mit deiner Bridge und arbeitet
   in der offenen Place. Beenden: im .bat-Fenster Strg+C.
```

**Wichtig zu den zwei Adressen**

| Adresse | Wofür | Wo eintragen |
|---|---|---|
| `http://127.0.0.1:8765` | verbindet das **Studio-Plugin** mit deiner Bridge auf demselben PC | im Plugin-Feld *Bridge-URL* |
| `https://….trycloudflare.com` | damit **Arena AI** von außen an deine Bridge kommt | nur im Prompt (automatisch) |

Der **Token** ist beide Male derselbe. `prompt.txt` liegt zusätzlich neben der
`.bat` – falls das Kopieren in die Zwischenablage mal nicht klappt, kannst du
den Text von dort nehmen.

### 4. (Optional, nur für Dashboard-Aktionen) Roblox API-Key eintragen
Für reines Arbeiten **in Studio** brauchst du **keinen** Key.
Nur wenn Arena z. B. GamePässe/Developer-Produkte erstellen soll:

1. `.env.example` als **`.env`** kopieren (liegt neben der `.bat`).
2. Das ausführliche Tutorial **in der `.env.example`** befolgen
   (Key auf <https://create.roblox.com/dashboard/credentials> erstellen,
   dort steht auch exakt, **welche Berechtigungen wofür** nötig sind).
3. Key in die `.env` eintragen.

⚠️ **Der Key ist wie ein Passwort.** Niemals an Arena schicken, niemals
öffentlich posten. `.env` und `config.json` stehen in `.gitignore`.

### 5. Studio-Plugin 🔌
Das Plugin wird **automatisch** in den Roblox-Plugin-Ordner geschrieben
(`%LOCALAPPDATA%\Roblox\Plugins\ArenaBridgePlugin.lua`), vorbelegt mit
lokaler URL und Token. Beim ersten Öffnen in Studio trägst du URL + Token
ein (falls die Vorbelegung fehlt) und klickst **„Verbinden"** – beides wird
gespeichert und beim nächsten Mal automatisch verwendet. Details und
Sonderfälle (Store-Version von Studio, eigener Ordner, Token wechseln) siehe
unten.

---

## 🧰 Starter-Optionen (für den Fall der Fälle)

```powershell
ArenaStudioConnector.bat              # Standard: Bridge + Tunnel, Token/URL, Prompt in der Zwischenablage
ArenaStudioConnector.bat /gui         # optionale App mit Fenster (braucht tkinter)
ArenaStudioConnector.bat /places Max  # Places von Roblox-User "Max" mit PlaceId/UniverseId
ArenaStudioConnector.bat /check       # Systemcheck: Python, tkinter, Plugin, Port, cloudflared
ArenaStudioConnector.bat /plugin      # Studio-Plugin jetzt installieren/aktualisieren
ArenaStudioConnector.bat /newtoken    # neuen Bridge-Token + Plugin neu schreiben
ArenaStudioConnector.bat /headless    # wie Standard (Alias)
ArenaStudioConnector.bat /unblock     # Windows-Sperre „Datei aus dem Internet" entfernen
ArenaStudioConnector.bat /help        # Hilfe anzeigen
ArenaStudioConnector.bat /version     # Version anzeigen
```

Bei Problemen: **`ArenaStudioConnector-Konsole.bat`** oder **`Diagnose.bat`**
starten – dort steht, was schiefgeht. Der Starter schreibt außerdem
`start_log.txt`, die App Startfehler nach `last_error.log` (beide neben der
`.bat`). Der Starter öffnet sich bei Doppelklick grundsätzlich in einem
Fenster, das auch bei Fehlern offen bleibt – es kann also nichts mehr
unbemerkt „durchblitzen“.

---

## 🔁 So funktioniert es

```
ArenaStudioConnector.bat ──► Bridge (127.0.0.1:8765) + Tunnel-URL + Token im Fenster
                          └─► Prompt in die Zwischenablage (prompt.txt)

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

## 🆘 „Fenster blitzt nur kurz auf und ist sofort weg"

Das heißt: **die .bat ist gestartet und vor der ersten Ausgabe wieder beendet
worden.** Ab Version 1.1.1 passiert das nicht mehr still – der Starter startet
sich bei Doppelklick selbst in einem Fenster, das **auch bei Fehlern offen
bleibt** (`cmd /k`). Zusätzlich schreibt er `start_log.txt` neben die `.bat`.

Wenn es bei dir weiterhin blitzt, hilft diese Reihenfolge:

1. **ZIP vor dem Entpacken zulassen** (häufigste Ursache bei Downloads):
   Rechtsklick auf die **ZIP-Datei** → *Eigenschaften* → unten bei *Sicherheit*
   **„Zulassen"** anhaken (bzw. „Entsperren"/„Unblock") → *OK* → **erst dann**
   entpacken. Dateien aus dem Internet sind markiert, und Windows blockt
   `.bat`-Dateien dann gerne ohne sichtbare Meldung.
   Alternativ in PowerShell:
   ```powershell
   Get-ChildItem "$env:USERPROFILE\Downloads" -Recurse -File | Unblock-File
   ```
2. **Nicht aus der ZIP-Vorschau starten.** Die Datei muss in einem normalen
   Ordner liegen (der Starter erkennt einen Temp-Ordner und sagt es dir).
3. **Fehlermeldung sichtbar machen** – in einem eigenen Fenster, das offen
   bleibt:
   * `Win + R` → `cmd` → Enter
   * `cd /d "C:\Pfad\zu\deinem\Ordner"`
   * `ArenaStudioConnector.bat /console` → Enter
   Jetzt steht die Meldung da. Alternativ **ArenaStudioConnector-Konsole.bat**
   doppelklicken.
4. **Diagnose.bat** doppelklicken. Sie ändert nichts, schreibt aber
   `diagnose_log.txt` in den Ordner: Windows-Version, ob Python gefunden wird,
   ob `tkinter` da ist, die Dateien im Ordner und die Ausgabe von
   `--check`. Diese Datei einfach mitschicken.
5. Wenn selbst die Diagnose nur blitzt: Dann blockiert sehr wahrscheinlich
   **Virenscanner, AppLocker oder eine Firmen-Richtlinie** `.bat`-Dateien.
   Der Connector lässt sich auch **ganz ohne .bat** starten:
   ```powershell
   cd "C:\Pfad\zu\deinem\Ordner"
   python arena_studio_connector.py --check
   python arena_studio_connector.py
   ```

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

**„Ich will die alte App mit Places-Liste."**
`ArenaStudioConnector.bat /gui` (oder `ArenaStudioConnector-Konsole.bat`).
Für den normalen Ablauf brauchst du sie nicht: `/places <Username>` zeigt
PlaceId/UniverseId in der Konsole, und welche Place offen ist, liest Arena
automatisch aus `/api/status`.

**„Wo ist das Studio-Plugin nach dem Neustart hin?"**
Klick in Studio auf den Toolbar-Button **„ArenaBridge"**. Findest du ihn
nicht, prüfe `ArenaStudioConnector.bat /check` – dort steht der komplette
Pfad. Zur Not in Studio unter *Plugins → Plugins-Ordner* nachsehen; die
Installation passiert automatisch bei jedem App-Start.

**Das Plugin sagt „Datei fehle" bzw. die Installation schlägt fehl.**
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
| `Diagnose.bat` | schreibt `diagnose_log.txt` (Python, tkinter, Dateien, `--check`) – für die Fehlersuche |
| `arena_studio_connector.py` | Komplette App (GUI + Bridge + Tunnel + Prompt-Generator) |
| `VERSION` | Version für `/version` – `build_zip.py` prüft, dass sie zu `APP_VERSION` passt |
| `plugin/ArenaBridgePlugin.lua` | Roblox-Studio-Plugin – wird beim App-Start **automatisch** nach `%LOCALAPPDATA%\Roblox\Plugins` installiert |
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
